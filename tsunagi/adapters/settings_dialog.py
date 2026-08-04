"""
The settings dialog: a Qt front-end for the addon config, replacing Anki's
raw JSON editor (registered via addonManager.setConfigAction in the root
__init__.py).

Split in two, dialogs.py-style: everything decidable is pure dict-in/dict-out
logic at module level (tested headless), and the Qt shell is one function with
function-local aqt imports so this module imports without Qt.
"""
from __future__ import annotations

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
# untouched: ankiconnect_import_offered, config_version, dev_watch_seconds.
FIELDS: Tuple[Field, ...] = (
    Field("enabled", "Server", "bool", "Enable Tsunagi server", restart=True,
          tooltip="When off, the API server does not start with Anki."),
    Field("host", "Server", "text", "Host", restart=True,
          tooltip="Bind address. 127.0.0.1 keeps the API local-only."),
    Field("port", "Server", "int", "Port", restart=True, minimum=0, maximum=65535,
          tooltip="Fixed port to listen on. 0 uses the preferred port below."),
    Field("prefer_port", "Server", "int", "Preferred port", restart=True,
          minimum=1, maximum=65535,
          tooltip="Used when Port is 0. Startup fails loudly if it is busy."),
    Field("api_key", "Server", "text", "API key",
          tooltip="Clients must send this key when set. Applies immediately."),
    Field("cors_allowlist", "Server", "cors_list", "Allowed origins (one per line)",
          tooltip="Browser origins allowed to call the API. \"*\" allows all; "
                  "\"http://localhost\" also covers 127.0.0.1 and browser "
                  "extensions. Applies immediately."),
    Field("log_level", "Server", "choice", "Log level", restart=True,
          choices=("critical", "error", "warning", "info", "debug")),
    Field("op_timeout_seconds", "Server", "int", "Operation timeout (seconds)",
          restart=True, minimum=1, maximum=600,
          tooltip="How long a request may wait on Anki's collection."),
    Field("media_max_bytes", "Media", "mib", "Max upload size",
          minimum=1, maximum=4096,
          tooltip="Largest media file the API accepts. Applies immediately."),
    Field("media_fetch_timeout_seconds", "Media", "int", "Download timeout (seconds)",
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


def open_settings(mw: Any) -> None:
    from aqt.qt import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QGroupBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QSpinBox,
        QVBoxLayout,
    )
    from aqt.utils import (
        disable_help_button,
        restoreGeom,
        saveGeom,
        showWarning,
    )

    # Persisted truth, not the live singleton: server-level keys the running
    # server hasn't picked up yet must display as saved.
    cfg, _ = _migrate(dict(mw.addonManager.getConfig(ADDON_PACKAGE) or {}))

    dlg = QDialog(mw)
    dlg.setWindowTitle("Tsunagi Settings")
    disable_help_button(dlg)
    layout = QVBoxLayout(dlg)

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
            if f.key == "port":
                w.setSpecialValueText("use preferred port")
            return w, w.setValue, w.value
        if f.kind == "choice":
            w = QComboBox()
            w.addItems(list(f.choices))
            return w, w.setCurrentText, w.currentText
        if f.kind == "cors_list":
            w = QPlainTextEdit()
            w.setFixedHeight(w.fontMetrics().lineSpacing() * 4 + 12)
            return w, w.setPlainText, w.toPlainText
        w = QLineEdit()
        if f.key == "api_key":
            w.setPlaceholderText("empty = authentication off")
        return w, w.setText, w.text

    sections: Dict[str, Any] = {}
    for f in FIELDS:
        if f.section not in sections:
            box = QGroupBox(f.section)
            box.setLayout(QFormLayout())
            sections[f.section] = box
            layout.addWidget(box)
        widget, setter, getter = make_widget(f)
        if f.tooltip:
            widget.setToolTip(f.tooltip)
        label = f.label + (" *" if f.restart else "")
        sections[f.section].layout().addRow(label, widget)
        field_widgets[f.key] = (setter, getter)

    note = QLabel("* saving restarts the API server to apply these")
    layout.addWidget(note)

    gates_box = QGroupBox("Optional capabilities (off by default)")
    gates_box.setLayout(QFormLayout())
    for key, label, tooltip, enabled in gate_rows(cfg):
        w = QCheckBox(label)
        w.setToolTip(tooltip)
        w.setChecked(enabled)
        gates_box.layout().addRow(w)
        gate_widgets[key] = w
    layout.addWidget(gates_box)

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

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok
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
        apply_config(mw, new_cfg, write=True)
        dlg.accept()  # close before the restart's thread-join can block
        if server_restart:
            _restart_server(mw, enabled=bool(new_cfg.get("enabled", True)))

    buttons.accepted.connect(on_ok)
    buttons.rejected.connect(dlg.reject)
    restore_btn = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
    # Repopulates the form only - nothing persists until OK (matches Anki's
    # own config editor). Gates absent from DEFAULTS reset to off.
    restore_btn.clicked.connect(lambda: populate(form_values_from_config(DEFAULTS)))

    restoreGeom(dlg, _GEOM_KEY)
    dlg.finished.connect(lambda _result: saveGeom(dlg, _GEOM_KEY))
    dlg.exec()
