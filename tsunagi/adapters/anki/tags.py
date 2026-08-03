"""
Tag reads and mutations.

Tags are a flat string namespace with "::" nesting by convention, so Anki's
own tag operations apply to a tag and its children together - renaming "verb"
also renames "verb::transitive". That behaviour is preserved rather than
flattened.
"""
from typing import List, Sequence

from anki.collection import Collection

from ...shared.errors import ValidationError
from ..ops import as_collection_op, as_query_op


def _count(res: object) -> int:
    return int(getattr(res, "count", 0) or 0)


@as_query_op
def all_tags(col: Collection) -> List[str]:
    return list(col.tags.all())


@as_collection_op
def add_tags(col: Collection, note_ids: Sequence[int], tags: str) -> int:
    """Add space-separated tags to notes (one undoable op)."""
    return _count(col.tags.bulk_add([int(i) for i in note_ids], tags))


@as_collection_op
def remove_tags(col: Collection, note_ids: Sequence[int], tags: str) -> int:
    return _count(col.tags.bulk_remove([int(i) for i in note_ids], tags))


@as_collection_op
def rename_tag(col: Collection, old: str, new: str) -> int:
    """Rename a tag and its children across every note. Returns notes changed."""
    if not old.strip() or not new.strip():
        raise ValidationError("both the old and new tag name are required")
    return _count(col.tags.rename(old, new))


@as_collection_op
def delete_tags(col: Collection, tags: str) -> int:
    """Remove space-separated tags (and their children) from every note."""
    if not tags.strip():
        raise ValidationError("at least one tag is required")
    return _count(col.tags.remove(tags))


@as_collection_op
def clear_unused_tags(col: Collection) -> int:
    """Drop tags left in the tag list that no note references any more."""
    return _count(col.tags.clear_unused_tags())
