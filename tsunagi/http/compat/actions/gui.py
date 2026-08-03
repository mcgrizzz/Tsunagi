"""
AnkiConnect compatibility handlers for GUI actions.

All aqt imports are function-local so this module stays importable headless
(same pattern as adapters/dialogs.py).
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki.notes import find_card_ids
from ....adapters.ops import call_on_main
from ..registry import registry


class GuiBrowseParams(BaseModel):
    query: Optional[str] = None
    # Deliberately untyped: canonical validates the shape itself and reports
    # 'reorderCards should be a dict: <value>', which a pydantic type error
    # would pre-empt with a different message.
    reorderCards: Optional[Any] = None


def _open_browser(query: Optional[str], reorder: Optional[Dict[str, Any]]) -> None:
    """Runs on the Qt main thread."""
    import aqt
    from aqt.qt import Qt

    browser = aqt.dialogs.open("Browser", aqt.mw)
    browser.activateWindow()

    if query is not None:
        browser.form.searchEdit.lineEdit().setText(query)
        if hasattr(browser, "onSearch"):
            browser.onSearch()
        else:
            browser.onSearchActivated()

    if reorder is not None:
        if not isinstance(reorder, dict):
            raise ValueError(f"reorderCards should be a dict: {reorder}")
        if not ("columnId" in reorder and "order" in reorder):
            # Canonical's message, unbalanced quote and all
            raise ValueError('Must provide a "columnId" and a "order" property"')
        order = reorder["order"]
        if order not in ("ascending", "descending"):
            raise ValueError(f"invalid card order: {order}")
        sort_order = (Qt.SortOrder.DescendingOrder if order == "descending"
                      else Qt.SortOrder.AscendingOrder)
        column_id = browser.table._model.active_column_index(reorder["columnId"])
        if column_id is None:
            raise ValueError(f"invalid columnId: {reorder['columnId']}")
        browser.table._on_sort_column_changed(column_id, sort_order)


@registry.register("guiBrowse", params=GuiBrowseParams)
def ac_guiBrowse(p: GuiBrowseParams) -> List[int]:
    # Dialog first, then the ids - canonical order, so the result reflects
    # the state after the search ran.
    call_on_main(_open_browser, p.query, p.reorderCards)
    return find_card_ids(p.query) if p.query is not None else []
