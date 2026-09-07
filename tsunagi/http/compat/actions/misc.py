"""
AnkiConnect compatibility handlers: miscellaneous actions.
"""
from typing import Any, Dict

from pydantic import BaseModel

from ..registry import registry


class ApiReflectParams(BaseModel):
    # Keep JSON values intact; upstream validates containers before dispatch.
    scopes: Any = None
    actions: Any = None


@registry.register("version")
def ac_version(params: Dict[str, Any]) -> int:
    if params:
        key = next(iter(params))
        raise ValueError(f"AnkiConnect.version() got an unexpected keyword argument '{key}'")
    return 6


@registry.register("apiReflect", params=ApiReflectParams)
def ac_apiReflect(p: ApiReflectParams) -> Dict[str, Any]:
    """
    Capability discovery. Clients call this to learn which actions exist;
    answering "unsupported action" makes them read fields off an error
    envelope instead.
    """
    from ..ankiconnect import get_available_actions

    if not isinstance(p.scopes, list):
        raise ValueError("scopes has invalid value")
    if p.actions is not None and not isinstance(p.actions, list):
        raise ValueError("actions has invalid value")
    if "actions" not in p.scopes:
        return {"scopes": []}
    available = get_available_actions()["actions"]
    wanted = p.actions
    if wanted is not None:
        for action in wanted:
            if not isinstance(action, str):
                # Canonical passes every element to getattr(), which raises.
                raise ValueError(f"attribute name must be string, not '{type(action).__name__}'")
    actions = available if wanted is None else [a for a in wanted if a in available]
    return {"scopes": ["actions"], "actions": actions}
