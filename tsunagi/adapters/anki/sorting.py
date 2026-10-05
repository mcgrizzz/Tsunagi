"""
Anki's Browser sorts, by their Browser names, for `order=` on cards and notes
(backlog 8.1). The sort is Anki's own: `due` orders new, learning and review
cards as the Browser does. Ties come back in ascending id, in both
directions, on every checked Anki (2026-09-30).
"""
from typing import Any, Dict, List

from anki.collection import Collection

from ..ops import as_query_op

# Browser column keys -> the names `order` takes: the Browser's own labels.
NAMES = {
    "cardDue": "due", "cardIvl": "interval", "cardEase": "ease", "cardLapses": "lapses",
    "cardReps": "reviews", "noteCrt": "created", "cardMod": "card_modified",
    "noteMod": "note_modified", "deck": "deck", "note": "note_type", "noteFld": "sort_field",
    "noteTags": "tags", "originalPosition": "position", "template": "card_type",
    "difficulty": "difficulty", "stability": "stability", "retrievability": "retrievability",
}


# Row field names for the sorts that order exactly by that field's values, so
# `order` also takes the names `select` and `where` use. Not `ease_factor`: the ease
# sort puts new cards apart (checked on 26.08, 2026-09-30).
FIELD_NAMES = {False: {"reps": "cardReps", "modified": "cardMod"},
               True: {"modified": "noteMod", "id": "noteCrt"}}


# What the API description lists (6.101): the sorts every supported Anki has,
# checked against the running Anki by tests/test_sorting.py.
CARD_SORTS = ("card_modified", "card_type", "created", "deck", "difficulty", "due", "ease",
              "interval", "lapses", "modified", "note_modified", "note_type", "position", "reps",
              "retrievability", "reviews", "sort_field", "stability", "tags")
NOTE_SORTS = ("card_modified", "card_type", "created", "deck", "due", "ease", "id", "interval",
              "lapses", "modified", "note_modified", "note_type", "position", "reviews", "sort_field", "tags")


def _sorts(col: Collection, notes: bool) -> Dict[str, Any]:
    """The sortable columns this Anki has; one it adds later is named by its label."""
    out = {}
    for column in col.all_browser_columns():
        if column.sorting_notes if notes else column.sorting_cards:
            name = NAMES.get(column.key) or column.cards_mode_label.lower().replace(" ", "_")
            out[name] = column
    by_key = {column.key: column for column in out.values()}
    out.update({field: by_key[key] for field, key in FIELD_NAMES[notes].items() if key in by_key})
    return out


@as_query_op
def sort_names(col: Collection, notes: bool) -> List[str]:
    return sorted(_sorts(col, notes))


@as_query_op
def find_sorted(col: Collection, query: str, name: str, descending: bool, notes: bool) -> List[int]:
    """Ids an Anki search matches (every card or note for ""), in that Browser sort."""
    column = _sorts(col, notes)[name]
    find = col.find_notes if notes else col.find_cards
    try:
        return [int(i) for i in find(query, order=column, reverse=descending)]
    except Exception as e:
        if type(e).__name__ in ("SearchError", "InvalidInput"):
            raise ValueError(f"Invalid Anki search: {e}") from e
        raise
