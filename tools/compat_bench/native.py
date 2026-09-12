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
        query = {"select": CARD_SELECT, "shape": "object",
                 "limit": workload.case["batch"] or workload.case["size"]}
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

    ids = []
    for source in workload.notes:
        note = {key: source[key] for key in ("modelName", "deckName", "tags")}
        note["fields"] = dict(source["fields"])
        note["allowDuplicate"] = source["options"]["allowDuplicate"]
        # Native notes do not accept the AnkiConnect attachment envelope.
        # Store both files and use the returned names, including for an already
        # present file. Include every upload and create request in the timing.
        for kind in ("audio", "picture"):
            for attachment in source.get(kind, []):
                stored = request.native("POST", "/v1/media", {
                    "filename": attachment["filename"], "data": attachment["data"],
                })["filename"]
                markup = f"[sound:{stored}]" if kind == "audio" else f'<img src="{stored}">'
                note["fields"]["Back"] += markup
        ids.append(request.native("POST", "/v1/notes", note)["result"]["id"])
    return ids
