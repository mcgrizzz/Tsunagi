"""Exercise actual Qt settings controls and Anki addon metadata in a temp folder."""
import json
import os
import socket
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anki.lang import set_lang  # noqa: E402
from aqt.addons import AddonManager  # noqa: E402
from aqt.qt import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,  # noqa: E402
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
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
    for scenario in ("missing", "cancel", "save", "restore", "restore_history", "preferred", "invalid", "save_error"):
        check_scenario(app, scenario)


def check_scenario(app, scenario):
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        cfg = {**DEFAULTS, "api_key": "existing-key", "port": 7777,
               "cors_allowlist": ["http://existing"]}
        if scenario == "restore_history":
            cfg["ankiconnect_imported_at"] = "2026-09-01T12:34:00+00:00"
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
                tabs = window.findChild(QTabWidget, "settingsTabs")
                assert [tabs.tabText(i) for i in range(tabs.count())] == ["Connection", "Access", "Advanced"]
                mode = window.findChild(QComboBox, "portMode")
                stack = window.findChild(QStackedWidget, "portControls")
                fixed = window.findChild(QSpinBox, "port")
                preferred = window.findChild(QSpinBox, "prefer_port")
                assert mode.currentIndex() == stack.currentIndex() == 1
                assert fixed.value() == 7777
                mode.setCurrentIndex(0)
                assert stack.currentIndex() == 0 and not fixed.isVisible() and preferred.isVisible()
                preferred.setValue(8888)
                mode.setCurrentIndex(1)
                assert fixed.value() == 7777 and preferred.value() == 8888
                tabs.setCurrentIndex(1)
                key = window.findChild(QLineEdit, "api_key")
                assert key.echoMode() == QLineEdit.EchoMode.Password
                reveal = window.findChild(QCheckBox, "showApiKey")
                reveal.click()
                assert key.echoMode() == QLineEdit.EchoMode.Normal
                reveal.click()
                app.processEvents()
                key.setFocus()
                key.focusNextChild()
                assert reveal.hasFocus()
                tabs.setCurrentIndex(0)
                if scenario == "save" and os.environ.get("TSUNAGI_SETTINGS_SCREENSHOT"):
                    target = Path(os.environ["TSUNAGI_SETTINGS_SCREENSHOT"])
                    window.resize(640, 580)
                    for index, name in enumerate(("connection", "access", "advanced")):
                        tabs.setCurrentIndex(index)
                        app.processEvents()
                        window.grab().save(str(target.with_stem(target.stem + "-" + name)))
                    window.resize(480, 420)
                    tabs.setCurrentIndex(1)
                    app.processEvents()
                    window.grab().save(str(target.with_stem(target.stem + "-small")))
                    window.resize(640, 580)
                    tabs.setCurrentIndex(0)
                history = window.findChild(QLabel, "ankiconnectImportHistory")
                if scenario == "restore_history":
                    assert "Last imported from AnkiConnect:" in history.text()
                else:
                    assert history.text() == "No settings import recorded."
                original_history = history.text()
                status = window.findChild(QLabel, "ankiconnectStatus")
                button = window.findChild(QPushButton, "ankiconnectImport")
                buttons = window.findChild(QDialogButtonBox)
                if scenario == "save_error":
                    with patch.object(dialog, "save_settings", side_effect=RuntimeError("Port unavailable")):
                        buttons.button(QDialogButtonBox.StandardButton.Save).click()
                    assert window.isVisible() and writes == []
                    assert warnings == ["Could not save settings: Port unavailable"]
                    assert manager.addon_meta(ANKICONNECT_ID).enabled
                    warnings.clear()
                    window.reject()
                    return
                if scenario == "preferred":
                    mode.setCurrentIndex(0)
                    buttons.button(QDialogButtonBox.StandardButton.Save).click()
                    return
                if scenario == "invalid":
                    window.findChild(QLineEdit, "host").clear()
                    buttons.button(QDialogButtonBox.StandardButton.Save).click()
                    assert window.isVisible() and writes == []
                    assert warnings == ["Host must not be empty."]
                    warnings.clear()
                    window.reject()
                    return
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
                    assert history.text() == original_history
                    assert mode.currentIndex() == stack.currentIndex() == 1
                    assert fixed.value() == preferred.value() == server.port
                    assert "1 new website origin(s)" in status.text()
                    assert manager.addon_meta(ANKICONNECT_ID).enabled
                    assert server.sock is not None and timer.isActive()
                    assert writes == []
                    if scenario in ("restore", "restore_history"):
                        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).click()
                        assert "pending" not in status.text()
                        assert mode.currentIndex() == (1 if DEFAULTS["port"] else 0)
                        assert preferred.value() == DEFAULTS["prefer_port"]
                role = (QDialogButtonBox.StandardButton.Save if scenario in ("save", "restore", "restore_history")
                        else QDialogButtonBox.StandardButton.Cancel)
                buttons.button(role).click()
            except Exception as exc:
                traceback.print_exc()
                failures.append(exc)
                window.reject()

        with patch.dict(sys.modules, loaded_modules), \
             patch.object(dialog, "apply_config", apply), \
             patch.object(dialog, "_restart_server"), \
             patch("aqt.utils.restoreGeom"), patch("aqt.utils.saveGeom"), \
             patch("aqt.utils.showWarning", lambda message, **kwargs: warnings.append(message)):
            QTimer.singleShot(0, exercise)
            dialog.open_settings(mw)
            if scenario == "save" and not failures:
                def inspect_saved_import():
                    window = next(w for w in app.topLevelWidgets()
                                  if isinstance(w, QDialog) and w.isVisible()
                                  and w.windowTitle() == "Tsunagi Settings")
                    try:
                        history = window.findChild(QLabel, "ankiconnectImportHistory")
                        assert "Last imported from AnkiConnect:" in history.text()
                        button = window.findChild(QPushButton, "ankiconnectImport")
                        assert button.text() == "Import settings again"
                        status = window.findChild(QLabel, "ankiconnectStatus").text()
                        assert status in ("Installed and disabled", "Not installed")
                        assert button.isEnabled() == (status != "Not installed")
                        if status == "Installed and disabled" and os.environ.get("TSUNAGI_SETTINGS_SCREENSHOT"):
                            target = Path(os.environ["TSUNAGI_SETTINGS_SCREENSHOT"])
                            window.grab().save(str(target.with_stem(target.stem + "-imported")))
                    except Exception as exc:
                        traceback.print_exc()
                        failures.append(exc)
                    finally:
                        window.reject()

                QTimer.singleShot(0, inspect_saved_import)
                dialog.open_settings(mw)
                with patch.object(manager, "allAddons", return_value=[ADDON_PACKAGE]):
                    QTimer.singleShot(0, inspect_saved_import)
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
            assert persisted["ankiconnect_imported_at"]
        elif scenario == "preferred":
            persisted = manager.getConfig(ADDON_PACKAGE)
            assert persisted["port"] == 0 and persisted["prefer_port"] == 8888
            assert persisted["api_key"] == "existing-key"
            assert manager.addon_meta(ANKICONNECT_ID).enabled
        elif scenario in ("restore", "restore_history"):
            assert manager.addon_meta(ANKICONNECT_ID).enabled
            assert manager.getConfig(ADDON_PACKAGE)["ankiconnect_imported_at"] == cfg["ankiconnect_imported_at"]
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
