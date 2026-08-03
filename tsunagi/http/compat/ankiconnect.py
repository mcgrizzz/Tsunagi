"""
AnkiConnect-compatible RPC dispatcher (POST / on the FastAPI app).

Wire semantics verified against AnkiConnect's source:
- `version` defaults to 4. Success replies are BARE results for version <= 4
  and {"result": ..., "error": null} envelopes for >= 5.
- Error replies are ALWAYS {"result": null, "error": "<msg>"} regardless of
  version.
- `multi` re-dispatches each entry of params["actions"] as a full raw request
  (own version default 4, own key check); one failure doesn't abort the rest;
  nested multi is allowed. The list is wrapped per the OUTER version.
- requestPermission is exempt from the key/origin gates but its result is
  still version-formatted.

NOTE: action handlers are registered by importing the action modules
(compat/actions/). That side-effect import lives in app.py, not here, so this
dispatcher stays importable without Anki for tests.
"""
from __future__ import annotations

import secrets
import traceback
from typing import Any, Callable, Dict, Optional

from .errors import (  # noqa: F401  (API_KEY_ERROR re-exported)
    ACTION_FAILED,
    API_KEY_ERROR,
    UNSUPPORTED_ACTION,
)
from .registry import registry


def _success(version: int, result: Any) -> Any:
    return result if version <= 4 else {"result": result, "error": None}


def _error(message: str) -> Dict[str, Any]:
    return {"result": None, "error": message}


def _default_settings():
    from ...adapters.settings import settings
    return settings


def _default_ask(origin: str) -> bool:
    from ...adapters.dialogs import ask_permission_dialog
    return ask_permission_dialog(origin)


def _request_permission(
    origin: Optional[str],
    settings: Any,
    ask: Optional[Callable[[str], bool]],
) -> Dict[str, Any]:
    """
    AnkiConnect requestPermission contract (API v6).
    Known/local callers are granted without a dialog; an unknown browser
    origin triggers a main-thread Yes/No dialog and, on accept, is persisted
    to cors_allowlist (picked up live by the CORS middleware).
    """
    granted = {
        "permission": "granted",
        "requireApiKey": bool(settings.get("api_key", "")),
        "version": 6,
    }
    if not origin:  # local / non-browser client
        return granted
    if settings.is_origin_allowed(origin):
        return granted
    ask = ask or _default_ask
    if ask(origin):
        settings.add_cors_origin(origin)
        return granted
    return {"permission": "denied"}


def handle_ankiconnect_rpc(
    raw: Dict[str, Any],
    origin: Optional[str] = None,
    settings: Any = None,
    ask_permission: Optional[Callable[[str], bool]] = None,
) -> Any:
    """
    Handle an AnkiConnect-style RPC request.

    Args:
        raw: the raw request dict ({"action", "params", "version", "key"})
        origin: value of the HTTP Origin header, if any
        settings: injectable Settings (defaults to the live singleton)
        ask_permission: injectable permission prompt (defaults to the Qt dialog)

    Returns:
        Bare result (version <= 4 success) or a {"result","error"} envelope.
    """
    action = raw.get("action", "")
    try:
        version = int(raw.get("version", 4))
    except (TypeError, ValueError):
        version = 4
    params = raw.get("params") or {}
    key = raw.get("key")
    settings = settings if settings is not None else _default_settings()

    # requestPermission is always exempt from the key/origin gates - it's how
    # a browser client bootstraps access in the first place.
    if action == "requestPermission":
        return _success(version, _request_permission(origin, settings, ask_permission))

    # Key + origin gate. Runs per invocation, so multi sub-actions are each
    # gated with their own key (matches AnkiConnect).
    api_key: str = settings.get("api_key", "")
    key_ok = (not api_key) or (
        isinstance(key, str)
        and secrets.compare_digest(key.encode(), api_key.encode())
    )
    origin_ok = origin is None or settings.is_origin_allowed(origin)
    if not (key_ok and origin_ok):
        return _error(API_KEY_ERROR)

    # multi: dispatcher-level, recursive. Each sub-entry is a full raw request.
    if action == "multi":
        actions = params.get("actions")
        if not isinstance(actions, list):
            return _error("'actions' must be a list of requests")
        subs = [
            handle_ankiconnect_rpc(
                sub if isinstance(sub, dict) else {},
                origin=origin,
                settings=settings,
                ask_permission=ask_permission,
            )
            for sub in actions
        ]
        return _success(version, subs)

    if not registry.is_registered(action):
        return _error(UNSUPPORTED_ACTION)

    try:
        return _success(version, registry.handle(action, params))
    except ValueError as ve:
        # Client error - invalid parameters / canonical lookup failures
        return _error(str(ve))
    except Exception:
        # Server error - log internally, return a generic string to the client
        print("[tsunagi] compat action failed:\n" + traceback.format_exc())
        return _error(ACTION_FAILED)


def get_available_actions() -> Dict[str, list[str]]:
    """
    List all available AnkiConnect actions (registered handlers plus the
    dispatcher-level multi/requestPermission).

    Returns:
        Dictionary with 'actions' key containing list of action names
    """
    return {"actions": sorted(registry.list_actions() + ["multi", "requestPermission"])}
