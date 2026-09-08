"""Compatibility HTTP downloads and preserved native/resource-limit behavior."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from tsunagi.http.v1.media import _fetch_url


@pytest.fixture
def download_url():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, length = self.path.strip("/").split("/")
            self.send_response(int(status))
            if length == "declared":
                self.send_header("Content-Length", "7")
            self.end_headers()
            self.wfile.write(b"payload")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("status", [201, 202, 204, 206, 404, 500])
def test_failed_download_keeps_existing_file(client, col, download_url, status):
    col.media.write_data("existing.mp3", b"original")
    url = f"{download_url}/{status}/declared"
    response = client.post("/", json={"action": "storeMediaFile", "version": 6, "params": {
        "filename": "existing.mp3", "url": url,
    }})
    assert response.json() == {"result": None, "error": f"{url} download failed with return code {status}"}
    assert (Path(col.media.dir()) / "existing.mp3").read_bytes() == b"original"


@pytest.mark.parametrize("length", ["declared", "undeclared"])
def test_compat_download_retains_size_limit(client, col, reset_settings, download_url, length):
    reset_settings.update(media_max_bytes=4)
    col.media.write_data("limited.mp3", b"original")
    response = client.post("/", json={"action": "storeMediaFile", "version": 6, "params": {
        "filename": "limited.mp3", "url": f"{download_url}/200/{length}",
    }})
    assert response.json() == {"result": None, "error": "file exceeds media_max_bytes (4)"}
    assert (Path(col.media.dir()) / "limited.mp3").read_bytes() == b"original"


def test_native_download_still_accepts_201(download_url):
    assert _fetch_url(download_url + "/201/declared") == b"payload"
