"""Expensive projections are built after filtering, with the same pages."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tsunagi.shared.planning import SearchSpec, SourceCaps
from tsunagi.shared.route_factory import create_resource_routes, make_id_getter


@pytest.fixture(params=[False, True], ids=["search-ids", "keyset"])
def query_client(request):
    rows = {i: {"id": i, "queue": -1 if i in (150, 290) else 0}
            for i in range(1, 301)}
    renders, calls = [], []

    def hydrate(ids, wants):
        calls.append((list(ids), wants))
        result = []
        for i in ids:
            row = dict(rows[i])
            if wants is None or wants & {"question", "answer"}:
                renders.append(i)
                row.update(question=f"Q{i}", answer=f"A{i}")
            result.append(row)
        return result

    def page_ids(last, limit):
        return [i for i in rows if last is None or i > last][:limit]

    caps = SourceCaps(
        search=SearchSpec(find_ids=lambda query: list(rows), hydrate=hydrate,
                          page_ids=page_ids if request.param else None),
        expensive_groups=(frozenset({"question", "answer"}),),
    )
    app = FastAPI()
    app.include_router(create_resource_routes(
        path="/v1/things", caps=caps, response_model=None,
        id_getter=make_id_getter("id"), resource_name="thing",
        resource_plural="things", tag="Things",
    ))
    with TestClient(app) as client:
        yield client, renders, calls


def query(client, method="GET", **params):
    response = (client.get("/v1/things", params=params) if method == "GET"
                else client.post("/v1/things/query", json=params))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("limit", [None, 1])
def test_explicit_selection_renders_only_returned_rows(query_client, method, limit):
    client, renders, calls = query_client
    params = {"select": "id,question", "where": ["queue==-1"]}
    if limit is not None:
        params["limit"] = limit
    items = []
    while True:
        page = query(client, method, **params)
        items.extend(page["items"])
        if page["next_cursor"] is None:
            break
        params["cursor"] = page["next_cursor"]
    assert items == [{"id": 150, "question": "Q150"}, {"id": 290, "question": "Q290"}]
    assert renders == [150, 290]
    assert all(wants == {"id", "queue"} for _, wants in calls if "question" not in wants)


def test_no_survivors_does_not_render(query_client):
    client, renders, _ = query_client
    assert query(client, select="id,question", where=["queue==7"])["items"] == []
    assert renders == []


@pytest.mark.parametrize("select,expected", [
    ("question", ["Q150", "Q290"]),
    ("id,question:front", [{"id": 150, "front": "Q150"}, {"id": 290, "front": "Q290"}]),
])
def test_deferred_projection_keeps_scalar_shape_and_aliases(query_client, select, expected):
    client, renders, _ = query_client
    assert query(client, select=select, where=["queue==-1"])["items"] == expected
    assert renders == [150, 290]


def test_cheap_projection_does_not_add_a_second_fetch(query_client):
    client, renders, calls = query_client
    page = query(client, select="id,queue", where=["queue==0"], limit=20)
    assert len(page["items"]) == 20
    assert len(calls) == 1
    assert renders == []


def test_work_already_needed_by_predicate_is_not_repeated(query_client):
    client, renders, _ = query_client
    page = query(client, select="id,answer", where=["question==Q150"])
    assert page["items"] == [{"id": 150, "answer": "A150"}]
    assert renders == list(range(1, 301))


@pytest.mark.parametrize("search", [None, "deck:Default"])
def test_real_cards_render_survivors_and_read_current_state(client, col, monkeypatch, search):
    from anki.cards import Card

    nt = col.models.by_name("Basic")
    for i in range(8):
        note = col.new_note(nt)
        note["Front"] = f"deferred-{i}"
        col.add_note(note, 1)
    ids = sorted(col.find_cards(""))
    suspended = ids[1::3]
    col.sched.suspend_cards(suspended)
    rendered = []
    original = Card.question

    def question(card, *args, **kwargs):
        rendered.append(int(card.id))
        return original(card, *args, **kwargs)

    monkeypatch.setattr(Card, "question", question)
    params = {"select": "id,question", "where": "queue==-1"}
    if search:
        params["search"] = search
    for expected in (suspended, suspended[1:]):
        rendered.clear()
        response = client.get("/v1/cards", params=params)
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()["items"]] == expected
        assert rendered == expected
        col.sched.unsuspend_cards(suspended[:1])
