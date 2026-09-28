from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AddonInfo(BaseModel):
    id: str = Field(description="Folder name; the AnkiWeb ID for AnkiWeb installs")
    name: str
    ankiweb_id: Optional[int] = None
    enabled: bool
    compatible: bool = Field(description="Whether it declares support for this Anki version")
    version: Optional[str] = Field(None, description="The author's version label, if any")
    installed_at: int = Field(description="Unix seconds")
    homepage: Optional[str] = None
    has_config: bool = Field(description="Has settings (edited in Anki's add-on manager)")
    has_config_ui: bool = Field(description="Registers its own settings dialog instead of Anki's JSON editor")
    provider: Optional[str] = Field(
        None, description="Id of the Tsunagi provider offering this add-on's actions, if any; "
                          "see GET /v1/addons/{provider}/actions")


class AddonList(BaseModel):
    items: List[AddonInfo]
    stats: dict


class ActionParam(BaseModel):
    type: str = Field(description="integer, boolean or dates (a list of YYYY-MM-DD)")
    description: str
    required: bool
    default: Any = None
    min: Optional[int] = None
    max: Optional[int] = None


class ActionInfo(BaseModel):
    name: str
    title: str
    description: str
    level: str = Field(description="read, normal or destructive (a backup is made before it runs)")
    params: Dict[str, ActionParam]
    shows_ui: bool = Field(description="Shows a progress window or message on the computer running Anki")
    status: str = Field(description="allowed, disabled (the user has not enabled it in Tsunagi's settings), "
                                    "not_permitted (the caller's role lacks it) or unsupported")


class ActionList(BaseModel):
    provider: str
    title: str
    unsupported: Optional[str] = Field(None, description="Why the provider cannot run, if it cannot")
    items: List[ActionInfo]
    stats: dict


class ActionResult(BaseModel):
    result: Any
    stats: dict
