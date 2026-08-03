"""
AnkiConnect-compatible RPC endpoint.

This module provides handlers that will be registered directly on the FastAPI app
to provide AnkiConnect compatibility at the root path (POST /).

AnkiConnect uses: POST http://localhost:8765/ with JSON body
Tsunagi equivalent: POST http://localhost:7777/ with same JSON format
"""
from __future__ import annotations

import traceback
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from . import models  # noqa: F401  (side-effect import: registers action handlers)
from .registry import registry


class AnkiConnectRequest(BaseModel):
    """
    AnkiConnect request format.

    Example:
        {
            "action": "findModelsById",
            "params": {"modelIds": [123, 456]},
            "version": 6
        }
    """
    action: str = Field(..., description="Action name to perform")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Parameters for the action")
    version: int = Field(default=6, description="AnkiConnect API version")


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


def handle_ankiconnect_rpc(request: AnkiConnectRequest) -> AnkiConnectResponse:
    """
    Handle AnkiConnect-style RPC requests.

    This function is called by the root POST endpoint to process AnkiConnect requests.

    Args:
        request: AnkiConnect request with action, params, and version

    Returns:
        AnkiConnect response with result or error
    """
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
