from __future__ import annotations

from typing import List, Optional

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


class AddonList(BaseModel):
    items: List[AddonInfo]
    stats: dict
