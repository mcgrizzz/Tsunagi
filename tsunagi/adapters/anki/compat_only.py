"""
Operations that exist only to serve the AnkiConnect shim.

Each one is here because Anki's own API has no equivalent with matching
semantics, and reshaping the native API around the difference would make the
native API worse. They are deliberate, like `_ac_duplicate_state` and
`relearn_cards`, not an accident of layering.
"""

from anki.collection import Collection

from ..ops import ValueWithChanges, as_collection_op


def _replace_tag_on(col: Collection, note, old: str, new: str):
    """The update's OpChanges when the note carried the tag, else None."""
    if not note.has_tag(old):
        return None
    note.remove_tag(old)
    note.add_tag(new)
    return col.update_note(note, skip_undo_entry=True)


def _replace_tags(col, note_ids, old, new):
    changed = 0
    changes = None
    error = None
    try:
        for nid in note_ids:
            try:
                note = col.get_note(nid)
            except Exception as exc:
                if type(exc).__name__ != "NotFoundError":
                    raise
                continue
            result = _replace_tag_on(col, note, old, new)
            if result is not None:
                changes = result
                changed += 1
    except Exception as exc:
        error = str(exc)
    # Publish successful earlier writes before the HTTP handler reports an error.
    value = (changed, error)
    return ValueWithChanges(value, changes) if changes is not None else value


@as_collection_op
def replace_tag_on_notes(col: Collection, note_ids, old, new):
    """Replace exact tags in input order, skipping unknown notes as upstream does."""
    return _replace_tags(col, note_ids, old, new)


@as_collection_op
def replace_tag_everywhere(col: Collection, old, new):
    """Use a targeted search for ordinary tags, then retain exact-match semantics."""
    from anki.collection import SearchNode

    try:
        if isinstance(old, str) and old:
            # The reference visits primary-key order; preserve it for partial writes.
            ids = sorted(col.find_notes(col.build_search_string(SearchNode(tag=old))))
        else:
            # Invalid values are only evaluated when a note is actually visited.
            ids = col.db.list("select id from notes")
        return _replace_tags(col, ids, old, new)
    except Exception as exc:
        return (0, str(exc))


@as_collection_op
def remove_unused_note_types(col: Collection) -> int:
    """
    AnkiConnect's `removeEmptyNotes`, which despite the name removes note
    *types* that no note uses - most likely "empty note type" phrased loosely
    rather than a bug. Destroys no content: use_count == 0 means there are no
    notes to lose. Compat-only; the native equivalent is DELETE /v1/models/{id}.
    """
    removed = 0
    changes = None
    for notetype in col.models.all():
        if col.models.use_count(notetype) == 0:
            changes = col.models.remove(notetype["id"])
            removed += 1
    return ValueWithChanges(removed, changes) if changes is not None else removed
