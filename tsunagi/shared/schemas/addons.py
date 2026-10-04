from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, StrictInt

from .wrappers import NULLABLE


class AddonInfo(BaseModel):
    id: str = Field(description="Folder name; the AnkiWeb ID for AnkiWeb installs")
    name: str = Field(description="Display name; the folder name when the add-on gives none.")
    ankiweb_id: Optional[int] = Field(None, description=(
        "AnkiWeb id; null when the folder name isn't a number (not installed from AnkiWeb)."), **NULLABLE)
    enabled: bool = Field(description="Whether the add-on is enabled.")
    compatible: bool = Field(description="Whether it declares support for this Anki version")
    version: Optional[str] = Field(None, description="The author's version label; null when none.", **NULLABLE)
    version_time: int = Field(description=(
        "When the installed version was published (AnkiWeb's upload time for AnkiWeb installs, otherwise "
        "the package's own timestamp), Unix seconds; 0 if unknown. Not when it was installed."))
    homepage: Optional[str] = Field(None, description="Homepage the add-on gives; null when none.", **NULLABLE)
    has_config: bool = Field(description="Has settings (edited in Anki's add-on manager)")
    has_config_ui: bool = Field(description="Registers its own settings dialog instead of Anki's JSON editor")
    provider: Optional[str] = Field(
        None, description="Id of the Tsunagi provider offering this add-on's actions; null when none. "
                          "See GET /v1/addons/{provider}/actions", **NULLABLE)


class AddonList(BaseModel):
    items: List[AddonInfo]
    stats: dict


class ActionParam(BaseModel):
    type: str = Field(description="integer, number, boolean, string or dates (a list of YYYY-MM-DD)")
    description: str
    required: bool
    default: Any = None
    min: Optional[Union[StrictInt, float]] = None
    max: Optional[Union[StrictInt, float]] = None


class ActionInfo(BaseModel):
    name: str
    title: str
    description: str
    impact: str = Field(description="How much running it by mistake could matter: read (changes nothing), "
                        "undoable (can be put back), or destructive (can't)")
    params: Dict[str, ActionParam]
    shows_ui: bool = Field(description="Shows a progress window or message on the computer running Anki")
    backup: bool = Field(False, description="Tsunagi backs up the collection before each run (destructive actions that change it outside undo)")
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
