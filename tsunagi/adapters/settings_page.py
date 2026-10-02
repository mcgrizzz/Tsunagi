"""
The settings page: plain HTML/JS (tsunagi/web/settings.*) in an AnkiWebView
dialog, the way Anki shows its own deck options. The page talks to Python only
over Anki's pycmd bridge, never through Tsunagi's HTTP server, so no API
client, extension or card template can reach it (backlog 6.5a, 8.5b).

Module level is pure dict-in/dict-out logic, tested headless; the Qt shell
(open_settings) keeps its aqt imports local so this module imports without Qt.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .._kiso.settings import Bridge
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
     "Run the add-on actions enabled on the Add-ons page, including destructive ones."),
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
    # A value that is no longer an impact (such as an old "normal") is dropped,
    # so the action shows as disabled rather than blocking Save.
    ok = ("undoable", "destructive")
    return {k: v for k, v in value.items() if v in ok} if isinstance(value, dict) else {}


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
                     # (Default also has every approved undoable action).
                     "default": _role_default(rid, {})})
    return rows


def providers_for_page() -> List[Dict[str, Any]]:
    """The add-ons offering actions, for the Add-ons page (main thread)."""
    from . import addon_actions, providers  # noqa: F401  (registers the bundled ones)
    return [{"id": p.id, "title": p.title, "unsupported": addon_actions.unavailable(p),
             "actions": [{"key": f"{p.id}/{i.name}", "title": i.title, "description": i.description,
                          "impact": i.impact, "shows_ui": i.shows_ui, "backup": i.backup} for i in p.items]}
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
    for key, impact in (draft.get("addon_enabled") or {}).items():
        if not re.fullmatch(r"[a-z0-9_]+/[a-z0-9_]+", key) or impact not in ("undoable", "destructive"):
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


def page_draft(state: Dict[str, Any]) -> Dict[str, Any]:
    """The part of page_state the page edits and Save sends back: Kiso's shell
    keeps it as `saved` and `draft`, and compares slices of it for each page's
    unsaved dot."""
    draft = {"values": dict(state["values"]),
             "gates": {g["key"]: g["on"] for g in state["gates"]},
             "apps": [dict(a) for a in state["apps"]],
             "roles": [{k: g[k] for k in ("id", "name", "grants")} for g in state["roles"]],
             "addon_enabled": dict(state["addon_enabled"]),
             "confirm_remote": False}
    for row in state["no_key_rows"]:
        draft[row["setting"]] = row["role"]
    return draft


def _page_html() -> str:
    from .._kiso.settings import page_html

    def read(name: str) -> str:
        return (WEB_DIR / name).read_text(encoding="utf-8")
    # Inlined into Kiso's shell: nothing is served, and no web exports are needed.
    return page_html(css=[read("settings.css")], js=[read("settings.js")])


class SettingsBridge(Bridge):
    """Handles the page's pycmd("tsunagi:{op, arg}") calls; returns JSON values.
    Kiso's Bridge dispatches them and answers dirty and close."""

    prefix = _PREFIX

    def __init__(self, mw: Any, *, restart: Callable[[bool], None],
                 close: Optional[Callable[[], None]] = None, copy: Callable[[str], None],
                 offer_takeover: bool = False) -> None:
        super().__init__(close=close)   # close the window, no questions asked
        self.mw = mw
        self.offer_takeover = offer_takeover  # open with the AnkiConnect takeover (first start)
        self.restart = restart  # restart(enabled): apply server-level keys
        self.copy = copy

    def saved(self) -> Dict[str, Any]:
        # Persisted truth, not the live singleton: server-level keys the
        # running server hasn't picked up yet must display as saved.
        return _migrate(dict(self.mw.addonManager.getConfig(ADDON_PACKAGE) or {}))[0]

    def _status(self) -> Dict[str, Any]:
        from .dialogs import ankiconnect_status
        return ankiconnect_status(self.mw.addonManager)

    def op_state(self, _arg: Any) -> Dict[str, Any]:
        status = self._status()
        # Defaults ride along for "Restore defaults" (per page and global);
        # saving applies the draft over the saved config, so import history
        # and other bookkeeping survive a restore.
        offer, self.offer_takeover = self.offer_takeover, False  # once, not after a Save
        state = page_state(self.saved(), status)
        return {**state, "cfg": page_draft(state), "providers": providers_for_page(),
                "defaults": page_state(_migrate({})[0], status), "offer_takeover": offer}

    def op_new_key(self, _arg: Any) -> str:
        return generate_api_key()

    def op_copy(self, text: str) -> bool:
        self.copy(str(text))
        return True

    def _takeover_config(self) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """(saved config, the same with AnkiConnect's key, websites and port, AnkiConnect's config)."""
        from .dialogs import ANKICONNECT_ID, ankiconnect_import_changes

        ac = self.mw.addonManager.getConfig(ANKICONNECT_ID)
        if ac is None:
            raise ValueError("No AnkiConnect settings are available to import.")
        base = self.saved()
        return base, {**base, **ankiconnect_import_changes(base, ac, include_port=True)}, ac

    def op_takeover_preview(self, _arg: Any) -> Dict[str, Any]:
        """What taking over from AnkiConnect would change, for the dialog."""
        from .config import default_app_key

        base, new, ac = self._takeover_config()
        return {"port_from": base.get("port") or base.get("prefer_port"),
                "port": new.get("port") or new.get("prefer_port"),
                "key": "none" if not ac.get("apiKey") else
                       "same" if default_app_key(new) == default_app_key(base) else "new",
                "new_origins": [o for o in new["cors_allowlist"] if o not in base.get("cors_allowlist", [])],
                "enabled": self._status()["enabled"]}

    def op_takeover(self, _arg: Any) -> Dict[str, Any]:
        """Apply the takeover at once over the saved config (the page has no
        unsaved changes), then restart the server on AnkiConnect's port."""
        from .settings_dialog import save_settings

        try:
            save_settings(self.mw, self._takeover_config()[1], disable_ankiconnect=True)
        except Exception as exc:
            return {"error": f"Could not take over from AnkiConnect: {exc}"}
        self.restart(True)
        return {"ok": True, "state": self.op_state(None)}

    def op_save(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """Save stays open and returns the saved draft as the page's new
        baseline (the X/Esc prompt's Save then asks to close)."""
        from .settings_dialog import save_settings

        new_cfg, restart, errors = config_from_page(self.saved(), draft)
        if errors:
            return {"errors": [{"message": str(e), "page": getattr(e, "page", None),
                                "field": getattr(e, "field", None)} for e in errors]}
        try:
            save_settings(self.mw, new_cfg)
        except Exception as exc:
            return {"errors": [{"message": f"Could not save settings: {exc}", "page": None, "field": None}]}
        if restart:
            self.restart(bool(new_cfg.get("enabled", True)))
        self.dirty = False
        return {"ok": True, "cfg": self.op_state(None)["cfg"]}

    def op_requests(self, arg: Any) -> Dict[str, Any]:
        """Every client's totals, and the requests matching the page's filters."""
        from . import request_log
        f = arg if isinstance(arg, dict) else {}
        return {"clients": request_log.clients(),
                "entries": request_log.recent(f.get("client") or None, bool(f.get("failed")),
                                              str(f.get("text") or "")),
                "per_client": request_log.PER_CLIENT, "max_shown": request_log.MAX_SHOWN}

    def op_clear_requests(self, _arg: Any) -> bool:
        from . import request_log
        request_log.clear()
        return True

    def op_server_status(self, _arg: Any) -> Dict[str, Any]:
        from ..app import server_url
        url = server_url()
        return {"running": url is not None, "url": url}


def open_settings(mw: Any, *, offer_takeover: bool = False) -> None:
    make_dialog(mw, offer_takeover=offer_takeover).exec()


def make_dialog(mw: Any, *, offer_takeover: bool = False) -> Any:
    """The settings dialog, not yet shown (tools/check_settings_dialog.py drives it)."""
    from aqt.qt import QApplication, QTimer

    from .._kiso.settings import make_dialog as kiso_dialog
    from .settings_dialog import _restart_server

    def restart(enabled: bool) -> None:
        # After the bridge call returns, so the reply reaches the page first.
        QTimer.singleShot(0, lambda: _restart_server(mw, enabled=enabled))

    return kiso_dialog(mw, title="Tsunagi Settings", html=_page_html(), geom_key=_GEOM_KEY, size=(980, 680),
                       bridge=lambda dlg, web: SettingsBridge(
                           mw, restart=restart, copy=lambda text: QApplication.clipboard().setText(text),
                           offer_takeover=offer_takeover))
