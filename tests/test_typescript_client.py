"""The TypeScript client (packages/typescript) against the real server: the
client moves with the API. Skips unless Node and the built client are here
(CI's client job builds it); `npm test` there checks the client on its own."""
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn

from tsunagi.adapters.events import broker

CLIENT = Path(__file__).resolve().parents[1] / "packages" / "typescript"


@pytest.mark.skipif(not shutil.which("node") or not (CLIENT / "dist" / "index.js").exists(),
                    reason="needs Node and the built client (npm ci && npm run build in packages/typescript)")
def test_the_client_works_against_the_server(col, reset_settings, monkeypatch, tmp_path):
    import aqt

    from tsunagi.app import app
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(aqt.mw, "pm", SimpleNamespace(name="Client"), raising=False)
    broker.start_session(col)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    node = subprocess.Popen(["node", str(CLIENT / "test" / "live.mjs"), f"http://127.0.0.1:{port}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        lines = []
        for line in node.stdout:
            lines.append(line)
            if line.strip() == "WATCHING":
                # The script's access watch is live: change this app's role.
                reset_settings.update(no_key_local_role="everything")
        assert node.wait(timeout=60) == 0, "".join(lines)
        assert "LIVE OK\n" in lines
    finally:
        node.kill()
        server.should_exit = True
        broker.begin_drain()
        thread.join(5)
