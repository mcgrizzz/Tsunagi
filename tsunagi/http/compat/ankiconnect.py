"""
AnkiConnect-compatible RPC endpoint.

This module provides handlers that will be registered directly on the FastAPI app
to provide AnkiConnect compatibility at the root path (POST /).

AnkiConnect uses: POST http://localhost:8765/ with JSON body
Tsunagi equivalent: POST http://localhost:7777/ with same JSON format

NOTE: action handlers are registered by importing the action modules
(e.g. compat/models.py). That side-effect import lives in app.py, not here,
so this dispatcher stays importable without Anki for tests.
"""
from __future__ import annotations

import secrets
import traceback
from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel, Field

from .registry import registry

# Canonical AnkiConnect error string - clients string-match on it.
API_KEY_ERROR = "valid api key must be provided"


class AnkiConnectRequest(BaseModel):
    """
    AnkiConnect request format.

    Example:
        {
            "action": "findModelsById",
            "params": {"modelIds": [123, 456]},
            "version": 6,
            "key": "optional api key"
        }
    """
    action: str = Field(..., description="Action name to perform")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Parameters for the action")
    version: int = Field(default=6, description="AnkiConnect API version")
    key: Optional[str] = Field(default=None, description="API key (required when api_key is configured)")


class AnkiConnectResponse(BaseModel):
    """
    AnkiConnect response format.

    Success:
        {"result": <data>, "error": null}

    Error:
        {"result": null, "error": "error message"}
    """
    result: Any = Field(default=None, description="Result data (null on error)")
    error: Optional[str] = Field(default=None, description="Error message (null on success)")


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
    request: AnkiConnectRequest,
    origin: Optional[str] = None,
    settings: Any = None,
    ask_permission: Optional[Callable[[str], bool]] = None,
) -> AnkiConnectResponse:
    """
    Handle AnkiConnect-style RPC requests.

    Args:
        request: AnkiConnect request with action, params, version, and key
        origin: value of the HTTP Origin header, if any
        settings: injectable Settings (defaults to the live singleton)
        ask_permission: injectable permission prompt (defaults to the Qt dialog)

    Returns:
        AnkiConnect response with result or error
    """
    settings = settings if settings is not None else _default_settings()

    # requestPermission is always exempt from the key/origin gates - it's how
    # a browser client bootstraps access in the first place.
    if request.action == "requestPermission":
        return AnkiConnectResponse(
            result=_request_permission(origin, settings, ask_permission),
            error=None,
        )

    # Key + origin gate (canonical AnkiConnect error on failure)
    api_key: str = settings.get("api_key", "")
    key_ok = (not api_key) or (
        request.key is not None
        and secrets.compare_digest(request.key.encode(), api_key.encode())
    )
    origin_ok = origin is None or settings.is_origin_allowed(origin)
    if not (key_ok and origin_ok):
        return AnkiConnectResponse(result=None, error=API_KEY_ERROR)

    try:
        # Check if action is registered
        if not registry.is_registered(request.action):
            available = registry.list_actions()
            return AnkiConnectResponse(
                result=None,
                error=f"Unknown action '{request.action}'. Available: {', '.join(available) if available else 'none'}"
            )

        # Execute the action
        result = registry.handle(request.action, request.params)

        return AnkiConnectResponse(result=result, error=None)

    except ValueError as ve:
        # Client error - invalid parameters
        return AnkiConnectResponse(result=None, error=str(ve))

    except Exception:
        # Server error - log internally, return a generic string to the client
        print("[tsunagi] compat action failed:\n" + traceback.format_exc())
        return AnkiConnectResponse(result=None, error="Action failed")


def get_available_actions() -> Dict[str, list[str]]:
    """
    List all registered AnkiConnect actions.

    Returns:
        Dictionary with 'actions' key containing list of action names
    """
    return {"actions": registry.list_actions()}
