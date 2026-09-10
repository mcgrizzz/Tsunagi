import base64
import json

import pytest

from tsunagi.shared.pagination import decode_cursor, encode_cursor, paginate_keyset

ROWS = [{"id": i} for i in range(1, 11)]  # ids 1..10
KEY = lambda r: r["id"]  # noqa: E731


class TestCursor:
    def test_round_trip(self):
        assert decode_cursor(encode_cursor({"last_key": 42})) == {"last_key": 42}

    def test_missing_cursor_starts_at_first_page(self):
        assert decode_cursor(None) == {}

    @pytest.mark.parametrize("cursor", ["", "!!!not-base64!!!", "not-json", "é", "e30=\n", "e30=!"])
    def test_malformed_cursor_is_rejected(self, cursor):
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            decode_cursor(cursor)

    @pytest.mark.parametrize("state", [
        None, [], 42, "text", {}, {"last_key": None}, {"last_key": True},
        {"last_key": 1.5}, {"last_key": "42"}, {"last_key": []},
        {"last_key": -1}, {"last_key": 2**63}, {"last_key": 1, "extra": 2},
    ])
    def test_invalid_id_state_is_rejected(self, state):
        cursor = base64.urlsafe_b64encode(json.dumps(state).encode()).decode()
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            decode_cursor(cursor)

    @pytest.mark.parametrize("key", [0, 2**63 - 1])
    def test_valid_id_bounds(self, key):
        assert decode_cursor(encode_cursor({"last_key": key})) == {"last_key": key}

    def test_filename_cursor_keeps_unicode(self):
        state = {"last_key": "日本語 🎵.mp3"}
        assert decode_cursor(encode_cursor(state), key_type=str) == state

    @pytest.mark.parametrize("key", ["", 1, None, True])
    def test_invalid_filename_key(self, key):
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            decode_cursor(encode_cursor({"last_key": key}), key_type=str)


class TestPaginateKeyset:
    def test_first_page(self):
        page, cur = paginate_keyset(ROWS, 3, None, key_fn=KEY)
        assert [r["id"] for r in page] == [1, 2, 3]
        assert cur is not None

    def test_walk_all_pages(self):
        seen, cur = [], None
        for _ in range(10):
            page, cur = paginate_keyset(ROWS, 4, cur, key_fn=KEY)
            seen += [r["id"] for r in page]
            if cur is None:
                break
        assert seen == list(range(1, 11))

    def test_exact_limit_has_no_cursor(self):
        page, cur = paginate_keyset(ROWS, 10, None, key_fn=KEY)
        assert len(page) == 10
        assert cur is None

    def test_skips_keys_at_or_below_last(self):
        cur = encode_cursor({"last_key": 8})
        page, nxt = paginate_keyset(ROWS, 5, cur, key_fn=KEY)
        assert [r["id"] for r in page] == [9, 10]
        assert nxt is None

    def test_bad_cursor_is_rejected_even_for_empty_results(self):
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            paginate_keyset([], 2, "garbage", key_fn=KEY)

    def test_limit_floor_is_one(self):
        page, _ = paginate_keyset(ROWS, 0, None, key_fn=KEY)
        assert len(page) == 1
