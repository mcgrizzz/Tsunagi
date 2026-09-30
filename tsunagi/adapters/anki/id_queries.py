"""Run the id queries the shared SQL layer builds (shared/sql_query.py)."""
from typing import Any, List, Sequence

from anki.collection import Collection

from ..ops import as_query_op


@as_query_op
def select_ids(col: Collection, sql: str, args: Sequence[Any]) -> List[int]:
    return [int(i) for i in col.db.list(sql, *args)]
