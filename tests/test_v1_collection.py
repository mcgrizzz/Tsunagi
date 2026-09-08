"""
Collection-level routes and their AnkiConnect aliases.

Only the parts that are honestly testable without a Qt main window: the
export/import round trip, reload, and getActiveProfile (the fake aqt.mw
carries a profile name because notesInfo reports it). GET /v1/profiles needs
mw.pm.profiles(), and profile switching and sync need a live main window, so
those are manual-checklist territory.
"""


def rpc(client, action, params=None, version=6):
    body = {"action": action, "version": version}
    if params is not None:
        body["params"] = params
    return client.post("/", json=body).json()


def add_note(client, front, deck="JP"):
    return client.post("/v1/notes", json={
        "modelName": "Basic", "deckName": deck,
        "fields": {"Front": front, "Back": "x"}}).json()["result"]


def seed(client):
    client.post("/v1/decks", json={"name": "JP"})
    add_note(client, "犬")
    add_note(client, "猫")


class TestExportImportRoundTrip:
    """
    The real test of both endpoints: export a deck, destroy it, import it back
    and check the notes returned. Also covers the version split - Anki changed
    export_anki_package's signature between 23.10 and current.
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
        disabled = client.get("/v1/capabilities").json()["fsrs"]
        assert disabled["supported"] is True
        assert disabled["enabled"] is False
        col.set_config("fsrs", True)
        enabled = client.get("/v1/capabilities").json()["fsrs"]
        assert enabled["enabled"] is True
        assert disabled["operations"] == enabled["operations"]
        assert client.get("/v1/collection").json()["fsrs"] is True

    def test_actual_backend_support_and_legacy_options(self, client):
        from anki.buildinfo import version

        legacy = version.startswith("23.10")
        operations = client.get("/v1/capabilities").json()["fsrs"]["operations"]
        assert operations["compute_params"]["available"] is True
        assert operations["evaluate_params"]["available"] is True
        assert operations["compute_params"]["unsupported_options"] == (
            ["current_params", "ignore_revlogs_before_ms", "num_of_relearning_steps", "health_check"]
            if legacy else []
        )
        assert operations["evaluate_params"]["unsupported_options"] == (
            ["ignore_revlogs_before_ms"] if legacy else []
        )
        for name in ("simulate", "simulate_workload", "optimal_retention"):
            assert operations[name]["available"] is not legacy

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

        def forbidden(*args, **kwargs):
            raise AssertionError("Discovery invoked a backend computation")

        assert capabilities(SimpleNamespace())["supported"] is False
        backend = SimpleNamespace(compute_optimal_retention=forbidden)
        assert capabilities(backend)["operations"]["optimal_retention"]["available"] is False
        backend.simulate_fsrs_review = forbidden
        result = capabilities(backend)
        assert result["supported"] is True
        assert result["operations"]["optimal_retention"]["available"] is True
        assert result["operations"]["simulate_workload"]["available"] is False
