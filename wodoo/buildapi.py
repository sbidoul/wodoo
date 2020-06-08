import shutil
import subprocess
import tarfile
import tempfile
import textwrap
from email.generator import Generator
from email.message import Message
from email.parser import HeaderParser
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Tuple

import toml
from setuptools_odoo import get_addon_metadata  # type: ignore
from wheel.wheelfile import WheelFile  # type: ignore

from . import __version__

TAG = "py3-none-any"  # TODO py2 for Odoo <= 11
INJECTOR = textwrap.dedent(
    """\
        import os


        def symlink_to(metadata_dir, src):
            here = os.path.dirname(__file__)
            dst = os.path.join(here, "odoo", "addons", os.path.basename(src))
            if not os.path.islink(dst):
                os.makedirs(os.path.join(here, "odoo", "addons"), exist_ok=True)
                os.symlink(src, dst)
                with open(os.path.join(here, metadata_dir, "RECORD"), "a") as f:
                    f.write("odoo/addons/{},,\\n".format(os.path.basename(src)))
    """
)


class UnsupportedOperation(NotImplementedError):
    pass


class NoScmFound(Exception):
    pass


def _load_pyproject_toml(addon_dir: Path) -> MutableMapping[str, Any]:
    pyproject_toml_path = addon_dir / "pyproject.toml"
    if pyproject_toml_path.exists():
        with open(pyproject_toml_path) as f:
            return toml.load(f)
    return {}


def _scm_ls_files(addon_dir: Path) -> List[str]:
    try:
        return (
            subprocess.check_output(
                ["git", "ls-files"], universal_newlines=True, cwd=addon_dir
            )
            .strip()
            .split("\n")
        )
    except subprocess.CalledProcessError:
        raise NoScmFound()


def _copy_to(addon_dir: Path, dst: Path) -> None:
    if _get_pkg_info_metadata(addon_dir):
        # if PKG-INFO is present, assume we are in an sdist, copy everything
        shutil.copytree(addon_dir, dst)
        return
    # copy scm controlled files
    try:
        scm_files = _scm_ls_files(addon_dir)
    except NoScmFound:
        # TODO DO NOT UNCOMMENT, until pip builds in place.
        # TODO In case pip copies, this will crash because of
        # TODO missing .git directory. If it would not crash
        # TODO the addon name would be wrong because cwd is a temp dir.
        # shutil.copytree(addon_dir, dst)
        raise
    else:
        dst.mkdir()
        for f in scm_files:
            d = Path(f).parent
            dstd = dst / d
            if not dstd.is_dir():
                dstd.mkdir(parents=True)
            shutil.copy(addon_dir / f, dstd)


def _ensure_absent(paths: List[Path]) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


def _write_metadata(path: Path, msg: Message) -> None:
    with open(path, "w", encoding="utf-8") as out:
        Generator(out, mangle_from_=False, maxheaderlen=0).flatten(msg)


def _prepare_wheel_metadata() -> Message:
    msg = Message()
    msg["Wheel-Version"] = "1.0"  # of the spec
    msg["Generator"] = "Wodoo " + __version__
    msg["Root-Is-Purelib"] = "true"
    msg["Tag"] = TAG
    return msg


def _make_dist_info(metadata: Message, dst: Path) -> str:
    dist_info_dirname = "{}-{}.dist-info".format(
        metadata["Name"].replace("-", "_"), metadata["Version"]
    )
    dist_info_path = Path(dst) / dist_info_dirname
    dist_info_path.mkdir()
    _write_metadata(dist_info_path / "WHEEL", _prepare_wheel_metadata())
    _write_metadata(dist_info_path / "METADATA", metadata)
    (dist_info_path / "top_level.txt").write_text("odoo")
    return dist_info_dirname


def _make_pkg_info(metadata: Message, dst: Path) -> None:
    _write_metadata(Path(dst) / "PKG-INFO", metadata)


def _get_addon_name(addon_dir: Path) -> str:
    return Path(addon_dir).resolve().name


def _get_wheel_name(metadata: Message) -> str:
    return "{}-{}-{}.whl".format(
        metadata["Name"].replace("-", "_"), metadata["Version"], TAG
    )


def _get_sdist_base_name(metadata: Message) -> str:
    return "{}-{}".format(metadata["Name"], metadata["Version"])


def _get_pkg_info_metadata(addon_dir: Path) -> Optional[Message]:
    pkg_info_path = Path(addon_dir) / "PKG-INFO"
    if not pkg_info_path.exists():
        return None
    with open("PKG-INFO", encoding="utf-8") as fp:
        return HeaderParser().parse(fp)


def _get_metadata(
    addon_dir: Path, local_version_identifier: Optional[str] = None
) -> Message:
    pkg_info_metadata = _get_pkg_info_metadata(addon_dir)
    if pkg_info_metadata:
        # if PKG-INFO is present, assume we are in an sdist
        return pkg_info_metadata
    options = (
        _load_pyproject_toml(addon_dir)
        .get("tool", {})
        .get("wodoo", {})
        .get("options", {})
    )
    metadata = get_addon_metadata(
        addon_dir,
        depends_override=options.get("depends_override", {}),
        external_dependencies_override=options.get(
            "external_dependencies_override", {}
        ),
        odoo_version_override=options.get("odoo_version_override"),
    )
    if local_version_identifier:
        metadata.replace_header(
            "Version", metadata["Version"] + "+" + local_version_identifier
        )
    return metadata  # type: ignore


def _build_wheel(
    addon_dir: Path,
    wheel_directory: Path,
    include_src: bool = True,
    include_pth: bool = False,
    local_version_identifier: Optional[str] = None,
) -> Tuple[str, str, str]:
    addon_name = _get_addon_name(addon_dir)
    metadata = _get_metadata(
        addon_dir, local_version_identifier=local_version_identifier
    )
    wheel_name = _get_wheel_name(metadata)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        # always include metadata
        dist_info_dirname = _make_dist_info(metadata, tmppath)
        if include_src:
            assert not include_pth
            odoo_addon_path = tmppath / "odoo" / "addons"
            odoo_addon_path.mkdir(parents=True)
            odoo_addon_path = odoo_addon_path / addon_name
            _copy_to(addon_dir, odoo_addon_path)
            # we don't want pyproject.toml nor PKG-INFO in the wheel
            _ensure_absent(
                [odoo_addon_path / "pyproject.toml", odoo_addon_path / "PKG-INFO"]
            )
        if include_pth:
            assert not include_src
            injector_name = "{}__editable".format(metadata["Name"].replace("-", "_"))
            with (tmppath / (injector_name + ".pth")).open("w") as f:
                f.write(
                    "import {injector_name}; {injector_name}."
                    "symlink_to({dist_info_dirname!r}, {addon_dir!r})\n".format(
                        injector_name=injector_name,
                        dist_info_dirname=dist_info_dirname,
                        addon_dir=str(addon_dir),
                    )
                )
            with (tmppath / (injector_name + ".py")).open("w") as f:
                f.write(INJECTOR)
        with WheelFile(wheel_directory / wheel_name, "w") as wf:
            wf.write_files(tmpdir)
    return wheel_name, dist_info_dirname, addon_name


def build_wheel(
    wheel_directory: str,
    config_settings: Optional[Dict[str, Any]] = None,
    metadata_directory: Optional[str] = None,
) -> str:
    wheel_name, _, _ = _build_wheel(Path.cwd(), Path(wheel_directory))
    return wheel_name


def build_wheel_for_editable(
    wheel_directory: str,
    scheme: Dict[str, str],
    config_settings: Optional[Dict[str, Any]] = None,
    metadata_directory: Optional[str] = None,
) -> str:
    print("*********", scheme)
    wheel_name, _, _ = _build_wheel(
        Path.cwd(),
        Path(wheel_directory),
        include_src=False,
        include_pth=True,
        local_version_identifier="editable",
    )
    return wheel_name


def _build_sdist(addon_dir: Path, sdist_directory: Path) -> Tuple[str, str]:
    addon_name = _get_addon_name(addon_dir)
    metadata = _get_metadata(addon_dir)
    sdist_name = _get_sdist_base_name(metadata)
    sdist_tar_name = sdist_name + ".tar.gz"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpppath = Path(tmpdir)
        sdist_tmpdir = tmpppath / sdist_name
        _copy_to(addon_dir, sdist_tmpdir)
        _make_pkg_info(metadata, sdist_tmpdir)
        with tarfile.open(
            str(sdist_directory / sdist_tar_name),
            mode="w|gz",
            format=tarfile.PAX_FORMAT,
        ) as tf:
            tf.add(str(sdist_tmpdir), arcname=sdist_name)
    return sdist_tar_name, addon_name


def build_sdist(
    sdist_directory: str, config_settings: Optional[Dict[str, Any]] = None
) -> str:
    sdist_tar_name, _ = _build_sdist(Path.cwd(), Path(sdist_directory))
    return sdist_tar_name
