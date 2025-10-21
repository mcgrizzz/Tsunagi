# from typing import Any, Dict, List, Mapping, Sequence
# from aqt import mw

# from ..ops import as_query_op, on_main


# @as_query_op
# def get_decks_by_cards(ids: Sequence[int]) -> List[Any]:
#     return [mw.col.decks.get(did) for did in mw.col.decks.for_card_ids(ids)]