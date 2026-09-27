"""
The settings page: plain HTML/JS (tsunagi/web/settings.*) in an AnkiWebView
dialog, the way Anki shows its own deck options. The page talks to Python only
over Anki's pycmd bridge, never through Tsunagi's HTTP server, so no API
client, extension or card template can reach it (backlog 6.5a, 8.5b).

Module level is pure dict-in/dict-out logic, tested headless; the Qt shell
(open_settings) keeps its aqt imports local so this module imports without Qt.
"""
from __future__ import annotations

import json
import re
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..shared.permissions import BUILTIN_GROUPS, GRANTS, NO_ACCESS, PERMISSIONS
from ..shared.version import ADDON_VERSION
from .config import ADDON_PACKAGE, DEFAULTS, _migrate
from .settings_dialog import (
    FIELDS,
    config_from_form,
    form_values_from_config,
    gate_rows,
    generate_api_key,
    import_history_text,
    validate_values,
)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
_GEOM_KEY = "tsunagiSettings"
_PREFIX = "tsunagi:"

# What each permission means, in the group editor's words. Areas in display
# order; a test keeps this in step with shared/permissions.py.
AREAS: List[Tuple[str, str, str]] = [
    ("read", "Read", "See notes, cards, decks, note types, tags, review history and media."),
    ("write", "Change", "Add, edit and delete. Undo needs every kind of change."),
    ("gui", "Use Anki's windows", "Open the Browser, Add and Edit windows and the reviewer on this computer."),
    ("sync", "Sync", "Sync with AnkiWeb."),
    ("manage", "Manage the collection", "Import, export, check the database, switch profile and close Anki."),
    ("events", "Live updates", "What the event stream sends as it happens."),
    ("local_files", "Read files on this computer",
     "Media uploads that name a file on this computer. Anything with this can make "
     "Anki read any file your account can read."),
    ("memory_state", "Rewrite FSRS memory state",
     "Overwrite what FSRS knows about cards. A faulty tool could quietly damage your scheduling."),
]
NAMES: Dict[str, str] = {
    "notes": "Notes", "cards": "Cards", "decks": "Decks", "deck_configs": "Deck options",
    "models": "Note types", "tags": "Tags", "reviews": "Review history", "media": "Media",
    "collection": "Collection info, jobs and the event stream", "addons": "Installed add-ons",
    "changes": "Changes to your collection", "reviews_live": "Each card you answer",
}
_NAME_LABEL = {"events:reviews": NAMES["reviews_live"]}

NO_KEY_ROWS = [
    ("no_key_local_group", "Programs on this computer",
     "Requests without a key from this computer, such as Yomitan or a script."),
    ("no_key_remote_group", "Other devices",
     "Requests without a key from anywhere else, including through Tailscale or "
     "another proxy. Anyone who can reach the port gets this group."),
]


def permission_catalog() -> List[Dict[str, Any]]:
    out = []
    for area, label, description in AREAS:
        names = sorted(p for p in PERMISSIONS if p.startswith(area + ":"))
        labelled = [{"name": n, "label": _NAME_LABEL.get(n, NAMES[n.split(":", 1)[1]])} for n in names]
        out.append({"area": area, "label": label, "description": description,
                    "names": sorted(labelled, key=lambda n: n["label"])})
    return out


def _groups_for_page(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    custom = cfg.get("groups") or {}
    rows = []
    for gid, spec in {**BUILTIN_GROUPS, **custom}.items():
        if not isinstance(spec, dict):
            continue
        builtin = BUILTIN_GROUPS.get(gid)
        rows.append({"id": gid, "name": str(spec.get("name") or gid),
                     "grants": sorted(g for g in spec.get("grants") or [] if g in GRANTS),
                     "builtin": builtin is not None,
                     "default": ({"name": builtin["name"], "grants": sorted(builtin["grants"])}
                                 if builtin else None)})
    return rows


def page_state(cfg: Dict[str, Any], ankiconnect: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the page renders, for `cfg` (the saved config, or defaults)."""
    return {
        "version": ADDON_VERSION,
        "fields": [f._asdict() for f in FIELDS],
        "values": form_values_from_config(cfg),
        "gates": [{"key": k, "label": label, "tooltip": tip, "on": on}
                  for k, label, tip, on in gate_rows(cfg)],
        "apps": [{"name": str(a.get("name") or ""), "key": str(a.get("key") or ""),
                  "group": str(a.get("group") or NO_ACCESS)}
                 for a in cfg.get("apps") or [] if isinstance(a, dict)],
        "no_key_rows": [{"setting": k, "label": label, "help": help_text,
                         "group": str(cfg.get(k, DEFAULTS[k]))}
                        for k, label, help_text in NO_KEY_ROWS],
        "groups": _groups_for_page(cfg),
        "catalog": permission_catalog(),
        "ankiconnect": {**ankiconnect, "history": import_history_text(cfg),
                        "imported": bool(cfg.get("ankiconnect_imported_at"))},
    }


def _stored_groups(groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Only user-made groups and edited built-ins are saved."""
    out = {}
    for g in groups:
        spec = {"name": g["name"].strip(), "grants": sorted(set(g["grants"]))}
        builtin = BUILTIN_GROUPS.get(g["id"])
        if builtin and spec == {"name": builtin["name"], "grants": sorted(builtin["grants"])}:
            continue
        out[g["id"]] = spec
    return out


def validate_access(cfg: Dict[str, Any], draft: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    groups = draft["groups"]
    ids = [g["id"] for g in groups]
    if len(set(ids)) != len(ids):
        errors.append("Two groups have the same id.")
    for g in groups:
        if not re.fullmatch(r"[a-z0-9_]{1,40}", g["id"]):
            errors.append(f"Group id {g['id']!r} may only use a-z, 0-9 and _.")
        if not g["name"].strip():
            errors.append("Every group needs a name.")
        if not set(g["grants"]) <= GRANTS:
            errors.append(f"{g['name']}: unknown permission.")
        if g["id"] == NO_ACCESS and g["grants"]:
            errors.append("No access cannot grant anything.")
    for gid in BUILTIN_GROUPS:
        if gid not in ids:
            errors.append(f"The built-in group {BUILTIN_GROUPS[gid]['name']!r} cannot be deleted.")
    names = [a["name"].strip() for a in draft["apps"]]
    keys = [a["key"] for a in draft["apps"]]
    if any(not n for n in names):
        errors.append("Every app needs a name.")
    if len(set(names)) != len(names):
        errors.append("Two apps have the same name.")
    if any(not k for k in keys):
        errors.append("Every app needs a key; use New key.")
    if len(set(keys)) != len(keys):
        errors.append("Two apps have the same key.")
    used = [a["group"] for a in draft["apps"]] + [draft[k] for k, *_ in NO_KEY_ROWS]
    for gid in sorted(set(used) - set(ids)):
        errors.append(f"Group {gid!r} is in use but does not exist.")
    remote = draft["no_key_remote_group"]
    if (remote != NO_ACCESS and remote != cfg.get("no_key_remote_group", DEFAULTS["no_key_remote_group"])
            and not draft.get("confirm_remote")):
        errors.append("Confirm that other devices may connect without a key.")
    return errors


def config_from_page(cfg: Dict[str, Any], draft: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, List[str]]:
    """(new_cfg, restart_needed, errors) for the page's draft on top of `cfg`."""
    values = {**draft["values"], "gates": draft["gates"]}
    errors = validate_values(values) + validate_access(cfg, draft)
    if errors:
        return cfg, False, errors
    new_cfg, restart = config_from_form(cfg, values)
    new_cfg["apps"] = [{"name": a["name"].strip(), "key": a["key"], "group": a["group"]}
                       for a in draft["apps"]]
    for key, *_ in NO_KEY_ROWS:
        new_cfg[key] = draft[key]
    new_cfg["groups"] = _stored_groups(draft["groups"])
    return new_cfg, restart, []


def _page_html() -> str:
    def read(name: str) -> str:
        return (WEB_DIR / name).read_text(encoding="utf-8")
    # Inlined: nothing is served to other pages, and no web exports are needed.
    return (read("settings.html")
            .replace("/*STYLE*/", read("settings.css"))
            .replace("/*SCRIPT*/", read("settings.js")))


class SettingsBridge:
    """Handles the page's pycmd("tsunagi:{op, arg}") calls; returns JSON values."""

    def __init__(self, mw: Any, *, close: Callable[[bool], None],
                 copy: Callable[[str], None]) -> None:
        self.mw = mw
        self.close = close  # close(saved)
        self.copy = copy
        self.restart = False
        self.saved_cfg: Optional[Dict[str, Any]] = None

    def saved(self) -> Dict[str, Any]:
        # Persisted truth, not the live singleton: server-level keys the
        # running server hasn't picked up yet must display as saved.
        return _migrate(dict(self.mw.addonManager.getConfig(ADDON_PACKAGE) or {}))[0]

    def handle(self, cmd: str) -> Any:
        if not cmd.startswith(_PREFIX):
            return None
        try:
            msg = json.loads(cmd[len(_PREFIX):])
            return getattr(self, "op_" + msg["op"])(msg.get("arg"))
        except Exception as exc:
            print("[tsunagi] settings page:\n" + traceback.format_exc())
            return {"error": str(exc)}

    def _status(self) -> Dict[str, Any]:
        from .dialogs import ankiconnect_status
        return ankiconnect_status(self.mw.addonManager)

    def op_state(self, _arg: Any) -> Dict[str, Any]:
        return page_state(self.saved(), self._status())

    def op_defaults(self, _arg: Any) -> Dict[str, Any]:
        # Import history is bookkeeping, not a setting: keep it.
        cfg = self.saved()
        keep = {k: cfg.get(k) for k in ("ankiconnect_import_offered", "ankiconnect_imported_at")}
        return page_state({**_migrate({})[0], **keep}, self._status())

    def op_new_key(self, _arg: Any) -> str:
        return generate_api_key()

    def op_copy(self, text: str) -> bool:
        self.copy(str(text))
        return True

    def op_import_ankiconnect(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """Stage AnkiConnect's key, port and origins into the page; Save applies."""
        from .config import default_app_key
        from .dialogs import ANKICONNECT_ID, ankiconnect_import_changes

        ac = self.mw.addonManager.getConfig(ANKICONNECT_ID)
        if ac is None:
            return {"error": "No AnkiConnect settings are available to import."}
        base = self.saved()
        current, _ = config_from_form(base, {**draft["values"], "gates": draft["gates"]})
        current["apps"] = draft["apps"]
        old_key, old_origins = default_app_key(current), set(current.get("cors_allowlist") or [])
        current.update(ankiconnect_import_changes(current, ac, include_port=True))
        state = page_state({**base, **current}, self._status())
        added = len(set(current.get("cors_allowlist") or []) - old_origins)
        return {"values": state["values"], "apps": state["apps"], "pending": {
            "port": current["port"] or current["prefer_port"],
            "key": "Unchanged" if default_app_key(current) == old_key else "Copy from AnkiConnect",
            "origins": "No new origins" if not added else f"{added} new origin" + ("s" if added != 1 else ""),
        }}

    def op_save(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        from .settings_dialog import save_settings

        new_cfg, restart, errors = config_from_page(self.saved(), draft)
        if errors:
            return {"errors": errors}
        pending = bool(draft.get("pending_import"))
        try:
            save_settings(self.mw, new_cfg, disable_ankiconnect=pending)
        except Exception as exc:
            return {"errors": [f"Could not save settings: {exc}"]}
        self.restart = restart or pending
        self.saved_cfg = new_cfg
        self.close(True)
        return {"ok": True}

    def op_cancel(self, _arg: Any) -> bool:
        self.close(False)
        return True


def open_settings(mw: Any) -> None:
    make_dialog(mw).exec()


def make_dialog(mw: Any) -> Any:
    """The settings dialog, not yet shown (tools/check_settings_dialog.py drives it)."""
    from aqt.qt import QApplication, QDialog, QTimer, QVBoxLayout
    from aqt.utils import disable_help_button, restoreGeom, saveGeom
    from aqt.webview import AnkiWebView

    from .settings_dialog import _restart_server

    dlg = QDialog(mw)
    dlg.setWindowTitle("Tsunagi Settings")
    disable_help_button(dlg)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(0, 0, 0, 0)
    web = AnkiWebView(parent=dlg, title="Tsunagi settings")
    web.setObjectName("tsunagiSettingsPage")
    layout.addWidget(web)

    def close(saved: bool) -> None:
        # After the bridge call returns: closing inside it would tear down the
        # page while Qt is still delivering the reply.
        QTimer.singleShot(0, dlg.accept if saved else dlg.reject)

    bridge = SettingsBridge(mw, close=close,
                            copy=lambda text: QApplication.clipboard().setText(text))
    dlg.tsunagi_bridge, dlg.tsunagi_web = bridge, web  # for the real-dialog check
    web.set_bridge_command(bridge.handle, dlg)
    web.stdHtml(_page_html(), context=dlg)

    def finished(_result: int) -> None:
        saveGeom(dlg, _GEOM_KEY)
        web.cleanup()
        if bridge.saved_cfg is not None and bridge.restart:
            _restart_server(mw, enabled=bool(bridge.saved_cfg.get("enabled", True)))

    dlg.finished.connect(finished)
    dlg.resize(860, 640)
    restoreGeom(dlg, _GEOM_KEY)
    return dlg
