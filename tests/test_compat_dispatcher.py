"""
Golden tests for AnkiConnect dispatcher semantics, verified against
AnkiConnect's actual source: version default 4 = bare results, errors always
enveloped, multi re-dispatches raw sub-requests with per-sub version/key.

Runs over the real full app (aqt fakes from conftest).
"""
import pytest

from tsunagi.adapters.config import DEFAULTS
from tsunagi.http.compat import actions  # noqa: F401  (ensure handlers are registered)
from tsunagi.http.compat.ankiconnect import API_KEY_ERROR, get_available_actions
from tsunagi.http.compat.errors import UNSUPPORTED_ACTION
from tsunagi.http.compat.registry import registry

TIER1 = {
    "version", "requestPermission", "multi",
    "deckNames", "deckNamesAndIds", "createDeck",
    "modelNames", "modelNamesAndIds", "modelFieldNames",
    "findModelsByName", "findModelsById",
    # M4: notes, media, gui
    "addNote", "addNotes", "canAddNotes", "canAddNotesWithErrorDetail",
    "updateNoteFields", "notesInfo", "findNotes", "deleteNotes",
    "storeMediaFile", "retrieveMediaFile", "getMediaFilesNames", "deleteMediaFile",
    "guiBrowse",
}


class TestVersionSemantics:
    def test_version_omitted_is_bare(self, client):
        # AnkiConnect defaults version to 4 -> bare result (what Yomitan relies on)
        assert client.post("/", json={"action": "version"}).json() == 6

    def test_version_4_is_bare(self, client):
        assert client.post("/", json={"action": "version", "version": 4}).json() == 6

    def test_version_5_is_enveloped(self, client):
        assert client.post("/", json={"action": "version", "version": 5}).json() == \
            {"result": 6, "error": None}

    def test_version_6_is_enveloped(self, client):
        assert client.post("/", json={"action": "version", "version": 6}).json() == \
            {"result": 6, "error": None}

    def test_request_permission_bare_at_v4(self, client):
        body = client.post("/", json={"action": "requestPermission"}).json()
        assert body == {"permission": "granted", "requireApikey": False, "version": 6}


class TestErrors:
    def test_unknown_action_exact_string(self, client):
        body = client.post("/", json={"action": "nopeNope", "version": 6}).json()
        assert body == {"result": None, "error": UNSUPPORTED_ACTION}

    def test_unknown_action_enveloped_even_at_v4(self, client):
        # Errors ignore version (format_exception_reply discards it)
        body = client.post("/", json={"action": "nopeNope"}).json()
        assert body == {"result": None, "error": UNSUPPORTED_ACTION}

    def test_key_error_enveloped_at_v4(self, client, reset_settings):
        reset_settings.configure({**DEFAULTS, "api_key": "k"}, persist=None)
        body = client.post("/", json={"action": "version"}).json()
        assert body == {"result": None, "error": API_KEY_ERROR}

    def test_param_validation_error_names_the_field(self, client):
        body = client.post("/", json={"action": "modelFieldNames", "version": 6,
                                      "params": {}}).json()
        assert body["result"] is None
        assert "modelName" in body["error"]
        assert "field required" in body["error"]


class TestMulti:
    def test_versionless_subs_are_bare_inside_outer_envelope(self, client, fake_col):
        body = client.post("/", json={
            "action": "multi", "version": 6,
            "params": {"actions": [{"action": "version"}, {"action": "deckNames"}]},
        }).json()
        assert body == {"result": [6, ["Default"]], "error": None}

    def test_sub_version_override(self, client):
        body = client.post("/", json={
            "action": "multi", "version": 6,
            "params": {"actions": [{"action": "version", "version": 6}]},
        }).json()
        assert body == {"result": [{"result": 6, "error": None}], "error": None}

    def test_one_failure_does_not_abort(self, client):
        body = client.post("/", json={
            "action": "multi", "version": 6,
            "params": {"actions": [{"action": "nopeNope"}, {"action": "version"}]},
        }).json()
        assert body["result"] == [{"result": None, "error": UNSUPPORTED_ACTION}, 6]

    def test_key_checked_per_sub_action(self, client, reset_settings):
        reset_settings.configure({**DEFAULTS, "api_key": "k"}, persist=None)
        body = client.post("/", json={
            "action": "multi", "version": 6, "key": "k",
            "params": {"actions": [
                {"action": "version"},               # no key -> per-sub error
                {"action": "version", "key": "k"},   # keyed -> bare 6
            ]},
        }).json()
        assert body["result"] == [{"result": None, "error": API_KEY_ERROR}, 6]

    def test_nested_multi(self, client):
        body = client.post("/", json={
            "action": "multi", "version": 6,
            "params": {"actions": [
                {"action": "multi", "params": {"actions": [{"action": "version"}]}},
            ]},
        }).json()
        # inner multi is version-less -> bare list of its (bare) sub-results
        assert body == {"result": [[6]], "error": None}

    def test_actions_must_be_a_list(self, client):
        body = client.post("/", json={"action": "multi", "version": 6,
                                      "params": {"actions": "nope"}}).json()
        assert body["result"] is None
        assert body["error"]


class TestBrowserOrigins:
    """
    Regression: Yomitan never calls requestPermission - it goes straight to
    deckNames with version 2 from a chrome-extension:// origin. With
    AnkiConnect's default allowlist that must just work.
    """

    YOMITAN = "chrome-extension://likgccmbimhjbgkjambclfkhldnlhbnn"

    def test_extension_origin_works_out_of_the_box(self, client, fake_col):
        resp = client.post("/", json={"action": "deckNames", "version": 2},
                           headers={"Origin": self.YOMITAN})
        assert resp.status_code == 200
        assert resp.json() == ["Default"]  # version 2 -> bare result

    def test_unknown_web_origin_is_403(self, client, reset_settings):
        resp = client.post("/", json={"action": "version"},
                           headers={"Origin": "https://evil.test"})
        assert resp.status_code == 403

    def test_unknown_origin_may_still_request_permission(self, client, reset_settings, monkeypatch):
        # The dialog would otherwise need real Qt; assert the request reaches
        # the dispatcher instead of being 403'd at the origin check.
        monkeypatch.setattr(
            "tsunagi.http.compat.ankiconnect._default_ask", lambda origin: False
        )
        reset_settings.configure({**DEFAULTS, "cors_allowlist": []}, persist=None)
        resp = client.post("/", json={"action": "requestPermission", "version": 6},
                           headers={"Origin": "https://site.test"})
        assert resp.status_code == 200
        assert resp.json() == {"result": {"permission": "denied"}, "error": None}


class TestAlwaysEnvelope:
    """
    Regression: AnkiConnect clients check only `error` and then read `result`.
    A FastAPI 422 body ({"detail": ...}) has neither key, so it slips past
    their guard and crashes them on the next property access (asbplayer died
    with "Cannot read properties of undefined (reading 'length')"). Every
    reply from POST / must be an envelope.
    """

    def test_malformed_json_is_an_envelope(self, client):
        resp = client.post("/", content=b"{not json", headers={"Content-Type": "application/json"})
        body = resp.json()
        assert set(body) == {"result", "error"}
        assert body["result"] is None and body["error"]

    def test_non_object_body_is_an_envelope(self, client):
        body = client.post("/", json=[1, 2, 3]).json()
        assert set(body) == {"result", "error"}
        assert body["result"] is None

    def test_missing_action_is_an_envelope(self, client):
        body = client.post("/", json={"version": 6}).json()
        assert body == {"result": None, "error": UNSUPPORTED_ACTION}

    def test_bad_params_shape_is_an_envelope(self, client):
        # Wrong param type would be a 422 if the body were a typed parameter
        body = client.post("/", json={"action": "notesInfo", "version": 6,
                                      "params": {"notes": "not-a-list"}}).json()
        assert set(body) == {"result", "error"}
        assert body["result"] is None and body["error"]


class TestRegistry:
    def test_duplicate_registration_raises(self):
        with pytest.raises(ValueError):
            @registry.register("version")
            def _dup(params):
                pass

    def test_tier1_manifest_complete(self):
        assert TIER1 <= set(get_available_actions()["actions"])
