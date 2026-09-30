"""The shared SQL layer (backlog 9.13) returns exactly what the Python predicate alone returns."""
import json

import pytest

from tsunagi.shared.filtering import parse_where
from tsunagi.shared.sql_query import Column, ColumnSource, compile_where

SOURCE = ColumnSource("t", {"n": Column("n", "int"), "b": Column("b", "bool"), "s": Column("s", "text")},
                      run=lambda sql, args: [])


@pytest.mark.parametrize("clause,pushed", [
    ("n==1", True), ("n!=1", True), ("n>=1", True), ("n in [1,2]", True), ("n not in [1]", True),
    ("n==true", False),        # the DSL never treats true as 1
    ("n==1.5", False), ("n>1.0", False),
    ("n in [1,true]", False), ("n in []", False),
    ("b==true", True), ("b!=false", True), ("b in [true]", True), ("b==1", False), ("b>false", False),
    ('s=="x"', True), ('s in ["x","y"]', True), ('s>"x"', False), ('s~="x"', False), ("s==1", False),
    ('fields[].value=="x"', False), ("missing==1", False),
])
def test_what_is_pushed(clause, pushed):
    assert bool(compile_where(SOURCE, [clause]).pushed) == pushed, clause
    parse_where(clause)


@pytest.fixture()
def data(client, col, answer_cards):
    notes = [{"modelName": "Basic (and reversed card)" if i % 3 == 0 else "Basic",
              "deckName": "Default", "tags": ["even"] if i % 2 == 0 else [],
              "fields": {"Front": f"<b>w{i}</b>" if i == 4 else f"w{i}", "Back": "x"}} for i in range(12)]
    assert client.post("/v1/notes", json=notes).json()["failed"] == []
    answer_cards(4, "good")
    answer_cards(2, "again")
    col.sched.suspend_cards([col.find_cards("")[1]])
    return col


def ids(client, path, **params):
    """Every matching row's id, walking pages when a limit is given."""
    out, params = [], dict(params)
    while True:
        body = client.get(path, params=params).json()
        assert "items" in body, body
        out += [row["id"] for row in body["items"]]
        if not body["next_cursor"]:
            return out
        params["cursor"] = body["next_cursor"]


CLAUSES = {
    "/v1/cards": ["queue==-1", "queue!=0", "reps>=1", "interval>0", "type in [1,2]", "type not in [0]",
                  "suspended==true", "suspended==false", "buried in [false]", "due<100000", "flag==0",
                  "queue==true", "note_id>0"],
    "/v1/notes": ["mod>0", "model_id>0", "usn!=-2", 'first_field in ["w1","w4","nope"]', 'first_field=="w5"',
                  'first_field=="<b>w4</b>"', 'guid!=""', "id>0", 'tags[]=="even"'],
    "/v1/reviews": ["ease==1", "ease in [1,3]", "interval<0", "type!=0", "time_ms>=0", "card_id>0",
                    "last_interval<=0"],
}


@pytest.mark.parametrize("path", list(CLAUSES))
def test_sql_path_matches_the_python_path(client, data, monkeypatch, path):
    from tsunagi.http.v1 import cards, notes, reviews
    caps = {"/v1/cards": cards.caps, "/v1/notes": notes.caps, "/v1/reviews": reviews.caps}[path]
    clauses = CLAUSES[path]
    queries = [{"where": [c]} for c in clauses]
    queries += [{"where": [a, b]} for a, b in zip(clauses, clauses[1:])]
    queries += [{**q, "search": "tag:even"} for q in queries[:6]]
    queries += [{**q, "limit": 3} for q in queries[:6]]
    queries += [{**q, "limit": 2, "search": "deck:Default"} for q in queries[:4]]
    with_sql = [ids(client, path, select="id", **q) for q in queries]
    monkeypatch.setattr(caps, "sql", None)
    without = [ids(client, path, select="id", **q) for q in queries]
    for query, a, b in zip(queries, with_sql, without):
        assert a == b, query
    assert any(with_sql), "the fixture should give some matches"


def test_deck_scoped_first_field_uses_the_checksum_with_the_search(client, data, monkeypatch):
    """Backlog 6.40: a search plus first_field used to load every note the search found."""
    from tsunagi.http.v1.notes import caps
    from tsunagi.shared.planning import make_plan

    where = [f"first_field in {json.dumps(['w1', 'w3', '<b>w4</b>'])}"]
    assert make_plan("id", where, caps, "deck:Default").mode == "sql"
    found = ids(client, "/v1/notes", search="deck:Default", where=where, select="id,first_field")
    monkeypatch.setattr(caps, "sql", None)
    assert found == ids(client, "/v1/notes", search="deck:Default", where=where, select="id,first_field")
    assert len(found) == 3
