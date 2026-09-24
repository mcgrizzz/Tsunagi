from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

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


class ImportOptions(BaseModel):
    """Omitted or null options use Anki's saved import preferences."""

    with_scheduling: Optional[bool] = Field(
        None, nullable=True, description="Import due dates and review history. Omit or null: use Anki's saved choice.")
    with_deck_configs: Optional[bool] = Field(
        None, nullable=True, description=(
            "Import deck presets. Omit or null: use Anki's saved choice. "
            "Explicit values require backend support; inspect /v1/collection/import-options."))
    merge_notetypes: Optional[bool] = Field(
        None, nullable=True, description="Merge compatible note types. Omit or null: use Anki's saved choice.")
    update_notes: Optional[Literal["if_newer", "always", "never"]] = Field(
        None, nullable=True, description="When to update existing notes. Omit or null: use Anki's saved choice.")
    update_notetypes: Optional[Literal["if_newer", "always", "never"]] = Field(
        None, nullable=True, description="When to update existing note types. Omit or null: use Anki's saved choice.")


class ImportPreferences(BaseModel):
    options: ImportOptions
    unsupported_options: List[str] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)


class ImportRequest(ImportOptions):
    path: str = Field(..., description="Source .apkg path, on the Anki machine")

    class Config:
        extra = "forbid"


class ImportResult(BaseModel):
    imported: int = 0
    updated: int = 0
    stats: Dict[str, Any] = Field(default_factory=dict)


class CollectionMeta(BaseModel):
    """
    Collection-level facts a client can't read from any row: whether FSRS is
    enabled (one collection-wide switch - NOT per deck or per preset, even
    though Anki's deck-options screen hosts the toggle), and the Anki version
    for feature detection.
    """
    fsrs: bool
    anki_version: str
    stats: Dict[str, Any] = Field(default_factory=dict)


class CollectionActionResult(BaseModel):
    """Result of a collection-level command that either worked or raised."""
    success: bool = True
    stats: Dict[str, Any] = Field(default_factory=dict)
