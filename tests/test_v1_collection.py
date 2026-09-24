"""
Collection-level routes and their AnkiConnect aliases.

Only the parts that are honestly testable without a Qt main window: the
export/import round trip, reload, and getActiveProfile (the fake aqt.mw
carries a profile name because notesInfo reports it). GET /v1/profiles needs
mw.pm.profiles(), and profile switching and sync need a live main window, so
those are manual-checklist territory.
"""


import pytest


def rpc(client, action, params=None, version=6):
    body = {"action": action, "version": version}
    if params is not None:
        body["params"] = params
    return client.post("/", json=body).json()


def add_note(client, front, deck="JP"):
    return client.post("/v1/notes?include=cards", json={
        "modelName": "Basic", "deckName": deck,
        "fields": {"Front": front, "Back": "x"}}).json()["created"][0]


def seed(client):
    client.post("/v1/decks", json={"name": "JP"})
    add_note(client, "犬")
    add_note(client, "猫")


class TestExportImportRoundTrip:
    """
    The real test of both endpoints: export a deck, destroy it, import it back
    and check the notes returned.
    """

    def test_round_trip_restores_the_notes(self, client, col, tmp_path):
        seed(client)
        path = str(tmp_path / "jp.apkg")

        assert client.post("/v1/collection:export", json={
            "deck": "JP", "path": path}).status_code == 200

        nids = [n["id"] for n in client.get("/v1/notes").json()["items"]]
        col.remove_notes(nids)
        assert client.get("/v1/notes").json()["items"] == []

        body = client.post("/v1/collection:import", json={"path": path}).json()
        assert body["imported"] == 2
        fronts = {n["fields"][0]["value"]
                  for n in client.get("/v1/notes").json()["items"]}
        assert fronts == {"犬", "猫"}

    def test_export_writes_a_file(self, client, tmp_path):
        seed(client)
        path = tmp_path / "out.apkg"
        client.post("/v1/collection:export", json={"deck": "JP", "path": str(path)})
        assert path.is_file() and path.stat().st_size > 0

    def test_scheduling_is_opt_in(self, client, tmp_path):
        # Both branches of the signature split must accept the flag.
        seed(client)
        for flag in (True, False):
            resp = client.post("/v1/collection:export", json={
                "deck": "JP", "path": str(tmp_path / f"s{flag}.apkg"),
                "with_scheduling": flag})
            assert resp.status_code == 200, resp.text

    def test_unknown_deck_is_404(self, client, tmp_path):
        resp = client.post("/v1/collection:export", json={
            "deck": "Nope", "path": str(tmp_path / "x.apkg")})
        assert resp.status_code == 404


class TestReload:
    def test_reload_succeeds(self, client):
        assert client.post("/v1/collection:reload").json()["success"] is True

    def test_reload_preserves_live_state_without_deprecated_reset(self, client, col, monkeypatch):
        add_note(client, "keep undo", deck="Default")
        undo = col.undo_status()
        model = col.models.by_name("Basic")
        model["css"] = "unsaved editor state"
        monkeypatch.delattr(type(col), "reset")

        assert client.post("/v1/collection:reload").json()["success"] is True
        assert rpc(client, "reloadCollection") == {"result": None, "error": None}
        assert col.models.get(model["id"]) is model
        assert model["css"] == "unsaved editor state"
        assert col.undo_status() == undo

    def test_reference_marks_reload_as_a_deprecated_noop(self, client):
        schema = client.get("/openapi.json").json()
        operation = schema["paths"]["/v1/collection:reload"]["post"]
        assert operation["deprecated"] is True
        assert "no reload" in operation["description"]


class TestCompatAliases:
    def test_export_and_import(self, client, col, tmp_path):
        seed(client)
        path = str(tmp_path / "compat.apkg")
        assert rpc(client, "exportPackage", {"deck": "JP", "path": path}) == {
            "result": True, "error": None}

        col.remove_notes([n["id"] for n in client.get("/v1/notes").json()["items"]])
        assert rpc(client, "importPackage", {"path": path}) == {
            "result": True, "error": None}
        assert len(client.get("/v1/notes").json()["items"]) == 2

    def test_export_unknown_deck_is_false_not_an_error(self, client, tmp_path):
        # Canonical returns False rather than raising.
        assert rpc(client, "exportPackage", {
            "deck": "Nope", "path": str(tmp_path / "x.apkg")}) == {
            "result": False, "error": None}

    def test_include_sched_is_canonicals_spelling(self, client, tmp_path):
        seed(client)
        assert rpc(client, "exportPackage", {
            "deck": "JP", "path": str(tmp_path / "s.apkg"),
            "includeSched": True})["error"] is None

    def test_get_active_profile(self, client):
        assert rpc(client, "getActiveProfile") == {"result": "User 1", "error": None}

    def test_reload_collection_returns_null(self, client):
        assert rpc(client, "reloadCollection") == {"result": None, "error": None}


class TestCollectionMeta:
    def test_fsrs_flag_tracks_the_collection_switch(self, client, col):
        body = client.get("/v1/collection").json()
        assert body["fsrs"] is False   # fresh collections default to SM-2

        col.set_config("fsrs", True)
        assert client.get("/v1/collection").json()["fsrs"] is True

    def test_anki_version_is_reported(self, client):
        body = client.get("/v1/collection").json()
        assert isinstance(body["anki_version"], str) and body["anki_version"]
        assert "duration_ms" in body["stats"]


class TestRedocPage:
    def test_serves_a_pinned_working_bundle(self, client):
        # The default redoc@next bundle on jsdelivr is broken (redoc 3 alpha
        # restructure -> MIME mismatch under nosniff); we pin redoc@2.
        resp = client.get("/redoc")
        assert resp.status_code == 200
        assert "redoc@2/bundles/redoc.standalone.js" in resp.text


class TestCapabilities:
    def test_versions_agree_with_health_and_openapi(self, client):
        from anki.buildinfo import version

        from tsunagi.shared.version import ADDON_VERSION, API_VERSION

        response = client.get("/v1/capabilities")
        assert response.status_code == 200, response.text
        versions = response.json()["versions"]
        assert versions == {"api": API_VERSION, "addon": ADDON_VERSION, "anki": version}
        health = client.get("/v1/health").json()
        assert health["versions"] == versions
        assert health["version"] == versions["addon"]
        schema = client.get("/openapi.json").json()
        assert schema["info"]["version"] == versions["addon"]
        assert schema["paths"]["/v1/capabilities"]["get"]["operationId"] == "getCapabilities"

    def test_collection_switch_does_not_disable_computations(self, client, col):
        col.set_config("fsrs", False)
        disabled = client.get("/v1/capabilities").json()
        assert disabled["features"]["fsrs_scheduling"]["status"] == "disabled"
        assert disabled["features"]["fsrs_scheduling"]["setting"] == "anki.fsrs"
        col.set_config("fsrs", True)
        enabled = client.get("/v1/capabilities").json()
        assert enabled["features"]["fsrs_scheduling"]["status"] == "available"
        assert disabled["operations"] == enabled["operations"]
        assert client.get("/v1/collection").json()["fsrs"] is True

    def test_every_fsrs_operation_and_option_is_available(self, client):
        operations = client.get("/v1/capabilities").json()["operations"]
        for name in ("compute-params", "evaluate-params", "simulate", "simulate-workload",
                     "optimal-retention"):
            operation = operations[f"POST /v1/fsrs:{name}"]
            assert operation["status"] == "available", name
            assert all(option["status"] != "unsupported" for option in operation.get("options", {}).values())

    def test_health_still_works_without_collection(self, client, monkeypatch):
        import aqt

        monkeypatch.setattr(aqt.mw, "col", None)
        response = client.get("/v1/health")
        assert response.status_code == 200
        assert response.json()["versions"]["anki"]
        assert client.get("/v1/capabilities").status_code == 503

    def test_partial_backend_is_inspected_without_running_operations(self):
        from types import SimpleNamespace

        from tsunagi.adapters.anki.fsrs import capabilities

        def forbidden(message):
            raise AssertionError("Discovery invoked a backend computation")

        assert capabilities(SimpleNamespace())["supported"] is False
        backend = SimpleNamespace(compute_optimal_retention=forbidden)
        result = capabilities(backend)
        assert result["supported"] is True
        assert result["operations"]["optimal_retention"]["available"] is True
        assert result["operations"]["simulate_workload"]["available"] is False
        assert result["operations"]["compute_params"] == {"available": False, "unsupported_options": []}


class TestImportChoices:
    @staticmethod
    def package(client, col, tmp_path):
        seed(client)
        col.db.execute("update cards set type=2, queue=2, due=100, ivl=21, reps=5, factor=2500")
        cid = col.db.scalar("select id from cards limit 1")
        col.db.execute(
            "insert into revlog values (?, ?, -1, 3, 21, 10, 2500, 1000, 1)",
            1700000000000, cid,
        )
        path = str(tmp_path / "choices.apkg")
        response = client.post("/v1/collection:export", json={
            "deck": "JP", "path": path, "with_scheduling": True,
        })
        assert response.status_code == 200, response.text
        col.remove_notes(col.find_notes(""))
        col.db.execute("delete from revlog")
        return path

    @pytest.mark.parametrize("saved", [False, True])
    @pytest.mark.parametrize("choice", ["omitted", None, False, True])
    def test_scheduling_and_history_follow_choice(self, client, col, tmp_path, saved, choice):
        path = self.package(client, col, tmp_path)
        # A real import establishes the saved preference, as Anki's dialog does.
        response = client.post("/v1/collection:import", json={
            "path": path, "with_scheduling": saved,
        })
        assert response.status_code == 200, response.text
        col.remove_notes(col.find_notes(""))
        col.db.execute("delete from revlog")
        request = {"path": path}
        if choice != "omitted":
            request["with_scheduling"] = choice
        response = client.post("/v1/collection:import", json=request)
        assert response.status_code == 200, response.text
        assert response.json()["imported"] == 2
        expected = saved if choice in ("omitted", None) else choice
        states = col.db.all("select type, queue, ivl, reps from cards")
        assert states == ([[2, 2, 21, 5]] * 2 if expected else [[0, 0, 0, 0]] * 2)
        assert col.db.scalar("select count(*) from revlog") == int(expected)
        preferences = client.get("/v1/collection/import-options").json()
        assert preferences["options"]["with_scheduling"] is expected

    def test_discovery_is_read_only_and_reports_backend_support(self, client, col):
        before = col._backend.get_import_anki_package_presets().SerializeToString()
        response = client.get("/v1/collection/import-options")
        assert response.status_code == 200, response.text
        body = response.json()
        presets = col._backend.get_import_anki_package_presets()
        assert presets.SerializeToString() == before
        assert body["options"]["with_scheduling"] is presets.with_scheduling
        supported = "with_deck_configs" in presets.DESCRIPTOR.fields_by_name
        assert body["unsupported_options"] == ([] if supported else ["with_deck_configs"])
        assert body["options"]["with_deck_configs"] == (
            presets.with_deck_configs if supported else None)

    @pytest.mark.parametrize("choice", ["if_newer", "always", "never"])
    @pytest.mark.parametrize("incoming_newer", [False, True])
    def test_note_update_rule(self, client, col, tmp_path, choice, incoming_newer):
        seed(client)
        path = str(tmp_path / "updates.apkg")
        assert client.post("/v1/collection:export", json={
            "deck": "JP", "path": path}).status_code == 200
        col.db.execute("update notes set flds='local' || char(31) || 'back', mod=mod+?",
                       -100 if incoming_newer else 100)
        response = client.post("/v1/collection:import", json={
            "path": path, "update_notes": choice,
        })
        assert response.status_code == 200, response.text
        updated = choice == "always" or (choice == "if_newer" and incoming_newer)
        assert response.json()["updated"] == (2 if updated else 0)
        fields = {col.get_note(nid)["Front"] for nid in col.find_notes("")}
        assert fields == ({"犬", "猫"} if updated else {"local"})
        assert client.get("/v1/collection/import-options").json()["options"]["update_notes"] == choice

    @pytest.mark.parametrize("choice", ["if_newer", "always", "never"])
    @pytest.mark.parametrize("incoming_newer", [False, True])
    def test_notetype_update_rule(self, client, col, tmp_path, choice, incoming_newer):
        seed(client)
        model = col.models.by_name("Basic")
        original_css = model["css"]
        original_mod = model["mod"]
        path = str(tmp_path / "models.apkg")
        assert client.post("/v1/collection:export", json={
            "deck": "JP", "path": path}).status_code == 200
        model["css"] = "/* local */"
        col.models.update_dict(model)
        col.db.execute("update notetypes set mtime_secs=? where id=?",
                       original_mod + (-100 if incoming_newer else 100), model["id"])
        col.models._cache.clear()
        response = client.post("/v1/collection:import", json={
            "path": path, "update_notetypes": choice,
        })
        assert response.status_code == 200, response.text
        col.models._cache.clear()
        updated = choice == "always" or (choice == "if_newer" and incoming_newer)
        assert col.models.by_name("Basic")["css"] == (original_css if updated else "/* local */")

    @pytest.mark.parametrize("choice", [False, True])
    def test_deck_preset_choice_or_unsupported_error(self, client, col, tmp_path, choice):
        seed(client)
        deck = col.decks.by_name("JP")
        config = col.decks.add_config("Package preset")
        config["new"]["perDay"] = 7
        col.decks.update_config(config)
        deck["conf"] = config["id"]
        col.decks.update_dict(deck)
        path = str(tmp_path / "presets.apkg")
        # The compatibility exporter includes deck presets on all tested versions.
        assert rpc(client, "exportPackage", {
            "deck": "JP", "path": path, "includeSched": True})["error"] is None
        col.decks.remove_config(config["id"])
        default_config = col.decks.get_config(1)
        default_config["new"]["perDay"] = 42
        col.decks.update_config(default_config)
        supported = "with_deck_configs" in col._backend.get_import_anki_package_presets().DESCRIPTOR.fields_by_name
        response = client.post("/v1/collection:import", json={
            "path": path, "with_deck_configs": choice, "with_scheduling": True,
        })
        if not supported:
            assert response.status_code == 400, response.text
            assert "with_deck_configs" in response.text
            assert col.decks.config_dict_for_deck_id(deck["id"])["new"]["perDay"] == 42
        else:
            assert response.status_code == 200, response.text
            assert col.decks.config_dict_for_deck_id(deck["id"])["new"]["perDay"] == (7 if choice else 42)

    @pytest.mark.parametrize("name,value", [
        ("with_scheduling", []), ("with_deck_configs", {}),
        ("merge_notetypes", "invalid"), ("update_notes", "sometimes"),
        ("update_notetypes", 1),
        ("with_schedulng", True),
    ])
    def test_invalid_choices_rejected_before_import(self, client, col, name, value):
        before = col._backend.get_import_anki_package_presets().SerializeToString()
        response = client.post("/v1/collection:import", json={
            "path": "/missing/invalid.apkg", name: value,
        })
        assert response.status_code == 422, response.text
        assert col._backend.get_import_anki_package_presets().SerializeToString() == before

    def test_partial_override_preserves_other_saved_choices(self, client, col, tmp_path):
        path = self.package(client, col, tmp_path)
        choices = {
            "with_scheduling": False, "merge_notetypes": True,
            "update_notes": "never", "update_notetypes": "never",
        }
        response = client.post("/v1/collection:import", json={"path": path, **choices})
        assert response.status_code == 200, response.text
        before = client.get("/v1/collection/import-options").json()["options"]
        response = client.post("/v1/collection:import", json={
            "path": path, "with_scheduling": True,
        })
        assert response.status_code == 200, response.text
        after = client.get("/v1/collection/import-options").json()["options"]
        assert after == {**before, "with_scheduling": True}

    def test_failed_import_does_not_save_choices(self, client, col, tmp_path):
        before = col._backend.get_import_anki_package_presets().SerializeToString()
        response = client.post("/v1/collection:import", json={
            "path": str(tmp_path / "missing.apkg"), "with_scheduling": True,
            "merge_notetypes": True, "update_notes": "never",
        })
        assert response.status_code != 200
        assert col._backend.get_import_anki_package_presets().SerializeToString() == before

    @pytest.mark.parametrize("merge", [False, True])
    def test_merging_diverged_notetypes(self, client, col, tmp_path, merge):
        seed(client)
        model = col.models.by_name("Basic")
        col.models.add_field(model, col.models.new_field("Incoming"))
        col.models.update_dict(model)
        path = str(tmp_path / "merge.apkg")
        assert client.post("/v1/collection:export", json={
            "deck": "JP", "path": path}).status_code == 200
        col.models.remove_field(model, model["flds"][-1])
        col.models.add_field(model, col.models.new_field("Local"))
        col.models.update_dict(model)
        response = client.post("/v1/collection:import", json={
            "path": path, "merge_notetypes": merge, "update_notetypes": "always",
        })
        assert response.status_code == 200, response.text
        col.models._cache.clear()
        fields = {field["name"] for field in col.models.get(model["id"])["flds"]}
        assert fields == ({"Front", "Back", "Incoming", "Local"} if merge
                          else {"Front", "Back", "Local"})

    def test_import_changes_and_undo(self, client, col, tmp_path):
        from tsunagi.adapters.anki.collection import import_package

        path = self.package(client, col, tmp_path)
        result = import_package.__wrapped__(col, path, with_scheduling=True)
        assert result.changes.note
        assert result.changes.card
        assert col.note_count() == 2
        col.undo()
        assert col.note_count() == 0
        col.redo()
        assert col.note_count() == 2

    def test_openapi_exposes_choices(self, client):
        schema = client.get("/openapi.json").json()
        assert "get" in schema["paths"]["/v1/collection/import-options"]
        props = schema["components"]["schemas"]["ImportRequest"]["properties"]
        assert {"path", "with_scheduling", "with_deck_configs", "merge_notetypes",
                "update_notes", "update_notetypes"} <= props.keys()
        assert all(props[name]["nullable"] for name in props if name != "path")
