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
