"""Public native workflows, with equivalent card fields and final note/media data."""
from __future__ import annotations

# Written out here deliberately: benchmark equivalence must not depend on the
# compatibility handler's own conversion code.
CARD_FIELDS = {
    "cardId": "id", "fieldOrder": "ord", "question": "question",
    "answer": "answer", "modelName": "model_name", "ord": "ord",
    "deckName": "deck_name", "css": "css", "factor": "factor",
    "interval": "interval", "note": "note_id", "type": "type", "queue": "queue",
    "due": "due", "reps": "reps", "lapses": "lapses", "left": "left",
    "mod": "mod", "nextReviews": "next_reviews", "flags": "flags",
}
CARD_SELECT = ",".join(dict.fromkeys([*CARD_FIELDS.values(), "fields"]))


def canonical_cards(cards):
    return [{**{key: card[field] for key, field in CARD_FIELDS.items()},
             "fields": {field["name"]: {"value": field["value"], "order": field["ord"]}
                        for field in card["fields"]}}
            for card in cards]


def run(workload, request):
    if workload.case["kind"] == "read_cards":
        # A zero benchmark batch means the entire known fixture in one response.
        query = {"select": CARD_SELECT, "shape": "object"}
        if workload.case["batch"]:
            query["limit"] = workload.case["batch"]
        cards, cursors = [], set()
        while True:
            page = request.native("GET", "/v1/cards", query)
            cards.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return cards
            assert cursor not in cursors, "native pagination repeated a cursor"
            cursors.add(cursor)
            query["cursor"] = cursor

    notes, uploads, destinations = [], [], []
    for source in workload.notes:
        note = {key: source[key] for key in ("modelName", "deckName", "tags")}
        note["fields"] = dict(source["fields"])
        note["allowDuplicate"] = source["options"]["allowDuplicate"]
        for kind in ("audio", "picture"):
            for attachment in source.get(kind, []):
                uploads.append({"filename": attachment["filename"], "data": attachment["data"]})
                destinations.append((len(notes), kind))
        notes.append(note)
    # Include both public requests and the client's field assembly in the timing.
    if uploads:
        result = request.native("POST", "/v1/media", uploads)
        assert not result["failed"], result["failed"]
        assert [item["index"] for item in result["created"]] == list(range(len(uploads)))
        for item in result["created"]:
            note_index, kind = destinations[item["index"]]
            stored = item["filename"]
            markup = f"[sound:{stored}]" if kind == "audio" else f'<img src="{stored}">'
            notes[note_index]["fields"]["Back"] += markup
    result = request.native("POST", "/v1/notes", notes)
    assert not result["failed"], result["failed"]
    assert [note["index"] for note in result["created"]] == list(range(len(notes)))
    return [note["id"] for note in result["created"]]
