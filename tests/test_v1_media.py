"""
Full-app tests for /v1/media over a real temp media directory.
"""
import base64
import os

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image data"
B64 = base64.b64encode(PNG).decode()


def seed(fake_col, name, data=b"x"):
    with open(os.path.join(fake_col.media.dir(), name), "wb") as fh:
        fh.write(data)


class TestList:
    def test_empty(self, client):
        assert client.get("/v1/media").json()["items"] == []

    def test_sorted_with_metadata(self, client, fake_col):
        seed(fake_col, "b.mp3", b"aa")
        seed(fake_col, "a.png", b"bbb")
        items = client.get("/v1/media").json()["items"]
        assert [i["filename"] for i in items] == ["a.png", "b.mp3"]
        assert items[0]["size"] == 3
        assert items[0]["mtime"] > 0

    def test_prefix_and_suffix_filters(self, client, fake_col):
        for name in ("dog.png", "dog.mp3", "cat.png"):
            seed(fake_col, name)
        assert [i["filename"] for i in client.get(
            "/v1/media", params={"prefix": "dog"}).json()["items"]] == ["dog.mp3", "dog.png"]
        assert [i["filename"] for i in client.get(
            "/v1/media", params={"suffix": ".png"}).json()["items"]] == ["cat.png", "dog.png"]

    def test_cursor_walks_every_file(self, client, fake_col):
        for name in ("a.png", "b.png", "c.png"):
            seed(fake_col, name)
        seen, cursor = [], None
        while True:
            params = {"limit": 1}
            if cursor:
                params["cursor"] = cursor
            body = client.get("/v1/media", params=params).json()
            seen += [i["filename"] for i in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert seen == ["a.png", "b.png", "c.png"]


class TestDownload:
    def test_raw_bytes_and_content_type(self, client, fake_col):
        seed(fake_col, "dog.png", PNG)
        resp = client.get("/v1/media/dog.png")
        assert resp.status_code == 200
        assert resp.content == PNG
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["content-disposition"].startswith("inline")

    def test_audio_content_type(self, client, fake_col):
        seed(fake_col, "word.mp3", b"id3")
        assert client.get("/v1/media/word.mp3").headers["content-type"] == "audio/mpeg"

    def test_unknown_extension_is_octet_stream(self, client, fake_col):
        seed(fake_col, "blob.zzz", b"x")
        assert client.get("/v1/media/blob.zzz").headers["content-type"] == "application/octet-stream"

    def test_missing_is_404(self, client):
        assert client.get("/v1/media/nope.png").status_code == 404


class TestUpload:
    def test_base64_upload(self, client, fake_col):
        resp = client.post("/v1/media", json={"filename": "dog.png", "data": B64})
        assert resp.status_code == 201
        body = resp.json()
        assert body == {"filename": "dog.png", "requested_filename": "dog.png",
                        "renamed": False, "size": len(PNG)}
        assert fake_col.media.have("dog.png")

    def test_identical_content_keeps_name(self, client):
        client.post("/v1/media", json={"filename": "dog.png", "data": B64})
        body = client.post("/v1/media", json={"filename": "dog.png", "data": B64}).json()
        assert body["filename"] == "dog.png"
        assert body["renamed"] is False

    def test_collision_with_different_bytes_is_renamed(self, client):
        client.post("/v1/media", json={"filename": "dog.png", "data": B64})
        other = base64.b64encode(b"different bytes entirely").decode()
        body = client.post("/v1/media", json={"filename": "dog.png", "data": other}).json()
        assert body["renamed"] is True
        assert body["filename"] != "dog.png"
        assert body["requested_filename"] == "dog.png"

    def test_requires_exactly_one_source(self, client):
        assert client.post("/v1/media", json={"filename": "a.png"}).status_code == 400
        assert client.post("/v1/media", json={
            "filename": "a.png", "data": B64, "url": "http://x/y.png"}).status_code == 400

    def test_data_requires_filename(self, client):
        assert client.post("/v1/media", json={"data": B64}).status_code == 400

    def test_invalid_base64_is_400(self, client):
        assert client.post("/v1/media", json={
            "filename": "a.png", "data": "not base64!!"}).status_code == 400

    def test_oversize_is_400(self, client, reset_settings):
        reset_settings.update(media_max_bytes=4)
        assert client.post("/v1/media", json={
            "filename": "a.png", "data": B64}).status_code == 400

    def test_local_path_disabled_by_default(self, client, tmp_path):
        f = tmp_path / "local.png"
        f.write_bytes(PNG)
        resp = client.post("/v1/media", json={"path": str(f)})
        assert resp.status_code == 400
        assert "media_allow_local_path" in resp.json()["detail"]

    def test_local_path_when_enabled(self, client, reset_settings, tmp_path):
        reset_settings.update(media_allow_local_path=True)
        f = tmp_path / "local.png"
        f.write_bytes(PNG)
        body = client.post("/v1/media", json={"path": str(f)}).json()
        assert body["filename"] == "local.png"

    def test_url_upload(self, client, monkeypatch):
        monkeypatch.setattr("tsunagi.http.v1.media._fetch_url", lambda url: PNG)
        body = client.post("/v1/media", json={"url": "https://x.test/dog.png"}).json()
        assert body["filename"] == "dog.png"

    def test_non_http_url_rejected(self):
        from tsunagi.http.v1.media import _fetch_url
        from tsunagi.shared.errors import ValidationError
        with pytest.raises(ValidationError):
            _fetch_url("file:///etc/passwd")


class TestDelete:
    def test_delete(self, client, fake_col):
        seed(fake_col, "dog.png", PNG)
        assert client.delete("/v1/media/dog.png").json()["success"] is True
        assert not fake_col.media.have("dog.png")

    def test_delete_missing_is_404(self, client):
        assert client.delete("/v1/media/nope.png").status_code == 404


class TestFilenameSecurity:
    # Names with no path separator: these route, so our validation must reject
    BAD_NAMES = ["..", "a\x00b", "CON", "con.png", "a:b", "x" * 300, " lead.png"]

    @pytest.mark.parametrize("name", BAD_NAMES)
    def test_rejected_on_upload(self, client, name):
        assert client.post("/v1/media", json={"filename": name, "data": B64}).status_code == 400

    @pytest.mark.parametrize("name", ["..", "CON", "a:b"])
    def test_rejected_on_download(self, client, name):
        assert client.get(f"/v1/media/{name}").status_code in (400, 404)

    @pytest.mark.parametrize("name", ["../secret", "..\\secret", "a/b", "/etc/passwd", "C:\\x"])
    def test_traversal_rejected_on_upload(self, client, name):
        assert client.post("/v1/media", json={"filename": name, "data": B64}).status_code == 400

    def test_symlink_escape_rejected(self, client, fake_col, tmp_path):
        # Name-level rules can't catch a symlink INSIDE the media folder
        # pointing outside it; the realpath containment check must.
        secret = tmp_path / "secret.txt"
        secret.write_text("classified")
        link = os.path.join(fake_col.media.dir(), "innocent.txt")
        try:
            os.symlink(secret, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")
        assert client.get("/v1/media/innocent.txt").status_code == 400
