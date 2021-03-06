from pathlib import Path

from wodoo.buildapi import _build_wheel

DATA_PATH = Path(__file__).parent / "data"


def test_build_wheel(tmp_path):
    wheel_name, distinfo_dir_name, addon_name = _build_wheel(
        DATA_PATH / "addon_1", tmp_path
    )
    assert addon_name == "addon_1"
    assert wheel_name == "odoo12_addon_addon_1-12.0.1.0.0-py3-none-any.whl"
    assert (tmp_path / wheel_name).exists()
