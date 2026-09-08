"""HTTP boundary regressions that also run without the upstream checkout."""

import pytest


def test_empty_post_discovers_ankiconnect_version(client):
    response = client.post("/", content=b"")
    assert response.status_code == 200
    assert response.json() == {"apiVersion": "AnkiConnect v.6"}


@pytest.mark.parametrize("content,error", [
    (b" ", "Expecting value: line 1 column 2 (char 1)"),
    (b'{"action":', "Expecting value: line 1 column 11 (char 10)"),
    (b'\xef\xbb\xbf{}', "Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)"),
    (b"\xff", "'utf-8' codec can't decode byte 0xff in position 0: invalid start byte"),
])
def test_decode_errors_use_upstream_diagnostics(client, content, error):
    response = client.post("/", content=content)
    assert response.status_code == 200
    assert response.json() == {"result": None, "error": error}


@pytest.mark.parametrize("content", [
    b"", b"{not json", b'{"action":"requestPermission","params":null}',
])
def test_invalid_body_cannot_bypass_origin_gate(client, content):
    response = client.post("/", content=content, headers={"Origin": "https://denied.test"})
    assert response.status_code == 403
    assert response.content == b""


@pytest.mark.parametrize("content_type", ["application/json", "text/plain"])
def test_rpc_decoding_ignores_content_type_charset(client, content_type):
    response = client.post(
        "/", content=b'{"action":"version","version":6}',
        headers={"Content-Type": content_type + "; charset=utf-16"},
    )
    assert response.status_code == 200
    assert response.json() == {"result": 6, "error": None}


def test_native_root_get_still_redirects_to_documentation(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"
