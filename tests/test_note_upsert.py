"""POST /v1/notes:upsert (backlog 7.1): create, or merge into the one match."""
import pytest


@pytest.fixture()
def vocab(col):
    """A note type shaped like a mining card."""
    mm = col.models
    nt = mm.new("Mining")
    for name in ("Expression", "Sentence", "Audio"):
        mm.add_field(nt, mm.new_field(name))
    tmpl = mm.new_template("Card 1")
    tmpl["qfmt"], tmpl["afmt"] = "{{Expression}}", "{{Sentence}}"
    mm.add_template(nt, tmpl)
    mm.add(nt)
    return col


def item(expression="食べる", **fields):
    return {"noteTypeName": "Mining", "deckName": "Default", "tags": ["mined"],
            "fields": {"Expression": expression, **fields}}


def existing(col, expression="食べる", tags=("old",), deck="Default", **fields):
    note = col.new_note(col.models.by_name("Mining"))
    note["Expression"] = expression
    for name, value in fields.items():
        note[name] = value
    note.tags = list(tags)
    col.add_note(note, col.decks.id(deck))
    return note.id


def upsert(client, body, **params):
    resp = client.post("/v1/notes:upsert", json=body, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_no_match_creates(client, vocab):
    out = upsert(client, item(Sentence="s1"), include="cards")
    [created] = out["created"]
    assert out["updated"] == [] and out["failed"] == [] and len(created["cards"]) == 1
    assert vocab.get_note(created["id"])["Sentence"] == "s1"


def test_one_match_merges_by_the_rules(client, vocab):
    nid = existing(vocab, Sentence="s1", Audio="")
    out = upsert(client, {**item(Sentence="s2", Audio="[sound:a.mp3]"),
                          "onMatch": {"fields": {"Sentence": "append"}}})
    assert out["created"] == []
    assert out["updated"] == [{"index": 0, "id": nid, "fields_changed": ["Sentence", "Audio"],
                               "tags_changed": True}]
    note = vocab.get_note(nid)
    assert (note["Sentence"], note["Audio"]) == ("s1<br>s2", "[sound:a.mp3]")
    assert sorted(note.tags) == ["mined", "old"]


def test_default_rule_only_fills_empty_fields(client, vocab):
    nid = existing(vocab, Sentence="mine", Audio="")
    upsert(client, item(Sentence="theirs", Audio="new.mp3"))
    note = vocab.get_note(nid)
    assert (note["Sentence"], note["Audio"]) == ("mine", "new.mp3")


@pytest.mark.parametrize("rule, new, result", [
    ("keep", "new", "old"), ("replace", "new", "new"), ("replace", "", "old"),
    ("replace_if_empty", "new", "old"), ("append", "new", "old|new"), ("append", "old", "old"),
])
def test_each_field_rule(client, vocab, rule, new, result):
    nid = existing(vocab, Sentence="old")
    upsert(client, {**item(Sentence=new), "onMatch": {"fields": {"*": rule}, "separator": "|"}})
    assert vocab.get_note(nid)["Sentence"] == result


def test_repeating_an_append_changes_nothing(client, vocab):
    nid = existing(vocab, Sentence="s1")
    body = {**item(Sentence="s2"), "onMatch": {"fields": {"Sentence": "append"}}}
    upsert(client, body)
    again = upsert(client, body)
    assert again["updated"][0]["fields_changed"] == [] and again["updated"][0]["tags_changed"] is False
    assert vocab.get_note(nid)["Sentence"] == "s1<br>s2"


@pytest.mark.parametrize("mode, tags", [("union", ["mined", "old"]), ("replace", ["mined"]), ("keep", ["old"])])
def test_tag_modes(client, vocab, mode, tags):
    nid = existing(vocab)
    upsert(client, {**item(), "onMatch": {"tags": mode}})
    assert sorted(vocab.get_note(nid).tags) == tags


def test_default_match_is_ankis_duplicate_check(client, vocab):
    nid = existing(vocab, expression="<b>食べる</b>")  # HTML ignored, as Anki's duplicate check does
    out = upsert(client, item(Sentence="s"))
    assert [u["id"] for u in out["updated"]] == [nid]


def test_match_field_is_exact_and_case_insensitive(client, vocab):
    nid = existing(vocab, expression="x", Sentence="Hello*World")
    existing(vocab, expression="y", Sentence="HelloXWorld")
    out = upsert(client, {**item("z", Sentence="hello*world"), "match": {"field": "Sentence"}})
    assert [u["id"] for u in out["updated"]] == [nid]  # "*" is literal, case ignored


def test_several_matches_fail_that_item_only(client, vocab):
    a, b = existing(vocab, Sentence="1"), existing(vocab, Sentence="2")
    out = upsert(client, [item(Sentence="3"), item("飲む")])
    [failure] = out["failed"]
    assert failure["index"] == 0 and failure["code"] == "ambiguous"
    assert str(a) in failure["message"] and str(b) in failure["message"]
    assert [c["index"] for c in out["created"]] == [1]


def test_bad_match_field_is_reported(client, vocab):
    out = upsert(client, {**item(), "match": {"field": "Nope"}})
    assert out["failed"][0]["code"] == "invalid_note" and "Nope" in out["failed"][0]["message"]


def test_updated_cards_stay_in_their_deck(client, vocab):
    nid = existing(vocab, deck="Japanese")
    upsert(client, {**item(Sentence="s"), "deckName": "Default"})
    [cid] = vocab.card_ids_of_note(nid)
    assert vocab.get_card(cid).did == vocab.decks.id("Japanese")


def test_a_batch_is_one_undo_step(client, vocab):
    nid = existing(vocab, Sentence="")
    notes_before = vocab.note_count()
    upsert(client, [item(Sentence="filled"), item("飲む")])
    assert vocab.note_count() == notes_before + 1
    vocab.undo()
    assert vocab.note_count() == notes_before and vocab.get_note(nid)["Sentence"] == ""
