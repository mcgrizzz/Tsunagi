"""Equivalent workloads and correctness checks, outside the timed requests."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def media_bytes(index, kind, size):
    # Small valid fixture headers; Anki stores attachments without decoding them.
    if kind == "picture":
        header = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=")
    else:
        import struct
        samples = bytes(max(2, size - 44))
        header = (b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVEfmt "
                  + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
                  + b"data" + struct.pack("<I", len(samples)) + samples)
    marker = hashlib.sha256(f"{kind}:{index}".encode()).digest()
    return (header + marker * (size // len(marker) + 1))[:max(size, len(header))]


def attachments(case):
    if case["kind"] not in ("add_media_new", "add_media_existing"):
        return {}
    return {f"bench-{i}.{extension}": media_bytes(i, kind, case["media_bytes"])
            for i in range(case["size"])
            for kind, extension in (("picture", "png"), ("audio", "wav"))}


def note_spec(index, media):
    note = {"modelName": "Basic", "deckName": "Default",
            "fields": {"Front": f"bulk-benchmark-{index}", "Back": f"meaning-{index}"},
            "tags": ["bulk_benchmark"], "options": {"allowDuplicate": False}}
    for kind, extension in (("picture", "png"), ("audio", "wav")):
        name = f"bench-{index}.{extension}"
        if name in media:
            note[kind] = [{"filename": name, "data": base64.b64encode(media[name]).decode(),
                           "fields": ["Back"]}]
    return note


def seed_collection(col, case):
    from .workflows import KINDS
    from .workflows import seed_collection as seed_workflow
    if case["kind"] in KINDS:
        return seed_workflow(col, case)
    if case["kind"] == "read_cards":
        model = col.models.by_name("Basic")
        for i in range(case["size"]):
            note = col.new_note(model)
            note["Front"], note["Back"] = f"bulk-benchmark-{i}", f"meaning-{i}"
            note.tags = ["bulk_benchmark"]
            col.add_note(note, 1)
    elif case["kind"] == "add_media_existing":
        for name, data in attachments(case).items():
            assert col.media.write_data(name, data) == name


class Workload:
    def __init__(self, case, implementation):
        self.case = case
        self.implementation = implementation
        self.media = attachments(case)
        self.notes = ([] if case["kind"] == "read_cards" else
                      [note_spec(i, self.media) for i in range(case["size"])])

    def run(self, request):
        if self.implementation == "native":
            from .native import run
            return run(self, request)
        if self.case["kind"] != "read_cards":
            return request("addNotes", {"notes": self.notes})
        ids = request("findCards", {"query": ""})
        batch = self.case["batch"] or len(ids) or 1
        cards = []
        for start in range(0, len(ids), batch):
            cards.extend(request("cardsInfo", {"cards": ids[start:start + batch]}))
        return cards

    def verify(self, col, result):
        size = self.case["size"]
        assert col.note_count() == size, "wrong final note count"
        assert col.card_count() == size, "wrong final card count"
        assert len(result) == size, "wrong result length"
        if self.case["kind"] == "read_cards":
            if self.implementation == "native":
                from .native import canonical_cards
                result = canonical_cards(result)
            ids = [card["cardId"] for card in result]
            assert len(set(ids)) == size, "duplicate returned card IDs"
            assert set(ids) == set(col.find_cards("")), "card result coverage differs"
            return digest(result)
        assert all(isinstance(nid, int) and nid > 0 for nid in result), "addNotes had failures"
        assert len(set(result)) == size, "duplicate created note IDs"
        normalized = []
        for i, nid in enumerate(result):
            note = col.get_note(nid)
            assert note["Front"] == f"bulk-benchmark-{i}"
            assert note["Back"].startswith(f"meaning-{i}")
            assert set(note.tags) == {"bulk_benchmark"}
            assert len(col.card_ids_of_note(nid)) == 1
            if self.media:
                assert f'<img src="bench-{i}.png">' in note["Back"]
                assert f"[sound:bench-{i}.wav]" in note["Back"]
            normalized.append({"fields": dict(note.items()), "tags": sorted(note.tags)})
        folder = Path(col.media.dir())
        for name, expected in self.media.items():
            assert (folder / name).read_bytes() == expected, f"media mismatch: {name}"
        assert {p.name for p in folder.iterdir() if not p.name.startswith(".")} == set(self.media)
        return digest(normalized)


def make_workload(case, implementation):
    from .workflows import KINDS, Workflow
    return (Workflow if case["kind"] in KINDS else Workload)(case, implementation)
