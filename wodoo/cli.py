import argparse
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .buildapi import _build_sdist, _build_wheel
from .init import init
from .install import install, install_editable, install_symlink


def main() -> None:
    ap = argparse.ArgumentParser(
        description="The Wodoo CLI is a set of useful commands to work "
        "with pep 517 compliant Odoo addons. It's most useful "
        "use case as of fall 2019 is 'wodoo install --symlink'."
    )
    ap.add_argument("-V", "--version", action="version", version="Wodoo " + __version__)
    ap.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Verbosity level (default: warn, once: info, twice: debug).",
    )
    ap.add_argument(
        "--addon-dir",
        default=".",
        help="The addon directory, where __manifest__.py and pyproject.toml are "
        "(default: current directory).",
    )
    # TODO --addons-dir
    subparsers = ap.add_subparsers(title="subcommands", dest="subcmd")
    subparsers.add_parser(
        "init",
        help="Initialize pyproject.toml in addon_dir with the wodoo build-system.",
    )
    # TODO init --git-commit, --git-add
    parser_install = subparsers.add_parser(
        "install",
        help="Install the addon. "
        "--symlink is mostly a workaround for pip install "
        "--editable not being compatible with pep517 yet. When "
        "--symlink is not used, this command builds the wheel "
        "and installs it with pip. For more advanced use cases, "
        "please use pep517.build and pip.",
    )
    parser_install.add_argument(
        "-s",
        "--symlink",
        action="store_true",
        help="Symlink the addon into site packages instead of copying it.",
    )
    parser_install.add_argument(
        "-e",
        "--editable",
        action="store_true",
        help="Install the addon in editable mode.",
    )
    parser_install.add_argument(
        "--python",
        help="Target Python executable. If not set, use the python of the "
        "active current virtualenv, or else the python running wodoo.",
    )
    parser_build = subparsers.add_parser(
        "build",
        help="Build the addon. A trivial alternative to 'python -m pep517.build'.",
    )
    parser_build.add_argument(
        "--binary",
        "-b",
        action="store_true",
        help="Build wheel. Default unless -s is set.",
    )
    parser_build.add_argument(
        "--source",
        "-s",
        action="store_true",
        help="Build sdist. Default unless -b is set.",
    )
    parser_build.add_argument(
        "--out-dir", "-o", required=True, help="Destination in which to save the build."
    )

    args = ap.parse_args(sys.argv[1:])

    if args.verbose >= 2:
        log_level = logging.DEBUG
    elif args.verbose >= 1:
        log_level = logging.INFO
    else:
        log_level = logging.WARN
    logging.basicConfig(level=log_level)

    addon_dir = os.path.realpath(args.addon_dir)

    if args.subcmd == "init":
        init(Path(addon_dir))
    elif args.subcmd == "install":
        python = args.python
        if not python:
            venv = os.environ.get("VIRTUAL_ENV")
            if venv:
                python = os.path.join(venv, "bin", "python")
            else:
                python = sys.executable
        if args.symlink:
            install_symlink(Path(addon_dir), python)
        elif args.editable:
            install_editable(Path(addon_dir), python)
        else:
            install(Path(addon_dir), python)
    elif args.subcmd == "build":
        if args.binary or not args.source:
            _build_wheel(Path(addon_dir), Path(args.out_dir))
        if args.source or not args.binary:
            _build_sdist(Path(addon_dir), Path(args.out_dir))
    else:
        ap.print_help()
        sys.exit(1)
