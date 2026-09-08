"""Optional real-Qt lifecycle check in an isolated aqt interpreter."""
import os
import subprocess
from pathlib import Path

import pytest


def test_standalone_editor_lifecycle():
    interpreter = os.environ.get("TSUNAGI_GUI_PYTHON")
    if not interpreter:
        pytest.skip("set TSUNAGI_GUI_PYTHON to an aqt/PyQt interpreter")
    script = Path(__file__).resolve().parents[1] / "tools" / "check_edit_dialog.py"
    result = subprocess.run([interpreter, str(script)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
