"""
The settings dialog: a Qt front-end for the addon config, replacing Anki's
raw JSON editor (registered via addonManager.setConfigAction in the root
__init__.py).

Split in two, dialogs.py-style: everything decidable is pure dict-in/dict-out
logic at module level (tested headless), and the Qt shell is one function with
function-local aqt imports so this module imports without Qt.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, NamedTuple, Tuple

from .config import ADDON_PACKAGE, DEFAULTS, _migrate
from .settings import apply_config

MIB = 1024 * 1024


class Field(NamedTuple):
    key: str
    section: str
    kind: str  # "bool" | "text" | "int" | "mib" | "choice" | "cors_list"
    label: str
    # Only read at server startup; saving such a change makes the dialog
    # restart the embedded server so it still applies immediately.
    restart: bool = False
    tooltip: str = ""
    minimum: int = 0
    maximum: int = 0
    choices: Tuple[str, ...] = ()


# The form, in display order. Keys not listed here (gates aside, which render
# as their own section) never appear in the dialog and pass through saves
# untouched: import history, config_version, dev_watch_seconds.
FIELDS: Tuple[Field, ...] = (
    Field("enabled", "Connection", "bool", "Enable Tsunagi server", restart=True,
          tooltip="When off, the API server does not start with Anki."),
    Field("host", "Connection", "text", "Host", restart=True,
          tooltip="Bind address. 127.0.0.1 keeps the API local-only."),
    Field("port", "Connection", "int", "Port", restart=True, minimum=0, maximum=65535,
          tooltip="Fixed port to listen on. 0 uses the preferred port below."),
    Field("prefer_port", "Connection", "int", "Preferred port", restart=True,
          minimum=1, maximum=65535,
          tooltip="Used when Port is 0. Startup fails loudly if it is busy."),
    Field("api_key", "Access", "text", "API key",
          tooltip="Clients must send this key when set. Applies immediately."),
    Field("cors_allowlist", "Access", "cors_list", "Allowed website origins",
          tooltip="Browser origins allowed to call the API. \"*\" allows all; "
                  "\"http://localhost\" also covers 127.0.0.1 and browser "
                  "extensions. Applies immediately."),
    Field("log_level", "Advanced", "choice", "Log level", restart=True,
          choices=("critical", "error", "warning", "info", "debug")),
    Field("op_timeout_seconds", "Advanced", "int", "Operation timeout (seconds)",
          restart=True, minimum=1, maximum=600,
          tooltip="How long a request may wait on Anki's collection."),
    Field("media_max_bytes", "Advanced", "mib", "Max upload size",
          minimum=1, maximum=4096,
          tooltip="Largest media file the API accepts. Applies immediately."),
    Field("media_fetch_timeout_seconds", "Advanced", "int", "Download timeout (seconds)",
          minimum=1, maximum=600,
          tooltip="Timeout when fetching media from a URL. Applies immediately."),
)

RESTART_KEYS = frozenset(f.key for f in FIELDS if f.restart)

# Labels/tooltips for known gates. Unknown keys (a newer config seen by older
# code) still render, using the raw key as label. Long-form docs live in
# config.md; a test keeps the two in lockstep.
GATE_INFO: Dict[str, Tuple[str, str]] = {
    "media_allow_local_path": (
        "Allow local file paths in media actions",
        "Lets API clients read files from this computer by path. "
        "Leave off unless a tool you trust needs it.",
    ),
    "cards_set_memory_state": (
        "Allow rewriting FSRS memory state",
        "Lets API clients overwrite cards' FSRS memory state and desired "
        "retention. Leave off unless a tool you trust needs it.",
    ),
}
_UNKNOWN_GATE_TOOLTIP = "Opt-in switch - see the add-on documentation."


def _parse_cors(text: str) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        origin = line.strip()
        if origin and origin not in out:
            out.append(origin)
    return out


def form_values_from_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Widget-ready values for every field, plus a "gates" sub-dict."""
    values: Dict[str, Any] = {}
    for f in FIELDS:
        raw = cfg.get(f.key, DEFAULTS[f.key])
        if f.kind == "bool":
            values[f.key] = bool(raw)
        elif f.kind in ("int",):
            values[f.key] = int(raw)
        elif f.kind == "mib":
            values[f.key] = max(1, round(int(raw) / MIB))
        elif f.kind == "cors_list":
            values[f.key] = "\n".join(raw or [])
        else:  # "text" | "choice"
            values[f.key] = str(raw)
    values["gates"] = {k: bool(v) for k, v in (cfg.get("gates") or {}).items()}
    return values


def config_from_form(cfg: Dict[str, Any], values: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    Apply form values on top of `cfg`. A key is overwritten only when its form
    value differs from what the form would show for `cfg` - untouched fields
    (including a media_max_bytes that isn't a whole MiB) survive byte-for-byte,
    and hidden keys pass through because they were never in the form.
    Returns (new_cfg, restart_needed).
    """
    baseline = form_values_from_config(cfg)
    new_cfg = dict(cfg)
    restart = False
    for f in FIELDS:
        if values[f.key] == baseline[f.key]:
            continue
        if f.kind == "mib":
            parsed: Any = int(values[f.key]) * MIB
        elif f.kind == "cors_list":
            parsed = _parse_cors(values[f.key])
            if parsed == list(cfg.get(f.key) or []):
                continue  # whitespace-only edit
        elif f.kind == "text":
            parsed = str(values[f.key]).strip()
            if parsed == str(cfg.get(f.key, "")):
                continue  # whitespace-only edit
        else:
            parsed = values[f.key]
        new_cfg[f.key] = parsed
        restart = restart or f.restart
    if values.get("gates", {}) != baseline["gates"]:
        # Always a fresh dict: the settings singleton's gates can alias
        # DEFAULTS["gates"] before the first configure().
        new_cfg["gates"] = {k: bool(v) for k, v in values["gates"].items()}
    return new_cfg, restart


def validate_values(values: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not str(values.get("host", "")).strip():
        errors.append("Host must not be empty.")
    for f in FIELDS:
        if f.kind in ("int", "mib") and f.maximum > 0:
            v = values.get(f.key)
            if not isinstance(v, int) or not (f.minimum <= v <= f.maximum):
                errors.append(f"{f.label} must be between {f.minimum} and {f.maximum}.")
    return errors


def gate_rows(cfg: Dict[str, Any]) -> List[Tuple[str, str, str, bool]]:
    """(key, label, tooltip, enabled) per gate - unknown gates included."""
    rows = []
    for key, value in sorted((cfg.get("gates") or {}).items()):
        label, tooltip = GATE_INFO.get(key, (key, _UNKNOWN_GATE_TOOLTIP))
        rows.append((key, label, tooltip, bool(value)))
    return rows


# ====================
# Qt shell (main thread; invoked from the Config button / Tools menu)
# ====================

_GEOM_KEY = "tsunagiSettings"


def _restart_server(mw: Any, *, enabled: bool) -> None:
    """
    Apply server-level keys live: stop uvicorn and start it again on the
    just-saved config (start_server re-reads everything, including log_level
    and op_timeout_seconds). The one case that still needs an Anki restart is
    a server thread that won't die - its port may still be held.
    """
    from aqt.utils import showWarning, tooltip

    from ..app import server_url, start_server, stop_server

    if not stop_server():
        showWarning("The previous Tsunagi server thread is still shutting "
                    "down, so its port may still be held. Restart Anki to "
                    "apply the server settings.")
        return
    start_server(mw)  # no-op (with a log line) when enabled is off
    url = server_url()
    if url:
        tooltip(f"Tsunagi server restarted on {url}")
    elif not enabled:
        tooltip("Tsunagi server stopped")
    else:
        # start_server caught the failure and will show its own delayed
        # tooltip with the reason; give immediate feedback too.
        showWarning("The Tsunagi server did not restart - see the console "
                    "for details.")


def _check_handover_port(cfg: Dict[str, Any]) -> None:
    from .config import _bindable

    if not cfg.get("enabled", True):
        return
    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port") or cfg.get("prefer_port") or 7777)
    if _bindable(host, port):
        return
    from ..app import server_url

    if server_url() == f"http://{host}:{port}":
        return  # Tsunagi itself already owns the selected address.
    raise ValueError(f"Port {port} is still in use. The AnkiConnect handover was cancelled.")


def save_settings(mw: Any, new_cfg: Dict[str, Any], *, disable_ankiconnect: bool = False) -> None:
    """Disable/stop AnkiConnect before committing settings for the port handover."""
    from .dialogs import (
        ANKICONNECT_ID,
        ankiconnect_import_record,
        ankiconnect_status,
        stop_ankiconnect_server,
    )

    if not disable_ankiconnect:
        apply_config(mw, new_cfg, write=True)
        return
    status = ankiconnect_status(mw.addonManager)
    if not status["installed"]:
        raise ValueError("AnkiConnect is no longer installed. Reopen settings and try again.")
    previous = dict(mw.addonManager.getConfig(ADDON_PACKAGE) or {})
    restore_server = None
    saving = False
    try:
        if status["enabled"]:
            mw.addonManager.toggleEnabled(ANKICONNECT_ID, enable=False)
        restore_server = stop_ankiconnect_server()
        _check_handover_port(new_cfg)
        new_cfg = {**new_cfg, **ankiconnect_import_record()}
        saving = True
        apply_config(mw, new_cfg, write=True)
    except Exception:
        try:
            if saving:
                apply_config(mw, previous, write=True)
        finally:
            try:
                if status["enabled"]:
                    mw.addonManager.toggleEnabled(ANKICONNECT_ID, enable=True)
            finally:
                if restore_server is not None:
                    restore_server()
        raise


def import_history_text(cfg: Dict[str, Any]) -> str:
    recorded = cfg.get("ankiconnect_imported_at")
    if recorded:
        try:
            local = datetime.fromisoformat(recorded).astimezone()
            return f"Last imported from AnkiConnect: {local:%Y-%m-%d %H:%M}."
        except (TypeError, ValueError, OverflowError):
            return "Import history is unavailable."
    if cfg.get("ankiconnect_import_offered"):
        return "No saved import record. Earlier versions did not record imports."
    return "No settings import recorded."


def open_settings(mw: Any) -> None:
    from aqt.qt import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QStackedWidget,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
    from aqt.utils import (
        disable_help_button,
        restoreGeom,
        saveGeom,
        showWarning,
    )

    from .dialogs import ANKICONNECT_ID, ankiconnect_import_changes, ankiconnect_status

    # Persisted truth, not the live singleton: server-level keys the running
    # server hasn't picked up yet must display as saved.
    cfg, _ = _migrate(dict(mw.addonManager.getConfig(ADDON_PACKAGE) or {}))

    dlg = QDialog(mw)
    dlg.setWindowTitle("Tsunagi Settings")
    disable_help_button(dlg)
    layout = QVBoxLayout(dlg)
    tabs = QTabWidget()
    tabs.setObjectName("settingsTabs")
    layout.addWidget(tabs)
    pages = {}
    for title in ("Connection", "Access", "Advanced"):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        tabs.addTab(scroll, title)
        pages[title] = page_layout

    def guidance(text):
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    # One (setter, getter) pair per field key; gates keyed separately.
    field_widgets: Dict[str, Tuple[Any, Any]] = {}
    gate_widgets: Dict[str, Any] = {}

    def make_widget(f: Field) -> Tuple[Any, Any, Any]:
        if f.kind == "bool":
            w = QCheckBox()
            return w, w.setChecked, w.isChecked
        if f.kind in ("int", "mib"):
            w = QSpinBox()
            w.setRange(f.minimum, f.maximum)
            if f.kind == "mib":
                w.setSuffix(" MiB")
            return w, w.setValue, w.value
        if f.kind == "choice":
            w = QComboBox()
            w.addItems(list(f.choices))
            return w, w.setCurrentText, w.currentText
        if f.kind == "cors_list":
            w = QPlainTextEdit()
            w.setMinimumHeight(w.fontMetrics().lineSpacing() * 5 + 12)
            return w, w.setPlainText, w.toPlainText
        w = QLineEdit()
        if f.key == "api_key":
            w.setPlaceholderText("No API key required")
            w.setEchoMode(QLineEdit.EchoMode.Password)
        return w, w.setText, w.text

    sections: Dict[str, Any] = {}
    port_mode = QComboBox()
    port_mode.setObjectName("portMode")
    port_mode.addItems(["Use preferred port", "Use a fixed port"])
    port_stack = QStackedWidget()
    port_stack.setObjectName("portControls")
    fixed_port = QSpinBox()
    fixed_port.setObjectName("port")
    fixed_port.setRange(1, 65535)
    preferred_port = QSpinBox()
    preferred_port.setObjectName("prefer_port")
    preferred_port.setRange(1, 65535)
    port_stack.addWidget(preferred_port)
    port_stack.addWidget(fixed_port)
    port_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    port_label = QLabel("Preferred port")

    def update_port_mode(index):
        port_stack.setCurrentIndex(index)
        port_label.setText("Port" if index else "Preferred port")
        port_label.setBuddy(fixed_port if index else preferred_port)

    port_mode.currentIndexChanged.connect(update_port_mode)
    update_port_mode(0)

    def set_port(value):
        fixed_port.setValue(value or DEFAULTS["prefer_port"])
        port_mode.setCurrentIndex(1 if value else 0)

    field_widgets["port"] = (set_port, lambda: fixed_port.value() if port_mode.currentIndex() else 0)
    field_widgets["prefer_port"] = (preferred_port.setValue, preferred_port.value)
    for f in FIELDS:
        if f.section not in sections:
            form = QFormLayout()
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            sections[f.section] = form
            pages[f.section].addLayout(form)
        form = sections[f.section]
        if f.key == "port":
            form.addRow("Port selection", port_mode)
            form.addRow(port_label, port_stack)
            form.addRow(guidance("The selected port must be free. Tsunagi does not choose another port if it is busy."))
            continue
        if f.key == "prefer_port":
            continue
        widget, setter, getter = make_widget(f)
        widget.setObjectName(f.key)
        widget.setToolTip(f.tooltip)
        field_widgets[f.key] = (setter, getter)
        if f.key == "api_key":
            row = QWidget()
            key_layout = QHBoxLayout(row)
            key_layout.setContentsMargins(0, 0, 0, 0)
            key_layout.addWidget(widget)
            reveal = QCheckBox("Show")
            reveal.setObjectName("showApiKey")
            reveal.toggled.connect(lambda checked, edit=widget: edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
            key_layout.addWidget(reveal)
            form.addRow(f.label, row)
            form.addRow(guidance("Leave empty to allow requests without an API key."))
        elif f.kind == "bool":
            widget.setText(f.label)
            form.addRow(widget)
        else:
            form.addRow(f.label, widget)
        if f.key == "host":
            form.addRow(guidance("127.0.0.1 accepts connections from this computer only."))
        elif f.key == "cors_allowlist":
            form.addRow(guidance("One origin per line, including http:// or https://. Use * to allow all origins."))

    gates_box = QGroupBox("Optional permissions")
    gates_layout = QVBoxLayout(gates_box)
    for key, label, tooltip, enabled in gate_rows(cfg):
        w = QCheckBox(label)
        w.setToolTip(tooltip)
        w.setChecked(enabled)
        gates_layout.addWidget(w)
        gates_layout.addWidget(guidance(tooltip))
        gate_widgets[key] = w
    pages["Access"].addWidget(gates_box)

    def populate(values: Dict[str, Any]) -> None:
        for key, (setter, _getter) in field_widgets.items():
            setter(values[key])
        for key, w in gate_widgets.items():
            w.setChecked(bool(values.get("gates", {}).get(key, False)))

    def collect() -> Dict[str, Any]:
        values = {key: getter() for key, (_setter, getter) in field_widgets.items()}
        values["gates"] = {key: w.isChecked() for key, w in gate_widgets.items()}
        return values

    populate(form_values_from_config(cfg))

    ac_box = QGroupBox("AnkiConnect")
    ac_layout = QVBoxLayout(ac_box)
    ac_status = QLabel()
    ac_status.setObjectName("ankiconnectStatus")
    ac_status.setWordWrap(True)
    ac_layout.addWidget(ac_status)
    ac_history = guidance(import_history_text(cfg))
    ac_history.setObjectName("ankiconnectImportHistory")
    ac_layout.addWidget(ac_history)
    ac_details = QLabel(
        "Import its API key and port, and add its website origins to your list. Save disables "
        "AnkiConnect and stops its server before enabling Tsunagi on that port."
    )
    ac_details.setWordWrap(True)
    ac_layout.addWidget(ac_details)
    import_button = QPushButton(
        "Import settings again" if cfg.get("ankiconnect_imported_at") else "Import AnkiConnect settings"
    )
    import_button.setObjectName("ankiconnectImport")
    ac_layout.addWidget(import_button)
    pages["Connection"].addWidget(ac_box)
    pending_import = False
    import_summary = ""

    def refresh_ankiconnect() -> None:
        status = ankiconnect_status(mw.addonManager)
        if not status["installed"]:
            text = "Not installed"
        elif status["enabled"]:
            text = "Installed and enabled"
        else:
            text = "Installed and disabled"
        if status["installed"] and not status["config_available"]:
            text += ". Import settings are unavailable."
        if pending_import:
            text += ". Changes pending. " + import_summary + " Save applies these settings and disables AnkiConnect."
        ac_status.setText(text)
        import_button.setEnabled(status["config_available"] and not pending_import)

    def on_import() -> None:
        nonlocal pending_import, import_summary
        ac = mw.addonManager.getConfig(ANKICONNECT_ID)
        if ac is None:
            refresh_ankiconnect()
            return
        current, _ = config_from_form(cfg, collect())
        old_origins = set(current.get("cors_allowlist") or [])
        try:
            current.update(ankiconnect_import_changes(current, ac, include_port=True))
        except ValueError as exc:
            showWarning(str(exc), parent=dlg)
            return
        populate(form_values_from_config(current))
        pending_import = True
        added = len(set(current.get("cors_allowlist") or []) - old_origins)
        import_summary = f"Port {current['port']}, API key settings, and {added} new website origin(s) ready to import."
        refresh_ankiconnect()

    import_button.clicked.connect(on_import)
    refresh_ankiconnect()

    for page_layout in pages.values():
        page_layout.addStretch()
    layout.addWidget(guidance("Save applies all tabs and restarts the API server when needed."))
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save
        | QDialogButtonBox.StandardButton.Cancel
        | QDialogButtonBox.StandardButton.RestoreDefaults
    )
    layout.addWidget(buttons)

    def on_ok() -> None:
        values = collect()
        errors = validate_values(values)
        if errors:
            showWarning("\n".join(errors), parent=dlg)
            return  # keep the dialog open
        new_cfg, server_restart = config_from_form(cfg, values)
        try:
            save_settings(mw, new_cfg, disable_ankiconnect=pending_import)
        except Exception as exc:
            showWarning(f"Could not save settings: {exc}", parent=dlg)
            return
        dlg.accept()  # close before the restart's thread-join can block
        if server_restart or pending_import:
            _restart_server(mw, enabled=bool(new_cfg.get("enabled", True)))

    buttons.accepted.connect(on_ok)
    buttons.rejected.connect(dlg.reject)
    restore_btn = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
    restore_btn.setText("Restore all defaults")
    restore_btn.setToolTip("Reset every tab and cancel the pending import. Nothing changes until Save.")
    # Repopulates the form only - nothing persists until Save (matches Anki's
    # own config editor). Gates absent from DEFAULTS reset to off.
    def restore_defaults() -> None:
        nonlocal pending_import
        pending_import = False
        populate(form_values_from_config(DEFAULTS))
        refresh_ankiconnect()

    restore_btn.clicked.connect(restore_defaults)

    dlg.resize(640, 580)
    restoreGeom(dlg, _GEOM_KEY)
    dlg.finished.connect(lambda _result: saveGeom(dlg, _GEOM_KEY))
    dlg.exec()
