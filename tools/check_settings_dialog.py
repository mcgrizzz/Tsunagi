"""Exercise actual Qt settings controls and Anki addon metadata in a temp folder."""
import json
import os
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anki.lang import set_lang  # noqa: E402
from aqt.addons import AddonManager  # noqa: E402
from aqt.qt import (  # noqa: E402
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,  # noqa: E402
    QPushButton,
    QTimer,
    QWidget,
)

from tsunagi.adapters import settings_dialog as dialog  # noqa: E402
from tsunagi.adapters.config import ADDON_PACKAGE, DEFAULTS  # noqa: E402
from tsunagi.adapters.dialogs import ANKICONNECT_ID  # noqa: E402


class ProbeServer:
    """A disposable listener with the shutdown interface used by AnkiConnect."""
    def __init__(self):
        self.port = 0
        self.sock = None
        self.listen()

    def listen(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", self.port))
        self.port = self.sock.getsockname()[1]
        self.sock.listen()

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None


def main():
    set_lang("en")
    app = QApplication.instance() or QApplication([])
    for scenario in ("missing", "cancel", "save", "restore"):
        check_scenario(app, scenario)


def check_scenario(app, scenario):
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        cfg = {**DEFAULTS, "api_key": "existing-key", "port": 7777,
               "cors_allowlist": ["http://existing"]}
        server = ProbeServer() if scenario != "missing" else None
        timer = QTimer()
        timer.start(25)
        loaded_modules = ({ANKICONNECT_ID: SimpleNamespace(ac=SimpleNamespace(server=server, timer=timer))}
                          if server is not None else {})
        addon_configs = {ADDON_PACKAGE: cfg}
        if scenario != "missing":
            addon_configs[ANKICONNECT_ID] = {
                "apiKey": "imported-key", "webCorsOriginList": ["http://existing", "http://imported", "http://imported"],
                "webBindPort": server.port,
            }
        for name, config in addon_configs.items():
            folder = base / name
            folder.mkdir()
            (folder / "__init__.py").write_text("")
            (folder / "config.json").write_text(json.dumps(config))
        mw = QWidget()
        manager = AddonManager.__new__(AddonManager)
        manager.mw = mw
        manager.addonsFolder = lambda module=None: str(base / module if module else base)
        mw.addonManager = manager
        failures, warnings = [], []
        writes = []

        def apply(_mw, new_cfg, *, write):
            assert write
            writes.append(new_cfg)
            manager.writeConfig(ADDON_PACKAGE, new_cfg)

        def exercise():
            window = next(w for w in app.topLevelWidgets()
                          if isinstance(w, QDialog) and w.windowTitle() == "Tsunagi Settings")
            try:
                if scenario == "save" and os.environ.get("TSUNAGI_SETTINGS_SCREENSHOT"):
                    window.grab().save(os.environ["TSUNAGI_SETTINGS_SCREENSHOT"])
                status = window.findChild(QLabel, "ankiconnectStatus")
                button = window.findChild(QPushButton, "ankiconnectImport")
                buttons = window.findChild(QDialogButtonBox)
                if scenario == "missing":
                    assert status.text() == "Not installed"
                    assert not button.isEnabled()
                else:
                    assert status.text() == "Installed and enabled"
                    origins = window.findChild(QPlainTextEdit)
                    origins.setPlainText("http://existing\nhttp://unsaved")
                    button.click()
                    assert origins.toPlainText().splitlines() == [
                        "http://existing", "http://unsaved", "http://imported"]
                    assert "pending" in status.text()
                    assert manager.addon_meta(ANKICONNECT_ID).enabled
                    assert server.sock is not None and timer.isActive()
                    assert writes == []
                    if scenario == "restore":
                        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).click()
                        assert "pending" not in status.text()
                role = (QDialogButtonBox.StandardButton.Ok if scenario in ("save", "restore")
                        else QDialogButtonBox.StandardButton.Cancel)
                buttons.button(role).click()
            except Exception as exc:
                failures.append(exc)
                window.reject()

        with patch.dict(sys.modules, loaded_modules), \
             patch.object(dialog, "apply_config", apply), \
             patch.object(dialog, "_restart_server"), \
             patch("aqt.utils.restoreGeom"), patch("aqt.utils.saveGeom"), \
             patch("aqt.utils.showWarning", lambda message, **kwargs: warnings.append(message)):
            QTimer.singleShot(0, exercise)
            dialog.open_settings(mw)
        assert not failures, failures
        assert not warnings, warnings
        if scenario == "save":
            assert not manager.addon_meta(ANKICONNECT_ID).enabled
            persisted = manager.getConfig(ADDON_PACKAGE)
            assert persisted["api_key"] == "imported-key"
            assert persisted["cors_allowlist"] == ["http://existing", "http://unsaved", "http://imported"]
            assert persisted["port"] == persisted["prefer_port"] == server.port
            assert persisted["enabled"] is True
            assert server.sock is None and not timer.isActive()
            with socket.socket() as tsunagi_listener:
                tsunagi_listener.bind(("127.0.0.1", persisted["port"]))
                tsunagi_listener.listen()
            assert persisted["ankiconnect_import_offered"] is True
        elif scenario == "restore":
            assert manager.addon_meta(ANKICONNECT_ID).enabled
        else:
            assert writes == []
            assert manager.getConfig(ADDON_PACKAGE) == cfg
            if scenario == "cancel":
                assert manager.addon_meta(ANKICONNECT_ID).enabled
        if server is not None:
            if scenario != "save":
                assert server.sock is not None and timer.isActive()
            server.close()
        timer.stop()
        mw.deleteLater()
        app.processEvents()
        print(f"PASS: settings {scenario}")


if __name__ == "__main__":
    main()
