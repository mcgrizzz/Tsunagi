"""Review rows are built without per-row validation; this keeps them on the schema.

The adapter reads the revlog and names each column itself. If a future Anki or
a schema edit makes those rows drift from ReviewInfo, this fails in CI instead
of a client receiving a different shape.
"""

from tsunagi.shared.schemas.reviews import ReviewInfo


def test_rows_match_review_schema(client, col, answer_cards):
    for word in ("a", "b", "c"):
        client.post("/v1/notes", json={"modelName": "Basic", "deckName": "Default",
                                       "fields": {"Front": word, "Back": "x"}})
    assert answer_cards(3, rating="again") == 3
    answer_cards(2)
    card = col.find_cards("")[0]
    # Learning intervals are negative seconds; imported history can carry any ints.
    imported = {"id": 1600000000000, "card_id": card, "usn": -1, "ease": 2, "interval": -600,
                "last_interval": -60, "factor": 1300, "time_ms": 7000, "type": 4}
    client.post("/v1/reviews", json={"reviews": [imported]})

    rows = client.get("/v1/reviews").json()["items"]
    assert len(rows) >= 6 and rows[0] == imported   # distinct values: columns map to names
    for row in rows:
        assert list(row) == list(ReviewInfo.__fields__), row
        assert all(type(value) is int for value in row.values()), row
        assert ReviewInfo.parse_obj(row).dict() == row
