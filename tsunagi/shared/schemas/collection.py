from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProfileList(BaseModel):
    """Every profile Anki knows about, and which one is open."""
    items: List[str]
    active: Optional[str] = None
    stats: Dict[str, Any] = Field(default_factory=dict)


class ProfileLoad(BaseModel):
    name: str = Field(..., description="Profile to switch to")


class ProfileLoadResult(BaseModel):
    # False when there is no profile by that name. Switching is asynchronous -
    # Anki may still be closing the old profile when this returns.
    loaded: bool
    stats: Dict[str, Any] = Field(default_factory=dict)


class SyncResult(BaseModel):
    # SyncCollectionResponse.ChangesRequired: 0 = no changes, 1 = normal sync.
    # Anything else means a full upload or download, which Anki must drive
    # itself, and is reported as an error rather than a status here.
    status: int
    server_message: str = ""
    stats: Dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    deck: str = Field(..., description="Name of the deck to export")
    path: str = Field(..., description="Destination .apkg path, on the Anki machine")
    with_scheduling: bool = Field(
        False, description="Include due dates and review history")
    with_media: bool = Field(True, description="Bundle referenced media files")


class ImportRequest(BaseModel):
    path: str = Field(..., description="Source .apkg path, on the Anki machine")


class ImportResult(BaseModel):
    imported: int = 0
    updated: int = 0
    stats: Dict[str, Any] = Field(default_factory=dict)


class CollectionActionResult(BaseModel):
    """Result of a collection-level command that either worked or raised."""
    success: bool = True
    stats: Dict[str, Any] = Field(default_factory=dict)
