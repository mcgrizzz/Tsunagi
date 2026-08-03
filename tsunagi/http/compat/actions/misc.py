"""
AnkiConnect compatibility handlers: miscellaneous actions.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ..registry import registry


class ApiReflectParams(BaseModel):
    scopes: Optional[List[str]] = None
    actions: Optional[List[str]] = None


@registry.register("version")
def ac_version(params: Dict[str, Any]) -> int:
    return 6


@registry.register("apiReflect", params=ApiReflectParams)
def ac_apiReflect(p: ApiReflectParams) -> Dict[str, Any]:
    """
    Capability discovery. Clients call this to learn which actions exist;
    answering "unsupported action" makes them read fields off an error
    envelope instead.
    """
    from ..ankiconnect import get_available_actions

    available = get_available_actions()["actions"]
    scopes = p.scopes or []
    if "actions" not in scopes:
        return {"scopes": [], "actions": []}
    wanted = p.actions
    actions = available if wanted is None else [a for a in wanted if a in available]
    return {"scopes": ["actions"], "actions": actions}
