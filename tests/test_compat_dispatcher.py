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
        assert body == {"permission": "granted", "requireApiKey": False, "version": 6}


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


class TestRegistry:
    def test_duplicate_registration_raises(self):
        with pytest.raises(ValueError):
            @registry.register("version")
            def _dup(params):
                pass

    def test_tier1_manifest_complete(self):
        assert TIER1 <= set(get_available_actions()["actions"])
