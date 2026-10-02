"""choose_port's busy check answers what uvicorn's own bind will do."""
import socket

import pytest

from tsunagi.adapters.config import choose_port


def _listener():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    return srv


def test_a_port_with_closed_connections_is_free():
    # A stopped server leaves the connections it closed in TIME_WAIT for about
    # a minute. On Linux and macOS a plain test bind refused the port then, so
    # a reload or a settings restart left Tsunagi down; uvicorn (SO_REUSEADDR)
    # binds it fine.
    srv = _listener()
    port = srv.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = srv.accept()
    conn.close()   # the server's side closes first, as on shutdown
    client.close()
    srv.close()
    assert choose_port({"host": "127.0.0.1", "port": port}) == port


def test_a_port_in_use_is_still_busy():
    srv = _listener()
    try:
        port = srv.getsockname()[1]
        with pytest.raises(RuntimeError, match="busy"):
            choose_port({"host": "127.0.0.1", "port": port})
    finally:
        srv.close()
