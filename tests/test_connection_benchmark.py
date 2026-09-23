"""Real sockets verify the benchmark's failure accounting, not server speed."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from tools.connection_bench import (
    Endpoint,
    abandon,
    burst,
    exchange,
    ids_digest,
    stalled_upload,
    validate_ids,
    wire_request,
)


@asynccontextmanager
async def server(handler):
    active = set()

    async def serve(reader, writer):
        active.add(asyncio.current_task())
        try:
            await reader.readuntil(b"\r\n\r\n")
            await handler(reader, writer)
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            active.remove(asyncio.current_task())

    listener = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with listener:
        try:
            yield Endpoint.parse(f"http://127.0.0.1:{listener.sockets[0].getsockname()[1]}")
        finally:
            tasks = list(active)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def response(payload):
    body = json.dumps(payload).encode()
    return f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body


@pytest.mark.parametrize(("raw", "expected"), [
    (response({"result": [1, 2], "error": None}), "ok"),
    (response({"result": [1], "error": None}), "invalid_response"),
    (response({"result": None, "error": "busy"}), "api_error"),
    (b"HTTP/1.1 503 Service Unavailable\r\n\r\n", "http_error"),
    (b"", "closed_without_response"),
    (b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{}", "truncated_response"),
])
def test_outcomes_include_complete_response_validation(raw, expected):
    async def scenario():
        async def handler(reader, writer):
            writer.write(raw)
            await writer.drain()

        async with server(handler) as endpoint:
            result = await exchange(endpoint, wire_request(endpoint, "/"), 1,
                                    lambda data: validate_ids(data, False, ids_digest([2, 1])))
            assert result["outcome"] == expected
            if expected == "http_error":
                assert result["http_status"] == 503
            if expected == "closed_without_response":
                assert result["response_bytes"] == 0

    asyncio.run(scenario())


def test_deadline_and_simultaneous_burst():
    async def scenario():
        async def stalled(reader, writer):
            await reader.read()

        async with server(stalled) as endpoint:
            result = await burst(endpoint, wire_request(endpoint, "/"), 8, .05, None)
            assert result["attempted"] == 8
            assert result["outcomes"] == {"timeout": 8}
            assert result["success_median_ms"] is None
            assert all(sample["stage"] == "headers" for sample in result["samples"])

    asyncio.run(scenario())


def test_disconnects_are_client_actions_and_server_can_recover():
    async def scenario():
        async def handler(reader, writer):
            writer.write(response({"result": [1], "error": None}))
            await writer.drain()

        async with server(handler) as endpoint:
            wire = wire_request(endpoint, "/")
            for sent in (wire[:-2], wire):
                result = await abandon(endpoint, sent, 1)
                assert result["outcome"] == "client_aborted_after_send"
            result = await exchange(endpoint, wire, 1)
            assert result["outcome"] == "ok"

    asyncio.run(scenario())


def test_native_validation_rejects_pagination_and_missing_ids():
    digest = ids_digest([1, 2])
    validate_ids({"items": [2, 1], "next_cursor": None}, True, digest)
    validate_ids({"items": [{"id": 2}, {"id": 1}], "next_cursor": None}, True, digest)
    with pytest.raises(ValueError, match="paginated"):
        validate_ids({"items": [{"id": 1}], "next_cursor": "next"}, True, digest)
    with pytest.raises(ValueError, match="differ"):
        validate_ids({"items": [{"id": 1}]}, True, digest)


def test_stalled_upload_probe_and_recovery():
    async def scenario():
        lock = asyncio.Lock()
        first = True

        async def handler(reader, writer):
            nonlocal first
            async with lock:
                if first:
                    first = False
                    await reader.read()  # incomplete upload blocks until the client closes
                else:
                    writer.write(response({"result": [1], "error": None}))
                    await writer.drain()

        async with server(handler) as endpoint:
            partial = wire_request(endpoint, "/", {"action": "findNotes"})[:-1]
            probe_wire = wire_request(endpoint, "/")
            result = await stalled_upload(endpoint, partial, probe_wire, 1, None)
            assert result["outcome"] == "timeout"
            assert (await exchange(endpoint, probe_wire, 1))["outcome"] == "ok"

    asyncio.run(scenario())


def test_endpoint_rejects_credentials_and_header_injection():
    for url in ("http://user:secret@localhost:7777", "http://localhost/extra", "http://localhost\r\nInjected:yes"):
        with pytest.raises(ValueError):
            Endpoint.parse(url)
