"""Bounded, unpooled HTTP clients for the live Anki connection benchmark.

Each attempt opens one socket, sends one request, and makes no retry. The timer
includes connecting, sending, receiving, and checking the complete response.
These JSON endpoints use Content-Length; unexpected framing is reported rather
than treated as a successful reply. No requests in this module modify Anki.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import socket
import statistics
import struct
import sys
import time
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    authority: str

    @classmethod
    def parse(cls, url):
        parts = urlsplit(url)
        if (parts.scheme != "http" or not parts.hostname or parts.username
                or parts.password or parts.query or parts.fragment
                or parts.path not in ("", "/") or "\r" in url or "\n" in url):
            raise ValueError("Use an http://host:port base URL without credentials or a path")
        return cls(parts.hostname, parts.port or 80, parts.netloc)


def wire_request(endpoint, path, payload=None, api_key=None):
    body = b"" if payload is None else json.dumps(payload).encode()
    headers = [f"{'GET' if payload is None else 'POST'} {path} HTTP/1.1",
               f"Host: {endpoint.authority}", "Connection: close",
               "Content-Type: application/json", f"Content-Length: {len(body)}"]
    if api_key:
        if "\r" in api_key or "\n" in api_key:
            raise ValueError("Invalid API key header")
        headers.append(f"X-API-Key: {api_key}")
    return ("\r\n".join(headers) + "\r\n\r\n").encode() + body


def action_request(endpoint, action, params=None, api_key=None):
    payload = {"action": action, "version": 6, "params": params or {}}
    if api_key:
        payload["key"] = api_key
    return wire_request(endpoint, "/", payload, api_key)


def ids_digest(ids):
    if not isinstance(ids, list) or any(type(value) is not int for value in ids):
        raise ValueError("Expected a list of integer note IDs")
    return hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()


def validate_ids(payload, native, expected_digest):
    if native:
        if payload.get("next_cursor") is not None:
            raise ValueError("Native response was paginated; omitted limit must return all IDs")
        # A one-field projection may return the scalar values directly.
        ids = [item if type(item) is int else item["id"] for item in payload["items"]]
    else:
        ids = payload["result"]
    if ids_digest(ids) != expected_digest:
        raise ValueError("Note IDs differ from the preflight result")


async def exchange(endpoint, wire, timeout, validate=None, *, return_payload=False):
    started = time.perf_counter()
    writer = None
    result = {"outcome": "pending", "stage": "connect", "response_bytes": 0}

    async def perform():
        nonlocal writer
        reader, writer = await asyncio.open_connection(endpoint.host, endpoint.port)
        result["stage"] = "send"
        writer.write(wire)
        await writer.drain()
        result["stage"] = "headers"
        head = await reader.readuntil(b"\r\n\r\n")
        result["response_bytes"] += len(head)
        status_line, *lines = head[:-4].split(b"\r\n")
        result["http_status"] = int(status_line.split()[1])
        if not 200 <= result["http_status"] < 300:
            result["outcome"] = "http_error"
            return
        headers = dict(line.split(b":", 1) for line in lines)
        headers = {key.lower(): value.strip() for key, value in headers.items()}
        length = int(headers[b"content-length"])
        if not 0 <= length <= 64 * 1024 * 1024 or b"transfer-encoding" in headers:
            raise ValueError("Unexpected response framing or response larger than 64 MiB")
        result["stage"] = "body"
        body = await reader.readexactly(length)
        result["response_bytes"] += len(body)
        result["stage"] = "validate"
        payload = json.loads(body)
        if isinstance(payload, dict) and payload.get("error") is not None:
            result["outcome"] = "api_error"
            return
        if validate:
            validate(payload)
        result["outcome"] = "ok"
        if return_payload:
            result["payload"] = payload

    try:
        await asyncio.wait_for(perform(), timeout)
    except asyncio.TimeoutError:
        result["outcome"] = "timeout"
    except asyncio.IncompleteReadError as exc:
        result["response_bytes"] += len(exc.partial)
        result["outcome"] = ("closed_without_response" if not result["response_bytes"]
                             else "truncated_response")
    except ConnectionRefusedError:
        result["outcome"] = "connection_refused"
    except ConnectionResetError:
        result["outcome"] = "connection_reset"
    except (OSError, asyncio.LimitOverrunError) as exc:
        result["outcome"] = "transport_error"
        result["error_type"] = type(exc).__name__
        result["errno"] = getattr(exc, "errno", None)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        result["outcome"] = "invalid_response"
        result["error_type"] = type(exc).__name__
        result["detail"] = str(exc)[:200]
    finally:
        result["elapsed_ms"] = (time.perf_counter() - started) * 1000
        if writer:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, asyncio.TimeoutError):
                pass
    return result


async def burst(endpoint, wire, concurrency, timeout, validate):
    gate = asyncio.Event()

    async def attempt():
        await gate.wait()
        return await exchange(endpoint, wire, timeout, validate)

    tasks = [asyncio.create_task(attempt()) for _ in range(concurrency)]
    started = time.perf_counter()
    gate.set()
    samples = await asyncio.gather(*tasks)
    return summarize(samples, (time.perf_counter() - started) * 1000)


def summarize(samples, elapsed_ms):
    successful = sorted(sample["elapsed_ms"] for sample in samples if sample["outcome"] == "ok")
    return {"attempted": len(samples), "outcomes": dict(Counter(s["outcome"] for s in samples)),
            "elapsed_ms": elapsed_ms,
            "success_median_ms": statistics.median(successful) if successful else None,
            "success_p95_ms": successful[math.ceil(len(successful) * .95) - 1] if successful else None,
            "samples": samples}


async def abandon(endpoint, wire, timeout):
    """Send bytes and close with RST, without assuming the server received them."""
    writer = None
    started = time.perf_counter()
    result = {"outcome": "pending", "stage": "connect"}

    async def send():
        nonlocal writer
        _, writer = await asyncio.open_connection(endpoint.host, endpoint.port)
        result["stage"] = "send"
        writer.write(wire)
        await writer.drain()
        # Linux/macOS linger uses two ints; Windows uses two unsigned shorts.
        linger = struct.pack("HH" if sys.platform == "win32" else "ii", 1, 0)
        writer.get_extra_info("socket").setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
        writer.transport.abort()
        result["outcome"] = "client_aborted_after_send"

    try:
        await asyncio.wait_for(send(), timeout)
    except asyncio.TimeoutError:
        result["outcome"] = "timeout"
    except OSError as exc:
        result["outcome"] = "transport_error"
        result["error_type"] = type(exc).__name__
    finally:
        if writer:
            writer.transport.abort()
        result["elapsed_ms"] = (time.perf_counter() - started) * 1000
    return result


async def stalled_upload(endpoint, partial_wire, probe_wire, timeout, validate):
    """Keep one body incomplete while an independent, valid query is attempted."""
    _, writer = await asyncio.wait_for(asyncio.open_connection(endpoint.host, endpoint.port), timeout)
    try:
        writer.write(partial_wire)
        await writer.drain()
        await asyncio.sleep(.1)  # allow the upstream 25 ms poller to accept it
        probe = asyncio.create_task(exchange(endpoint, probe_wire, 1, validate))
        await asyncio.sleep(2)  # still open when the probe's one-second deadline expires
        return await probe
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 1)
        except (OSError, asyncio.TimeoutError):
            pass


def query_request(endpoint, native, query, api_key):
    if native:
        return wire_request(endpoint, "/v1/notes?" + urlencode({"select": "id", "search": query}), api_key=api_key)
    return action_request(endpoint, "findNotes", {"query": query}, api_key)
