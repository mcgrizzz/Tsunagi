"""Card rows are built without per-row validation; this keeps them on the schema.

The adapter names each card's values itself. If a future Anki or a schema edit
makes those rows drift from CardInfo, this fails in CI instead of a client
receiving a different shape.
"""

from tsunagi.shared.schemas.cards import CardInfo


def test_rows_match_card_schema(client, col, answer_cards):
    client.post("/v1/notes", json=[
        {"modelName": "Basic (and reversed card)", "deckName": "Default",
         "fields": {"Front": "食べる", "Back": "to eat"}},
        {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "a", "Back": "b"}},
    ])
    col.set_config("fsrs", True)   # answered cards then carry FSRS memory state
    assert answer_cards(2) == 2
    first, second, third = col.find_cards("", order="c.id")
    col.sched.suspend_cards([second])
    col.set_user_flag_for_cards(5, [third])
    card = col.get_card(third)
    card.custom_data = '{"k":1}'
    col.update_card(card)

    rows = client.get("/v1/cards").json()["items"]
    assert [row["id"] for row in rows] == [first, second, third]
    for row in rows:
        assert list(row) == list(CardInfo.__fields__), row
        assert CardInfo.parse_obj(row).dict() == row
        live = col.get_card(row["id"])
        # Distinct sources for each position: values map to the right names.
        assert (row["note_id"], row["deck_id"], row["ord"], row["queue"], row["due"],
                row["interval"], row["reps"], row["flags"]) == (
            live.nid, live.did, live.ord, live.queue, live.due, live.ivl, live.reps, live.flags)
        assert row["fields"] == [{"name": n, "value": v, "ord": i}
                                 for i, (n, v) in enumerate(live.note().items())]
    assert [row["suspended"] for row in rows] == [False, True, False]
    assert rows[2]["flag"] == 5 and rows[2]["custom_data"] == '{"k":1}'
    assert rows[0]["deck_name"] == "Default" and rows[0]["model_name"] == "Basic (and reversed card)"
    assert all(isinstance(row["question"], str) and row["question"] for row in rows)
    reviewed = [row for row in rows if row["reps"]]
    assert reviewed and all(set(row["memory_state"]) == {"stability", "difficulty"} for row in reviewed)
    for row in reviewed:
        assert all(type(v) is float for v in row["memory_state"].values())
        assert all(row[key] is None or type(row[key]) is float for key in ("desired_retention", "decay"))
        assert row["last_review_time"] is None or type(row["last_review_time"]) is int
