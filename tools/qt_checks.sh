#!/usr/bin/env bash
# Run the offscreen Qt tests and the real-Anki GUI checks with the current
# python, which needs aqt and its Qt dependencies. CI and the Anki watch use it.
set -euo pipefail
cd "$(dirname "$0")/.."
export QT_QPA_PLATFORM=offscreen
TSUNAGI_GUI_PYTHON="$(command -v python)" python -m pytest -q \
  tests/test_settings_dialog_qt.py tests/test_edit_dialog_lifecycle.py
for check in check_browser_startup check_browser check_add_cards check_edit_dialog \
  check_gui_media check_import_dispatch check_import_job check_reviewer check_settings_dialog; do
  echo "::group::$check"
  timeout 300 python "tools/$check.py"
  echo "::endgroup::"
done
