from __future__ import annotations

from pydantic import BaseModel, Field

from .notes import NoteIds
from .wrappers import RequestBody


class TagRow(BaseModel):
    """A row of GET /v1/tags."""
    name: str = Field(description='Tag name; "::" separates levels of a hierarchical tag.')


class TagRename(RequestBody):
    name: str


class TagBulkRequest(NoteIds):
    # Space-separated, matching Anki's own bulk_add/bulk_remove signature.
    tags: str


class TagMutationResult(BaseModel):
    """`affected` counts NOTES changed, which is what Anki's ops report."""
    affected: int
    stats: dict
