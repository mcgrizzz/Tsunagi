"""Idempotency-Key on every other write (backlog 6.64): a retry gets the recorded writes back."""
import pytest
from access import key_required

from tsunagi.adapters import idempotency, ops


@pytest.fixture(autouse=True)
def clean_journals():
    idempotency._journals.reset()
    yield
    idempotency._journals.reset()


@pytest.fixture()
def cid(client, col):
    nid = client.post("/v1/notes", json={"modelName": "Basic", "deckName": "Default",
                                         "fields": {"Front": "a", "Back": ""}}).json()["created"][0]["id"]
    return col.card_ids_of_note(nid)[0]


def answer(client, cid, key=None, ease=3, **headers):
    return client.post("/v1/cards:answer", json={"answers": [{"card_id": cid, "ease": ease}]},
                       headers={**({"Idempotency-Key": key} if key else {}), **headers})


def reviews(col, cid):
    return col.db.scalar("select count() from revlog where cid=?", cid)


def test_a_retried_answer_is_answered_once(client, col, cid):
    first, again = answer(client, cid, "k1"), answer(client, cid, "k1")
    assert first.status_code == again.status_code == 200
    assert again.json()["affected"] == first.json()["affected"] == 1
    assert "idempotent-replayed" not in first.headers and again.headers["idempotent-replayed"] == "true"
    assert reviews(col, cid) == 1 and col.get_card(cid).reps == 1


def test_without_a_key_a_retry_writes_again(client, col, cid):
    answer(client, cid), answer(client, cid)
    assert reviews(col, cid) == 2


def test_a_new_key_is_a_new_write(client, col, cid):
    answer(client, cid, "k1"), answer(client, cid, "k2")
    assert reviews(col, cid) == 2


def test_a_key_reused_for_a_different_request_is_refused(client, col, cid):
    answer(client, cid, "k1")
    resp = answer(client, cid, "k1", ease=1)
    assert resp.status_code == 400 and "different request" in resp.json()["detail"]
    assert reviews(col, cid) == 1


def test_the_same_key_on_another_route_is_another_request(client, col, cid):
    answer(client, cid, "k1")
    r = client.post("/v1/cards:suspend", json={"card_ids": [cid]}, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 200 and "idempotent-replayed" not in r.headers
    assert col.get_card(cid).queue == -1


def test_keys_belong_to_each_app(client, col, cid, reset_settings):
    reset_settings.update(**{**key_required("a" * 32, name="Yomitan"),
                             "apps": [{"name": "Yomitan", "key": "a" * 32, "role": "everything"},
                                      {"name": "Phone", "key": "b" * 32, "role": "everything"}]})
    answer(client, cid, "same", **{"X-Api-Key": "a" * 32})
    other = answer(client, cid, "same", **{"X-Api-Key": "b" * 32})
    assert "idempotent-replayed" not in other.headers and reviews(col, cid) == 2


def test_a_write_that_completes_after_a_503_is_returned_to_the_retry(client, col, cid, monkeypatch):
    # The first attempt outlasts op_timeout_seconds: 503, but Anki still runs
    # the write later. The retry must get that result, not answer again.
    queued, run_async = [], ops.collection_op_run_async
    monkeypatch.setattr(ops, "collection_op_run_async",
                        lambda fn, *a, on_success, on_failure, **kw: queued.append((fn, a, kw, on_success, on_failure)))
    monkeypatch.setattr(ops, "op_timeout", lambda: 0.05)
    first = answer(client, cid, "late")
    assert first.status_code == 503 and "retry with the same Idempotency-Key" in first.json()["detail"]
    assert answer(client, cid, "late").status_code == 503   # still running: waits, starts nothing
    assert len(queued) == 1

    fn, args, kwargs, on_success, on_failure = queued[0]
    monkeypatch.setattr(ops, "collection_op_run_async", run_async)
    run_async(fn, *args, on_success=on_success, on_failure=on_failure, **kwargs)   # Anki finally runs it
    retry = answer(client, cid, "late")
    assert retry.status_code == 200 and retry.headers["idempotent-replayed"] == "true"
    assert retry.json()["affected"] == 1 and reviews(col, cid) == 1


def test_a_failed_write_runs_again_on_retry(client, col, cid, monkeypatch):
    calls, run_async = [], ops.collection_op_run_async

    def flaky(fn, *a, on_success, on_failure, **kw):
        calls.append(1)
        if len(calls) == 1:
            return on_failure(RuntimeError("Anki fell over"))
        return run_async(fn, *a, on_success=on_success, on_failure=on_failure, **kw)
    monkeypatch.setattr(ops, "collection_op_run_async", flaky)
    assert answer(client, cid, "k1").status_code == 500
    retry = answer(client, cid, "k1")
    assert retry.status_code == 200 and "idempotent-replayed" not in retry.headers
    assert len(calls) == 2 and reviews(col, cid) == 1


def test_patch_and_reads_take_a_key_too(client, col, cid):
    nid = col.get_card(cid).nid
    for _ in range(2):
        r = client.patch(f"/v1/notes/{nid}", json={"fields": {"Back": "x"}}, headers={"Idempotency-Key": "p"})
        assert r.status_code == 200
    assert r.headers["idempotent-replayed"] == "true"
    q = client.post("/v1/notes/query", json={"select": "id"}, headers={"Idempotency-Key": "q"})
    assert q.status_code == 200 and "idempotent-replayed" not in q.headers   # nothing to record
