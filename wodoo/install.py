import contextlib
import csv
import hashlib
import json
import subprocess
import sys
import sysconfig
import tempfile
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Generator, Tuple

from .buildapi import _build_wheel

INSTALLER = "wodoo"


def _get_purelib_path(python: str) -> Path:
    if python == sys.executable:
        return Path(sysconfig.get_paths()["purelib"])
    return Path(
        subprocess.check_output(
            [python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            universal_newlines=True,
        ).strip()
    )


def _hash_file(path: Path) -> Tuple[str, str]:
    """Return RECORD compatible (hash, length) for path."""
    with path.open("rb") as f:
        block = f.read()
    h = hashlib.sha256()
    h.update(block)
    return (
        "sha256=" + urlsafe_b64encode(h.digest()).decode("latin1").rstrip("="),
        str(len(block)),
    )


@contextlib.contextmanager
def _replace_metadata_file(
    purelib_path: Path, dist_info_dirname: str, name: str
) -> Generator:
    record = dist_info_dirname + "/" + name
    record_path = purelib_path / dist_info_dirname / "RECORD"
    tmp_record_path = purelib_path / dist_info_dirname / "RECORD.wodoo"
    path = purelib_path / dist_info_dirname / name
    tmp_path = purelib_path / dist_info_dirname / (name + ".wodoo")
    with tmp_path.open("w", encoding="utf-8") as f:
        yield f
    with tmp_record_path.open("w") as outf:
        writer = csv.writer(outf)
        with record_path.open() as inf:
            for row in csv.reader(inf):
                if row[0] == record:
                    # skip record for file we are replacing
                    continue
                writer.writerow(row)
        # write record for file we are writing
        writer.writerow((record,) + _hash_file(tmp_path))
    # commit changes
    tmp_path.rename(path)
    tmp_record_path.rename(record_path)


def install(addon_dir: Path, python: str) -> None:
    # This the same as "python -m pip install <addon_dir>",
    # but faster because it avoids initialization of a build environment.
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        wheel_name, dist_info_dirname, _ = _build_wheel(addon_dir, tmppath)
        # see https://github.com/pypa/pip/issues/7678 for discussion about --upgrade
        subprocess.check_call(
            [python, "-m", "pip", "install", "--upgrade", tmppath / wheel_name]
        )
        purelib_path = _get_purelib_path(python)
        # overwrite INSTALLER so it is not pip
        with _replace_metadata_file(purelib_path, dist_info_dirname, "INSTALLER") as f:
            f.write(INSTALLER)
        # overwrite direct_url.json so it is not the temporary wheel
        with _replace_metadata_file(
            purelib_path, dist_info_dirname, "direct_url.json"
        ) as f:
            json.dump({"url": addon_dir.resolve().as_uri(), "dir_info": {}}, f)


def install_symlink(addon_dir: Path, python: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        wheel_name, dist_info_dirname, addon_name = _build_wheel(
            addon_dir,
            tmppath,
            include_src=False,
            include_pth=False,
            local_version_identifier="editable",
        )
        # see https://github.com/pypa/pip/issues/7678 for discussion about --upgrade
        subprocess.check_call(
            [python, "-m", "pip", "install", "--upgrade", tmppath / wheel_name]
        )
        purelib_path = _get_purelib_path(python)
        odoo_addons_path = purelib_path / "odoo" / "addons"
        if not odoo_addons_path.exists():
            odoo_addons_path.mkdir(parents=True)
        addon_path = odoo_addons_path / addon_name
        addon_path.symlink_to(addon_dir)
        record_path = purelib_path / dist_info_dirname / "RECORD"
        with record_path.open("a") as f:
            f.write("odoo/addons/{},,\n".format(addon_name))
        # overwrite INSTALLER so it is not pip
        with _replace_metadata_file(purelib_path, dist_info_dirname, "INSTALLER") as f:
            f.write(INSTALLER)
        # overwrite direct_url.json so it is not the temporary wheel,
        # and it has the editable flag
        with _replace_metadata_file(
            purelib_path, dist_info_dirname, "direct_url.json"
        ) as f:
            json.dump(
                {"url": addon_dir.resolve().as_uri(), "dir_info": {"editable": True}}, f
            )


def install_editable(addon_dir: Path, python: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        wheel_name, dist_info_dirname, addon_name = _build_wheel(
            addon_dir,
            tmppath,
            include_src=False,
            include_pth=True,
            local_version_identifier="editable",
        )
        # see https://github.com/pypa/pip/issues/7678 for discussion about --upgrade
        subprocess.check_call(
            [python, "-m", "pip", "install", "--upgrade", tmppath / wheel_name]
        )
        purelib_path = _get_purelib_path(python)
        # overwrite INSTALLER so it is not pip
        with _replace_metadata_file(purelib_path, dist_info_dirname, "INSTALLER") as f:
            f.write(INSTALLER)
        # overwrite direct_url.json so it is not the temporary wheel,
        # and it has the editable flag
        with _replace_metadata_file(
            purelib_path, dist_info_dirname, "direct_url.json"
        ) as f:
            json.dump(
                {"url": addon_dir.resolve().as_uri(), "dir_info": {"editable": True}}, f
            )
