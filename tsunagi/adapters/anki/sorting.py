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


def _sorts(col: Collection, notes: bool) -> Dict[str, Any]:
    """The sortable columns this Anki has; one it adds later is named by its label."""
    out = {}
    for column in col.all_browser_columns():
        if column.sorting_notes if notes else column.sorting_cards:
            name = NAMES.get(column.key) or column.cards_mode_label.lower().replace(" ", "_")
            out[name] = column
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
