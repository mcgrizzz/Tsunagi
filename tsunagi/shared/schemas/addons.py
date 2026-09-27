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
    has_config: bool = Field(description="Has a config readable at /v1/addons/{id}/config")
    has_config_ui: bool = Field(description="Registers its own settings dialog instead of Anki's JSON editor")


class AddonList(BaseModel):
    items: List[AddonInfo]
    stats: dict


class AddonConfig(BaseModel):
    id: str
    config: Optional[Dict[str, Any]] = Field(description="Null when the add-on has no config")


class AddonConfigWrite(BaseModel):
    config: Dict[str, Any] = Field(description="The whole config; it replaces the saved one")


class AddonConfigWriteResult(BaseModel):
    id: str
    changed: bool
    stats: dict
