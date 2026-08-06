"""
Schema drift guard: the complete inventory of Anki's SQLite schema that
Tsunagi's raw SQL depends on.

Policy (see the adapters): raw SQL is reads-only against the frozen core -
`cards`, `notes`, `revlog` and `col.mod` - which no Anki schema migration
has ever altered (schema 11 through 18 only ever ADDED indexes to them).
The restructured tables (decks, notetypes, deck configs, tags) are reached
through Python APIs only. This test runs against every pinned Anki version,
so bumping a pin turns any future drift into red CI instead of user reports.
"""
import pytest

# table -> columns our SQL names (selects, where clauses, inserts)
RAW_SQL_SURFACE = {
    "cards": {"id", "nid", "ord", "did", "type", "queue"},
    "notes": {"id", "mod", "mid"},
    "revlog": {"id", "cid", "usn", "ease", "ivl", "lastIvl", "factor",
               "time", "type"},
    "col": {"mod"},
}


@pytest.mark.parametrize("table", sorted(RAW_SQL_SURFACE))
def test_columns_we_rely_on_exist(col, table):
    have = {row[1] for row in col.db.all(f"pragma table_info({table})")}
    missing = RAW_SQL_SURFACE[table] - have
    assert not missing, (
        f"Anki's `{table}` table no longer has {sorted(missing)} - every raw "
        f"SQL statement naming them must be revisited (grep the adapters)"
    )
