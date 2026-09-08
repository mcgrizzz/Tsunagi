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
- requestPermission is exempt from the key gate but its result is still
  version-formatted.

Origin enforcement lives in the HTTP layer (app.py: origin_allowed_for -> 403
with an empty body, as AnkiConnect does), not here, so that multi sub-actions
aren't re-checked and a blocked origin gets the same wire response
AnkiConnect gives.

NOTE: action handlers are registered by importing the action modules
(compat/actions/). That side-effect import lives in app.py, not here, so this
dispatcher stays importable without Anki for tests.
"""
from __future__ import annotations

import secrets
import traceback
from typing import Any, Callable, Dict, Optional

from ...adapters.dialogs import PermissionDecision
from ...shared.errors import ValidationError as TsunagiValidationError
from .errors import (  # noqa: F401  (API_KEY_ERROR re-exported)
    ACTION_FAILED,
    API_KEY_ERROR,
    UNSUPPORTED_ACTION,
)
from .registry import registry

_ACTIONS_CACHE = None
_HTTP_PERMISSION = object()


def _success(version: Any, result: Any) -> Any:
    try:
        return result if version <= 4 else {"result": result, "error": None}
    except TypeError as exc:
        # Nested versions bypass HTTP validation. Upstream formats the response
        # after executing the action, so a bad version does not undo its writes.
        return _error(str(exc))


def _error(message: str) -> Dict[str, Any]:
    return {"result": None, "error": message}


def _default_settings():
    from ...adapters.settings import settings
    return settings


def _default_ask(origin: Any) -> PermissionDecision:
    from ...adapters.dialogs import ask_permission_dialog
    return ask_permission_dialog(origin)


def _request_permission(
    origin: Any,
    settings: Any,
    ask: Optional[Callable[[Any], bool | PermissionDecision]],
    *,
    allowed: Any = _HTTP_PERMISSION,
) -> Dict[str, Any]:
    """
    AnkiConnect requestPermission contract (API v6).
    Known/local callers are granted without a dialog; an unknown browser
    origin triggers a main-thread Yes/No dialog and, on accept, is persisted
    to cors_allowlist (picked up live by the CORS middleware).
    Nested requests supply `allowed` themselves; false forces the prompt even
    for a local origin because they bypass upstream's HTTP context injection.
    """
    granted = {
        "permission": "granted",
        # Canonical spells this with a lowercase k ("requireApikey"); clients
        # read that exact key, so don't "fix" the casing.
        "requireApikey": bool(settings.get("api_key", "")),
        "version": 6,
    }
    if allowed is _HTTP_PERMISSION:
        allowed = origin is None or settings.is_origin_allowed(origin)
    if allowed:
        return granted
    if origin in settings.get("ankiconnect_ignore_origins", []):
        return {"permission": "denied"}
    ask = ask or _default_ask
    decision = ask(origin)
    if decision:
        # Nested permission calls can explicitly force a prompt for an already
        # allowed origin. Upstream appends every acceptance, including duplicates
        # and non-string child values; keep that behavior in the shim.
        settings.update(cors_allowlist=[*settings.get("cors_allowlist", []), origin])
        return granted
    if origin and isinstance(decision, PermissionDecision) and decision.ignore:
        settings.update(ankiconnect_ignore_origins=[
            *settings.get("ankiconnect_ignore_origins", []), origin,
        ])
    return {"permission": "denied"}


def handle_ankiconnect_rpc(
    raw: Dict[str, Any],
    origin: Optional[str] = None,
    settings: Any = None,
    ask_permission: Optional[Callable[[Any], bool | PermissionDecision]] = None,
    *,
    _nested: bool = False,
) -> Any:
    """
    Handle an AnkiConnect-style RPC request.

    Args:
        raw: the raw request dict ({"action", "params", "version", "key"})
        origin: value of the HTTP Origin header, if any
        settings: injectable Settings (defaults to the live singleton)
        ask_permission: injectable permission prompt (defaults to the Qt dialog)
        _nested: internal marker for multi children that bypass HTTP context injection

    Returns:
        Bare result (version <= 4 success) or a {"result","error"} envelope.
    """
    action = raw.get("action", "")
    version = raw.get("version", 4)
    params = raw.get("params", {})
    key = raw.get("key")
    settings = settings if settings is not None else _default_settings()

    # requestPermission is always exempt from the key/origin gates - it's how
    # a browser client bootstraps access in the first place.
    if action == "requestPermission":
        from .signatures import validate_arguments

        try:
            # Upstream's HTTP wrapper supplies these two arguments from the
            # Origin gate only for the outer request. Multi children bind their
            # own arguments without another pass through the HTTP wrapper.
            if not _nested and isinstance(params, dict):
                validate_arguments(action, {**params, "origin": origin, "allowed": True})
            else:
                validate_arguments(action, params)
            if _nested:
                return _success(version, _request_permission(
                    params["origin"], settings, ask_permission, allowed=params["allowed"]))
            return _success(version, _request_permission(origin, settings, ask_permission))
        except ValueError as e:
            return _error(str(e))

    # Key gate. Runs per invocation, so multi sub-actions are each gated with
    # their own key (matches AnkiConnect).
    api_key: str = settings.get("api_key", "")
    key_ok = (not api_key) or (
        isinstance(key, str)
        and secrets.compare_digest(key.encode(), api_key.encode())
    )
    if not key_ok:
        return _error(API_KEY_ERROR)

    # Malformed action/params must remain RPC errors, including inside multi.
    # Otherwise dictionary lookup or params.get() escapes as an HTTP 500.
    if not isinstance(action, str):
        return _error(UNSUPPORTED_ACTION)
    if action != "multi" and not registry.is_registered(action):
        return _error(UNSUPPORTED_ACTION)

    from .signatures import validate_arguments

    try:
        validate_arguments(action, params)
    except ValueError as e:
        return _error(str(e))

    # multi: dispatcher-level, recursive. Each sub-entry is a full raw request.
    if action == "multi":
        try:
            # Upstream iterates directly: malformed entries abort this multi,
            # retaining earlier writes and preventing later entries from running.
            subs = [
                handle_ankiconnect_rpc(
                    sub, origin=origin, settings=settings,
                    ask_permission=ask_permission, _nested=True,
                )
                for sub in params["actions"]
            ]
        except (TypeError, AttributeError) as exc:
            return _error(str(exc))
        return _success(version, subs)

    try:
        return _success(version, registry.handle(action, params))
    except (ValueError, TsunagiValidationError) as e:
        # Client error - invalid parameters, canonical lookup failures, or an
        # adapter rejecting input (e.g. an unusable media filename). These
        # carry a useful message, so don't hide them behind ACTION_FAILED.
        return _error(str(e))
    except Exception:
        # Server error - log internally, return a generic string to the client
        print("[tsunagi] compat action failed:\n" + traceback.format_exc())
        return _error(ACTION_FAILED)


def origin_allowed_for(action: str, origin: Optional[str], settings: Any = None) -> bool:
    """
    AnkiConnect's rule: a request with no Origin (non-browser client) is fine,
    an allowlisted origin is fine, and requestPermission is always let through
    so a browser client can ask for access.
    """
    if origin is None:
        return True
    if action == "requestPermission":
        return True
    settings = settings if settings is not None else _default_settings()
    return settings.is_origin_allowed(origin)


def get_available_actions() -> Dict[str, list[str]]:
    """
    List all available AnkiConnect actions (registered handlers plus the
    dispatcher-level multi/requestPermission).

    Returns:
        Dictionary with 'actions' key containing list of action names
    """
    global _ACTIONS_CACHE
    if _ACTIONS_CACHE is None:
        # Registration is import-time and immutable afterwards.
        _ACTIONS_CACHE = sorted(registry.list_actions() + ["multi", "requestPermission"])
    return {"actions": _ACTIONS_CACHE}
