"""Related-data workflows: compare the same answers across different API calls."""
from __future__ import annotations

from copy import deepcopy

from .workloads import digest, note_spec

KINDS = {"model_fields", "model_fields_multi", "duplicate_ids", "duplicate_ids_multi",
         "duplicate_mixed_multi", "save_card_ids"}


def seed_collection(col, case):
    if case["kind"].startswith("model_fields"):
        basic = deepcopy(col.models.by_name("Basic"))
        originals = list(col.models.all())
        for i in range(case["size"]):
            model = deepcopy(basic)
            model.update(id=0, name=f"Benchmark {i:04}")
            col.models.add(model)
        for model in originals:
            col.models.remove(model["id"])
    elif case["kind"].startswith("duplicate"):
        model = col.models.by_name("Basic")
        for i in range(case["size"]):
            if case["kind"] == "duplicate_mixed_multi" and i % 2:
                continue
            note = col.new_note(model)
            note["Front"], note["Back"] = f"bulk-benchmark-{i}", f"meaning-{i}"
            col.add_note(note, 1)


def call_actions(request, actions, multi):
    if not actions:
        return []
    if not multi:
        return [request(action["action"], action["params"]) for action in actions]
    envelopes = request("multi", {"actions": [dict(action, version=6) for action in actions]})
    assert len(envelopes) == len(actions)
    for envelope in envelopes:
        assert envelope["error"] is None, envelope
    return [envelope["result"] for envelope in envelopes]


class Workflow:
    def __init__(self, case, implementation):
        self.case = case
        self.native = implementation == "native"
        self.notes = [note_spec(i, {}) for i in range(case["size"])]
        for note in self.notes:
            note["options"]["duplicateScope"] = "collection"
            if case["kind"] == "save_card_ids":
                note["modelName"] = "Basic (and reversed card)"

    @staticmethod
    def native_note(note):
        return {**{k: v for k, v in note.items() if k != "options"}, **note["options"]}

    def run(self, request):
        kind = self.case["kind"]
        if kind.startswith("model_fields"):
            if self.native:
                page = request.native("GET", "/v1/models", {"select": "id,name,fields[].name"})
                assert page["next_cursor"] is None
                return page["items"]
            models = request("modelNamesAndIds", {})
            fields = call_actions(request, [
                {"action": "modelFieldNames", "params": {"modelName": name}} for name in models
            ], kind.endswith("_multi"))
            return [{"id": mid, "name": name, "fields": names}
                    for (name, mid), names in zip(models.items(), fields)]
        if kind.startswith("duplicate"):
            if self.native:
                return request.native("POST", "/v1/notes:check", {
                    "notes": [self.native_note(note) for note in self.notes]
                })["results"]
            checks = request("canAddNotesWithErrorDetail", {"notes": self.notes})
            assert len(checks) == len(self.notes)
            duplicates = []
            result = []
            for i, check in enumerate(checks):
                error = check.get("error")
                assert error is None or error == "cannot create note because it is a duplicate", check
                if error:
                    duplicates.append(i)
                result.append({"index": i, "can_add": check["canAdd"],
                               "state": "duplicate" if error else "normal", "duplicate_note_ids": []})
            matches = call_actions(request, [
                {"action": "findNotes", "params": {"query": f"note:Basic Front:re:^bulk-benchmark-{i}$"}}
                for i in duplicates
            ], kind.endswith("_multi"))
            for i, ids in zip(duplicates, matches):
                result[i]["duplicate_note_ids"] = ids
            return result
        # A single interactive save, with two generated cards. No bulk-write claim.
        note = self.notes[0]
        if self.native:
            saved = request.native("POST", "/v1/notes", self.native_note(note))["result"]
            return {"id": saved["id"], "cards": saved["cards"]}
        nid = request("addNote", {"note": note})
        return {"id": nid, "cards": request("findCards", {"query": f"nid:{nid}"})}

    def verify(self, col, result):
        kind, size = self.case["kind"], self.case["size"]
        if kind.startswith("model_fields"):
            expected = sorted([{"id": m["id"], "name": m["name"],
                                "fields": [f["name"] for f in m["flds"]]}
                               for m in col.models.all()], key=lambda m: m["id"])
            assert len(expected) == size, expected
            assert sorted(result, key=lambda m: m["id"]) == expected
            assert col.note_count() == col.card_count() == 0
            return digest(expected)
        if kind.startswith("duplicate"):
            existing = {col.get_note(nid)["Front"]: nid for nid in col.find_notes("")}
            assert len(existing) == ((size + 1) // 2 if kind == "duplicate_mixed_multi" else size)
            expected, actual = [], []
            for i, spec in enumerate(self.notes):
                nid = existing.get(spec["fields"]["Front"])
                expected.append({"index": i, "can_add": nid is None,
                                 "state": "normal" if nid is None else "duplicate",
                                 "duplicate_note_ids": [] if nid is None else [nid]})
            for row in result:
                actual.append({key: row[key] for key in expected[0]})
            assert actual == expected
            assert col.card_count() == len(existing)
            return digest(actual)
        assert col.note_count() == 1 and col.card_count() == 2
        note = col.get_note(result["id"])
        assert len(result["cards"]) == 2
        assert set(result["cards"]) == set(col.card_ids_of_note(note.id))
        assert dict(note.items()) == self.notes[0]["fields"]
        assert set(note.tags) == set(self.notes[0]["tags"])
        return digest({"fields": dict(note.items()), "tags": sorted(note.tags), "card_count": 2})
