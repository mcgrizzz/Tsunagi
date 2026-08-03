from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class TagList(BaseModel):
    items: List[str]
    stats: dict


class TagRename(BaseModel):
    name: str


class TagBulkRequest(BaseModel):
    class Config:
        allow_population_by_field_name = True

    note_ids: List[int] = Field(alias="noteIds")
    # Space-separated, matching Anki's own bulk_add/bulk_remove signature.
    tags: str


class TagMutationResult(BaseModel):
    """`affected` counts NOTES changed, which is what Anki's ops report."""
    affected: int
    stats: dict
