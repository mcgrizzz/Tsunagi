from __future__ import annotations

from pydantic import BaseModel

from .notes import NoteIds


class TagRow(BaseModel):
    """A row of GET /v1/tags."""
    name: str


class TagRename(BaseModel):
    name: str


class TagBulkRequest(NoteIds):
    # Space-separated, matching Anki's own bulk_add/bulk_remove signature.
    tags: str


class TagMutationResult(BaseModel):
    """`affected` counts NOTES changed, which is what Anki's ops report."""
    affected: int
    stats: dict
