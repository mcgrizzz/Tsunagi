"""
Operations that exist only to serve the AnkiConnect shim.

Each one is here because Anki's own API has no equivalent with matching
semantics, and reshaping the native API around the difference would make the
native API worse. They are deliberate, like `_ac_duplicate_state` and
`relearn_cards`, not an accident of layering.
"""
from typing import Sequence

from anki.collection import Collection

from ..ops import as_collection_op


def _replace_tag_on(col: Collection, note, old: str, new: str) -> bool:
    if not note.has_tag(old):
        return False
    note.remove_tag(old)
    note.add_tag(new)
    col.update_note(note)
    return True


@as_collection_op
def replace_tag_on_notes(col: Collection, note_ids: Sequence[int],
                         old: str, new: str) -> int:
    """
    Swap one exact tag for another on the given notes.

    Compat-only. `col.tags.rename` renames a tag *and its children*, and
    `col.tags.find_and_replace` substitutes substrings inside each tag -
    AnkiConnect's replaceTags does neither, matching the tag exactly and
    leaving "verb::transitive" alone when replacing "verb". Unknown note ids
    are skipped, as canonical does.
    """
    changed = 0
    for nid in note_ids:
        try:
            note = col.get_note(int(nid))
        except Exception as e:
            if type(e).__name__ == "NotFoundError":
                continue
            raise
        if _replace_tag_on(col, note, old, new):
            changed += 1
    return changed


@as_collection_op
def replace_tag_everywhere(col: Collection, old: str, new: str) -> int:
    """replaceTagsInAllNotes - the same exact-match swap over every note."""
    changed = 0
    for nid in col.find_notes(""):
        if _replace_tag_on(col, col.get_note(int(nid)), old, new):
            changed += 1
    return changed


@as_collection_op
def remove_unused_note_types(col: Collection) -> int:
    """
    AnkiConnect's `removeEmptyNotes`, which despite the name removes note
    *types* that no note uses - most likely "empty note type" phrased loosely
    rather than a bug. Destroys no content: use_count == 0 means there are no
    notes to lose. Compat-only; the native equivalent is DELETE /v1/models/{id}.
    """
    removed = 0
    for notetype in col.models.all():
        if col.models.use_count(notetype) == 0:
            col.models.remove(notetype["id"])
            removed += 1
    return removed
