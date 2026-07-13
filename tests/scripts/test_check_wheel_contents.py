from __future__ import annotations

import importlib
import sys
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
wheel_check = importlib.import_module("check_wheel_contents")


def test_wheel_inspector_accepts_required_runtime_assets(tmp_path):
    wheel = tmp_path / "sample.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for suffix in wheel_check.REQUIRED_SUFFIXES:
            archive.writestr(f"src/{suffix}", "placeholder")
    assert wheel_check.inspect_wheel(wheel) == []


def test_wheel_inspector_reports_missing_asset(tmp_path):
    wheel = tmp_path / "sample.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("src/claudescientist/cli.py", "placeholder")
    assert "cockpit/theme/cockpit.tcss" in wheel_check.inspect_wheel(wheel)
