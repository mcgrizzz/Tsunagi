"""Public upload batches: partial failures, bounded dispatch and profile isolation."""
import base64
from pathlib import Path

import pytest

from tsunagi.adapters.anki import media_batches


def upload(name="file.png", data=b"image"):
    return {"filename": name, "data": base64.b64encode(data).decode()}


def create(client, body):
    response = client.post("/v1/media", json=body)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("as_array", [False, True])
def test_one_upload_has_the_same_envelope(client, col, as_array):
    body = upload()
    result = create(client, [body] if as_array else body)
    assert result == {"created": [{"index": 0, "filename": "file.png",
                                  "requested_filename": "file.png", "renamed": False,
                                  "size": 5}], "failed": []}
    assert Path(col.media.dir(), "file.png").read_bytes() == b"image"


def test_empty_array_does_not_dispatch(client, monkeypatch):
    def unexpected(*args):
        pytest.fail("No files to store")
    monkeypatch.setattr(media_batches, "query_op_call", unexpected)
    assert create(client, []) == {"created": [], "failed": []}


def test_partial_failures_and_collision_names_preserve_input_indexes(client, col, monkeypatch):
    original = col.media.write_data
    def write_data(name, data):
        if name == "unwritable.png":
            raise OSError("disk failure")
        return original(name, data)
    monkeypatch.setattr(col.media, "write_data", write_data)
    result = create(client, [upload(), upload("../bad"),
                             {"filename": "bad.png", "data": "!"},
                             upload(data=b"different"), upload("unwritable.png"),
                             upload("last.png")])
    assert [item["index"] for item in result["created"]] == [0, 3, 5]
    assert [item["index"] for item in result["failed"]] == [1, 2, 4]
    assert [item["code"] for item in result["failed"]] == [
        "invalid_media", "invalid_media", "storage_error"]
    second = result["created"][1]
    assert second["renamed"] is True
    assert second["filename"] != second["requested_filename"] == "file.png"
    for item, expected in zip(result["created"], [b"image", b"different", b"image"]):
        assert Path(col.media.dir(), item["filename"]).read_bytes() == expected


@pytest.mark.parametrize("file_bound,byte_bound,expected_sizes", [
    (2, 100, [2, 2, 1]), (64, 8, [1, 1, 1, 1, 1]), (64, 4, [1, 1, 1, 1, 1]),
])
def test_internal_chunks_bound_work_without_limiting_request(client, monkeypatch,
                                                           file_bound, byte_bound, expected_sizes):
    monkeypatch.setattr(media_batches, "UPLOAD_CHUNK_FILES", file_bound)
    monkeypatch.setattr(media_batches, "UPLOAD_CHUNK_BYTES", byte_bound)
    original = media_batches.query_op_call
    sizes = []
    def dispatch(fn, expected, items):
        sizes.append(len(items))
        return original(fn, expected, items)
    monkeypatch.setattr(media_batches, "query_op_call", dispatch)
    result = create(client, [upload(f"{i}.png") for i in range(5)])
    assert result["failed"] == []
    assert len(result["created"]) == 5
    assert sizes == expected_sizes


def test_later_external_source_can_read_earlier_upload_off_collection_thread(client, col, monkeypatch):
    inside_dispatch = False
    original = media_batches.query_op_call
    def dispatch(*args):
        nonlocal inside_dispatch
        inside_dispatch = True
        try:
            return original(*args)
        finally:
            inside_dispatch = False
    def fetch(url):
        assert not inside_dispatch
        return Path(col.media.dir(), "file.png").read_bytes()
    monkeypatch.setattr(media_batches, "query_op_call", dispatch)
    monkeypatch.setattr("tsunagi.http.v1.media._fetch_url", fetch)
    result = create(client, [upload(), {"url": "https://example.test/copy.png"}])
    assert result["failed"] == []
    assert [item["filename"] for item in result["created"]] == ["file.png", "copy.png"]
    assert Path(col.media.dir(), "copy.png").read_bytes() == b"image"


def test_profile_switch_during_download_cannot_store_in_another_collection(client, col, monkeypatch):
    def fetch(url):
        monkeypatch.setattr(media_batches.mw, "col", object())
        return b"image"
    monkeypatch.setattr("tsunagi.http.v1.media._fetch_url", fetch)
    response = client.post("/v1/media", json={"url": "https://example.test/file.png"})
    assert response.status_code == 503, response.text
    assert not col.media.have("file.png")


def test_malformed_array_is_rejected_before_storing(client, col):
    response = client.post("/v1/media", json=[upload(), 123])
    assert response.status_code == 422
    assert not col.media.have("file.png")
