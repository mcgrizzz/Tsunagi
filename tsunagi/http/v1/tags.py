"""
Tags router - hand-written for the same reason as media: a flat string
namespace with no integer id and nothing for the query planner to plan.
"""
import time
from typing import Optional

from fastapi import APIRouter, Body, Path, Query

from ...adapters.anki.tags import (
    add_tags,
    all_tags,
    clear_unused_tags,
    delete_tags,
    remove_tags,
    rename_tag,
)
from ...shared.errors import ResourceNotFoundError, handle_mutation_errors
from ...shared.schemas.tags import (
    TagBulkRequest,
    TagList,
    TagMutationResult,
    TagRename,
)

router = APIRouter()


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


@router.get(
    "/v1/tags",
    response_model=TagList,
    summary="List tags",
    description="Every tag in the collection, sorted. Nesting uses '::'.",
    tags=["Tags"],
    operation_id="listTags",
)
@handle_mutation_errors("list")
def list_tags(
    prefix: Optional[str] = Query(None, description="Only tags starting with this prefix"),
) -> TagList:
    start = time.perf_counter()
    items = all_tags()
    if prefix:
        items = [t for t in items if t.startswith(prefix)]
    return TagList(items=items, stats=_stats(start))


@router.patch(
    "/v1/tags/{tag}",
    response_model=TagMutationResult,
    summary="Rename a tag",
    description="Renames the tag and its children ('a' also renames 'a::b').",
    tags=["Tags"],
    operation_id="renameTag",
)
@handle_mutation_errors("rename")
def rename(
    tag: str = Path(..., description="The tag to rename"),
    body: TagRename = Body(...),
) -> TagMutationResult:
    start = time.perf_counter()
    if tag not in all_tags():
        raise ResourceNotFoundError("tag", tag)
    return TagMutationResult(affected=rename_tag(tag, body.name), stats=_stats(start))


@router.delete(
    "/v1/tags/{tag}",
    response_model=TagMutationResult,
    summary="Delete a tag",
    description="Removes the tag and its children from every note.",
    tags=["Tags"],
    operation_id="deleteTag",
)
@handle_mutation_errors("delete")
def delete(tag: str = Path(..., description="The tag to remove")) -> TagMutationResult:
    start = time.perf_counter()
    if tag not in all_tags():
        raise ResourceNotFoundError("tag", tag)
    return TagMutationResult(affected=delete_tags(tag), stats=_stats(start))


@router.post(
    "/v1/tags:clear-unused",
    response_model=TagMutationResult,
    summary="Clear unused tags",
    description="Drops registered tags that no note references any more.",
    tags=["Tags"],
    operation_id="clearUnusedTags",
)
@handle_mutation_errors("clear-unused")
def clear_unused() -> TagMutationResult:
    start = time.perf_counter()
    return TagMutationResult(affected=clear_unused_tags(), stats=_stats(start))


@router.post(
    "/v1/tags:bulk-add",
    response_model=TagMutationResult,
    summary="Add tags to many notes",
    description="One undoable op for the whole batch. `tags` is space-separated.",
    tags=["Tags"],
    operation_id="bulkAddTags",
)
@handle_mutation_errors("bulk-add")
def bulk_add(body: TagBulkRequest = Body(...)) -> TagMutationResult:
    start = time.perf_counter()
    return TagMutationResult(affected=add_tags(body.note_ids, body.tags), stats=_stats(start))


@router.post(
    "/v1/tags:bulk-remove",
    response_model=TagMutationResult,
    summary="Remove tags from many notes",
    description="One undoable op for the whole batch. `tags` is space-separated.",
    tags=["Tags"],
    operation_id="bulkRemoveTags",
)
@handle_mutation_errors("bulk-remove")
def bulk_remove(body: TagBulkRequest = Body(...)) -> TagMutationResult:
    start = time.perf_counter()
    return TagMutationResult(affected=remove_tags(body.note_ids, body.tags), stats=_stats(start))
