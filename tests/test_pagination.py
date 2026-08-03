from tsunagi.shared.pagination import decode_cursor, encode_cursor, paginate_keyset

ROWS = [{"id": i} for i in range(1, 11)]  # ids 1..10
KEY = lambda r: r["id"]  # noqa: E731


class TestCursor:
    def test_round_trip(self):
        assert decode_cursor(encode_cursor({"last_key": 42})) == {"last_key": 42}

    def test_none_and_garbage_are_empty(self):
        assert decode_cursor(None) == {}
        assert decode_cursor("") == {}
        assert decode_cursor("!!!not-base64!!!") == {}


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

    def test_bad_cursor_restarts(self):
        page, _ = paginate_keyset(ROWS, 2, "garbage", key_fn=KEY)
        assert [r["id"] for r in page] == [1, 2]

    def test_limit_floor_is_one(self):
        page, _ = paginate_keyset(ROWS, 0, None, key_fn=KEY)
        assert len(page) == 1
