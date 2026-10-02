"""
Tags: the list is a shared resource list (rows `{"name": ...}`, keyed by name;
backlog 6.71); rename, delete and the bulk verbs are written here.
"""
import time

from fastapi import Body, Path

from ...adapters.anki.tags import (
    add_tags,
    all_tags,
    clear_unused_tags,
    delete_tags,
    remove_tags,
    rename_tag,
)
from ...shared.errors import ResourceNotFoundError, handle_mutation_errors
from ...shared.permissions import requires
from ...shared.planning import SourceCaps
from ...shared.route_factory import create_resource_routes
from ...shared.schemas.tags import (
    TagBulkRequest,
    TagMutationResult,
    TagRename,
    TagRow,
)

# Query: GET /v1/tags, POST /v1/tags/query, with the parameters every list takes.
router = create_resource_routes(
    path="/v1/tags",
    caps=SourceCaps(fetch_all=lambda wants=None: [{"name": t} for t in all_tags()], key_type=str),
    row_model=TagRow,
    id_getter=lambda row: row["name"],
    resource_name="tag",
    resource_plural="tags",
    permission_resource="tags",
    tag="Tags",
    description="Every tag in the collection; nesting uses '::' (where=name^=\"Japanese::\" for one branch).",
)


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


@router.patch(
    "/v1/tags/{tag}",
    openapi_extra=requires("write:tags"),
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
    openapi_extra=requires("write:tags"),
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
    openapi_extra=requires("write:tags"),
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
    openapi_extra=requires("write:tags"),
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
    openapi_extra=requires("write:tags"),
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
