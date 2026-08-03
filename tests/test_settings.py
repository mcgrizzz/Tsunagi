from tsunagi.adapters.settings import Settings


class TestSettings:
    def test_update_merges_and_persists_full_dict(self):
        seen = []
        s = Settings({"a": 1}, persist=seen.append)
        s.update(b=2)
        assert s.get("a") == 1
        assert s.get("b") == 2
        assert seen == [{"a": 1, "b": 2}]

    def test_update_without_persist_does_not_crash(self):
        s = Settings({"a": 1})
        s.update(a=2)
        assert s.get("a") == 2

    def test_add_cors_origin_appends_once(self):
        seen = []
        s = Settings({"cors_allowlist": []}, persist=seen.append)
        s.add_cors_origin("https://x.test")
        s.add_cors_origin("https://x.test")
        assert s.get("cors_allowlist") == ["https://x.test"]
        assert len(seen) == 1  # second call is a no-op, nothing re-persisted

    def test_configure_replaces_values_keeps_identity(self):
        s = Settings({"api_key": ""})
        ref = s
        seen = []
        s.configure({"api_key": "k"}, persist=seen.append)
        assert ref is s
        assert ref.get("api_key") == "k"
        s.update(x=1)
        assert seen  # new persist callback active

    def test_is_origin_allowed(self):
        s = Settings({"cors_allowlist": ["https://a.test"]})
        assert s.is_origin_allowed("https://a.test")
        assert not s.is_origin_allowed("https://b.test")
        s.update(cors_allowlist=["*"])
        assert s.is_origin_allowed("https://anything.test")

    def test_snapshot_is_a_copy(self):
        s = Settings({"a": 1})
        snap = s.snapshot()
        snap["a"] = 99
        assert s.get("a") == 1
