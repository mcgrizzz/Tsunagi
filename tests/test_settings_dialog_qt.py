"""Optional real Qt check using an interpreter with aqt and PyQt installed."""
import os
import subprocess
from pathlib import Path

import pytest


def test_settings_dialog_controls_and_addon_metadata():
    interpreter = os.environ.get("TSUNAGI_GUI_PYTHON")
    if not interpreter:
        pytest.skip("Set TSUNAGI_GUI_PYTHON to an interpreter with aqt/PyQt")
    result = subprocess.run(
        [interpreter, str(Path(__file__).resolve().parents[1] / "tools/check_settings_dialog.py")],
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
