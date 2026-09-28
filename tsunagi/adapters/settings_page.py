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
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..shared.permissions import BUILTIN_ROLES, NO_ACCESS, PERMISSIONS, is_grant
from ..shared.version import ADDON_VERSION
from .config import ADDON_PACKAGE, DEFAULTS, _migrate
from .settings import approved_defaults
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
_GEOM_KEY = "tsunagiSettingsPage"  # not the old Qt dialog's saved size
_PREFIX = "tsunagi:"

# What each permission means, in the role editor's words: (area, label, short
# label for role summaries, description). Areas in display order; a test keeps
# this in step with shared/permissions.py.
AREAS: List[Tuple[str, str, str, str]] = [
    ("read", "Read", "Read", "See notes, cards, decks, note types, tags, review history and media."),
    ("write", "Change", "Change", "Add, edit and delete. Undo needs every kind of change."),
    ("gui", "Use Anki's windows", "Windows",
     "Open the Browser, Add and Edit windows and the reviewer on this computer."),
    ("sync", "Sync", "Sync", "Sync with AnkiWeb."),
    ("manage", "Manage the collection", "Manage",
     "Import, export, check the database, switch profile and close Anki."),
    ("events", "Live updates", "Live updates", "What the event stream sends as it happens."),
    ("local_files", "Read files on this computer", "Local files",
     "Media uploads that name a file on this computer. Anything with this can make "
     "Anki read any file your account can read."),
    ("memory_state", "Rewrite FSRS memory state", "FSRS state",
     "Overwrite what FSRS knows about cards. A faulty tool could quietly damage your scheduling."),
    ("addon", "Run add-on actions", "Add-ons",
     "Run the add-on actions enabled on the Add-ons page, including destructive ones (a backup is made first)."),
]
NAMES: Dict[str, str] = {
    "notes": "Notes", "cards": "Cards", "decks": "Decks", "deck_configs": "Deck options",
    "models": "Note types", "tags": "Tags", "reviews": "Review history", "media": "Media",
    "collection": "Collection info, jobs and the event stream", "addons": "Installed add-ons",
    "changes": "Changes to your collection", "reviews_live": "Each card you answer",
}
_NAME_LABEL = {"events:reviews": NAMES["reviews_live"]}

# (setting, label, short label for "Used by" lists, help)
NO_KEY_ROWS = [
    ("no_key_local_role", "Programs on this computer", "This computer",
     "Requests without a key from this computer, such as Yomitan or a script."),
    ("no_key_remote_role", "Other devices", "Other devices",
     "Requests without a key from anywhere else, including through Tailscale or "
     "another proxy. Anyone who can reach the port gets this role."),
]


def permission_catalog() -> List[Dict[str, Any]]:
    out = []
    for area, label, short, description in AREAS:
        names = sorted(p for p in PERMISSIONS if p.startswith(area + ":"))
        labelled = [{"name": n, "label": _NAME_LABEL.get(n, NAMES[n.split(":", 1)[1]])} for n in names]
        out.append({"area": area, "label": label, "short": short, "description": description,
                    "names": sorted(labelled, key=lambda n: n["label"])})
    return out


def _role_default(rid: str, approvals: Any) -> Optional[Dict[str, Any]]:
    builtin = BUILTIN_ROLES.get(rid)
    if builtin is None:
        return None
    return {"name": builtin["name"],
            "grants": sorted(set(builtin["grants"]) | approved_defaults(rid, approvals))}


def _approvals(value: Any) -> Dict[str, str]:
    return {k: v for k, v in value.items() if isinstance(v, str)} if isinstance(value, dict) else {}


def _roles_for_page(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    custom = cfg.get("roles") or {}
    approvals = cfg.get("addon_enabled")
    rows = []
    for rid, spec in {**BUILTIN_ROLES, **custom}.items():
        if not isinstance(spec, dict):
            continue
        default = _role_default(rid, approvals)
        grants = sorted(g for g in spec.get("grants") or [] if is_grant(g))
        rows.append({"id": rid, "name": str(spec.get("name") or rid),
                     "grants": default["grants"] if rid not in custom and default else grants,
                     "builtin": default is not None,
                     # Without add-on approvals: the page adds its draft's own
                     # (Default also has every approved normal action).
                     "default": _role_default(rid, {})})
    return rows


def providers_for_page() -> List[Dict[str, Any]]:
    """The add-ons offering actions, for the Add-ons page (main thread)."""
    from . import addon_actions, providers  # noqa: F401  (registers the bundled ones)
    return [{"id": p.id, "title": p.title, "unsupported": addon_actions.unavailable(p),
             "actions": [{"key": f"{p.id}/{i.name}", "title": i.title, "description": i.description,
                          "level": i.level, "shows_ui": i.shows_ui} for i in p.items]}
            for p in sorted(addon_actions.PROVIDERS.values(), key=lambda p: p.title.lower())]


def page_state(cfg: Dict[str, Any], ankiconnect: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the page renders, for `cfg` (the saved config, or defaults)."""
    return {
        "version": ADDON_VERSION,
        "fields": [f._asdict() for f in FIELDS],
        "values": form_values_from_config(cfg),
        "gates": [{"key": k, "label": label, "tooltip": tip, "on": on}
                  for k, label, tip, on in gate_rows(cfg)],
        "apps": [{"name": str(a.get("name") or ""), "key": str(a.get("key") or ""),
                  "role": str(a.get("role") or NO_ACCESS), "enabled": a.get("enabled") is not False}
                 for a in cfg.get("apps") or [] if isinstance(a, dict)],
        "no_key_rows": [{"setting": k, "label": label, "short": short, "help": help_text,
                         "role": str(cfg.get(k, DEFAULTS[k]))}
                        for k, label, short, help_text in NO_KEY_ROWS],
        "roles": _roles_for_page(cfg),
        "addon_enabled": _approvals(cfg.get("addon_enabled")),
        "catalog": permission_catalog(),
        "ankiconnect": {**ankiconnect, "history": import_history_text(cfg),
                        "imported": bool(cfg.get("ankiconnect_imported_at"))},
    }


def _stored_roles(roles: List[Dict[str, Any]], approvals: Any) -> Dict[str, Any]:
    """Only user-made roles and edited built-ins are saved."""
    out = {}
    for g in roles:
        spec = {"name": g["name"].strip(), "grants": sorted(set(g["grants"]))}
        if spec == _role_default(g["id"], approvals):
            continue
        out[g["id"]] = spec
    return out


class PageError(str):
    """A validation message that also says where to fix it, so Save can take
    the user there. Still a str for callers that only show the text."""
    page: str
    field: Optional[str]

    def __new__(cls, message: str, page: str, field: Optional[str] = None) -> "PageError":
        obj = super().__new__(cls, message)
        obj.page, obj.field = page, field
        return obj


def _value_error(message: str) -> PageError:
    field = "host" if message.startswith("Host") else next(
        (f.key for f in FIELDS if message.startswith(f.label)), None)
    return PageError(message, "web" if field == "cors_allowlist" else "server", field)


def validate_access(cfg: Dict[str, Any], draft: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    def add(message: str, page: str, field: Optional[str] = None) -> None:
        errors.append(PageError(message, page, field))
    roles = draft["roles"]
    ids = [g["id"] for g in roles]
    if len(set(ids)) != len(ids):
        add("Two roles have the same id.", "roles")
    for g in roles:
        if not re.fullmatch(r"[a-z0-9_]{1,40}", g["id"]):
            add(f"Role id {g['id']!r} may only use a-z, 0-9 and _.", "roles")
        if not g["name"].strip():
            add("Every role needs a name.", "roles")
        if not all(is_grant(x) for x in g["grants"]):
            add(f"{g['name']}: unknown permission.", "roles")
        if g["id"] == NO_ACCESS and g["grants"]:
            add("No access cannot grant anything.", "roles")
    for rid in BUILTIN_ROLES:
        if rid not in ids:
            add(f"The built-in role {BUILTIN_ROLES[rid]['name']!r} cannot be deleted.", "roles")
    names = [a["name"].strip() for a in draft["apps"]]
    keys = [a["key"] for a in draft["apps"]]
    if any(not n for n in names):
        add("Every app needs a name.", "apps")
    if len(set(names)) != len(names):
        add("Two apps have the same name.", "apps")
    if any(not k for k in keys):
        add("Every app needs a key; use New key.", "apps")
    if len(set(keys)) != len(keys):
        add("Two apps have the same key.", "apps")
    used = [a["role"] for a in draft["apps"]] + [draft[k] for k, *_ in NO_KEY_ROWS]
    for rid in sorted(set(used) - set(ids)):
        add(f"Role {rid!r} is in use but does not exist.", "apps")
    for key, level in (draft.get("addon_enabled") or {}).items():
        if not re.fullmatch(r"[a-z0-9_]+/[a-z0-9_]+", key) or level not in ("normal", "destructive"):
            add(f"Add-on setting {key!r} is not valid.", "addons")
    remote = draft["no_key_remote_role"]
    if (remote != NO_ACCESS and remote != cfg.get("no_key_remote_role", DEFAULTS["no_key_remote_role"])
            and not draft.get("confirm_remote")):
        add("Confirm that other devices may connect without a key.", "nokey", "confirmRemote")
    return errors


def config_from_page(cfg: Dict[str, Any], draft: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, List[str]]:
    """(new_cfg, restart_needed, errors) for the page's draft on top of `cfg`."""
    values = {**draft["values"], "gates": draft["gates"]}
    errors = [_value_error(e) for e in validate_values(values)] + validate_access(cfg, draft)
    if errors:
        return cfg, False, errors
    new_cfg, restart = config_from_form(cfg, values)
    # "enabled" is stored only when off, so apps that are on keep their old shape.
    new_cfg["apps"] = [{"name": a["name"].strip(), "key": a["key"], "role": a["role"],
                        **({} if a.get("enabled", True) else {"enabled": False})}
                       for a in draft["apps"]]
    for key, *_ in NO_KEY_ROWS:
        new_cfg[key] = draft[key]
    approvals = _approvals(draft.get("addon_enabled", cfg.get("addon_enabled")))
    new_cfg["addon_enabled"] = approvals
    new_cfg["roles"] = _stored_roles(draft["roles"], approvals)
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

    def __init__(self, mw: Any, *, restart: Callable[[bool], None],
                 close: Callable[[], None], copy: Callable[[str], None]) -> None:
        self.mw = mw
        self.restart = restart  # restart(enabled): apply server-level keys
        self.close = close      # close the window, no questions asked
        self.copy = copy
        self.dirty = False      # unsaved changes on the page (X/Esc asks first)

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
            logging.getLogger(__name__).exception("Settings page request failed")
            return {"error": str(exc)}

    def _status(self) -> Dict[str, Any]:
        from .dialogs import ankiconnect_status
        return ankiconnect_status(self.mw.addonManager)

    def op_state(self, _arg: Any) -> Dict[str, Any]:
        status = self._status()
        # Defaults ride along for "Restore defaults" (per page and global);
        # saving applies the draft over the saved config, so import history
        # and other bookkeeping survive a restore.
        return {**page_state(self.saved(), status), "providers": providers_for_page(),
                "defaults": page_state(_migrate({})[0], status)}

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
        """Save stays open and returns the saved state as the page's new
        baseline; only the X/Esc prompt's Save sends `close`."""
        from .settings_dialog import save_settings

        close = bool(draft.pop("close", False))
        new_cfg, restart, errors = config_from_page(self.saved(), draft)
        if errors:
            return {"errors": [{"message": str(e), "page": getattr(e, "page", None),
                                "field": getattr(e, "field", None)} for e in errors]}
        pending = bool(draft.get("pending_import"))
        try:
            save_settings(self.mw, new_cfg, disable_ankiconnect=pending)
        except Exception as exc:
            return {"errors": [f"Could not save settings: {exc}"]}
        if restart or pending:
            self.restart(bool(new_cfg.get("enabled", True)))
        self.dirty = False
        if close:
            self.close()
            return {"ok": True}
        return {"ok": True, "state": self.op_state(None)}

    def op_close(self, _arg: Any) -> bool:
        """Discard in the X/Esc prompt: close without saving."""
        self.dirty = False
        self.close()
        return True

    def op_dirty(self, dirty: Any) -> bool:
        self.dirty = bool(dirty)
        return True

    def op_server_status(self, _arg: Any) -> Dict[str, Any]:
        from ..app import server_url
        url = server_url()
        return {"running": url is not None, "url": url}


def open_settings(mw: Any) -> None:
    make_dialog(mw).exec()


def make_dialog(mw: Any) -> Any:
    """The settings dialog, not yet shown (tools/check_settings_dialog.py drives it)."""
    from aqt.qt import QApplication, QDialog, QTimer, QVBoxLayout
    from aqt.utils import disable_help_button, restoreGeom, saveGeom
    from aqt.webview import AnkiWebView

    from .settings_dialog import _restart_server

    class SettingsDialog(QDialog):
        def reject(self) -> None:
            # X and Esc: close at once when clean; with unsaved changes the
            # page asks Save / Discard / Keep editing.
            if bridge.dirty:
                web.eval("askClose()")
            else:
                super().reject()

    dlg = SettingsDialog(mw)
    dlg.setWindowTitle("Tsunagi Settings")
    disable_help_button(dlg)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(0, 0, 0, 0)
    web = AnkiWebView(parent=dlg, title="Tsunagi settings")
    web.setObjectName("tsunagiSettingsPage")
    layout.addWidget(web)

    def restart(enabled: bool) -> None:
        # After the bridge call returns, so the reply reaches the page first.
        QTimer.singleShot(0, lambda: _restart_server(mw, enabled=enabled))

    def close() -> None:
        # After the bridge call returns: closing inside it would tear down the
        # page while Qt is still delivering the reply.
        QTimer.singleShot(0, dlg.accept)

    bridge = SettingsBridge(mw, restart=restart, close=close,
                            copy=lambda text: QApplication.clipboard().setText(text))
    dlg.tsunagi_bridge, dlg.tsunagi_web = bridge, web  # for the real-dialog check
    web.set_bridge_command(bridge.handle, dlg)
    web.stdHtml(_page_html(), context=dlg)

    def finished(_result: int) -> None:
        saveGeom(dlg, _GEOM_KEY)
        web.cleanup()

    dlg.finished.connect(finished)
    dlg.resize(980, 680)
    restoreGeom(dlg, _GEOM_KEY)
    return dlg
