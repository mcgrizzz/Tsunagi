"""
The event stream: GET /v1/events as Server-Sent Events.

Hand-rolled SSE over StreamingResponse - no new dependencies, and unlike a
websocket it goes through the auth/CORS middleware like any other request.
The generator polls the broker's thread-safe queue with a short sleep, so no
event-loop capture is needed (it behaves identically under uvicorn's loop
and the TestClient's).

Events are published from Qt-main-thread hook callbacks registered in the
addon root __init__.py; see adapters/events.py for the broker and the
dispatch rules.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Query
from starlette.responses import StreamingResponse

from ...adapters.events import broker
from ...adapters.settings import settings

router = APIRouter()

POLL_SECONDS = 0.25
HEARTBEAT_SECONDS = 15.0

_DESCRIPTION = """\
Streams collection events as Server-Sent Events (`text/event-stream`).

Event types (each `data:` line is one JSON object with `seq` and `ts` epoch ms):

- `op` - a completed operation: `{"origin": "api"|"ui"|null, "changes": [...],
  "label": "Update Note"}` where `changes` lists the true OpChanges flags
  (card, note, deck, tag, notetype, config, study_queues, ...) and `label`
  (when known) is the localized name of the operation. Anki's change events
  carry no record ids - treat `op` as an invalidation signal and requery,
  e.g. `GET /v1/notes?search=edited:1`.
- `review` - a card answered in Anki's reviewer: `{"card_id", "ease"}`.
  Fires just before the matching `op`.
- `sync` - `{"phase": "started"|"finished"}`; a finished sync is followed by
  a `reset`.
- `reset` - everything may have changed (Anki's legacy full refresh, or
  `{"reason": "lagged"}` when this client fell behind and events were
  dropped).
- `close` - final frame before the stream ends:
  `{"reason": "shutdown"|"timeout"|"max_events"|"auth"}`. `auth` means the
  API key changed after this stream connected - reconnect with the current
  key.

`op.origin`: `"api"` is a change made through Tsunagi; `"ui"` is an Anki
window acting on its own behalf; `null` means Anki did not attribute the
operation to any window (many of its actions don't).

Delivery is live-only and best-effort - there is no replay. Browser
`EventSource` cannot send headers, so this route also accepts the API key as
the `api_key` query parameter. The `stats` envelope used by JSON routes does
not apply to a stream.

Not every change produces an event: media writes and import/export run
outside Anki's change-tracking, and raw database edits by other addons are
invisible. See the README for the full list.
"""


def _sse_frame(event: Dict[str, Any]) -> str:
    return (f"event: {event['type']}\n"
            f"id: {event['seq']}\n"
            f"data: {json.dumps(event, separators=(',', ':'))}\n\n")


def _close_frame(reason: str) -> str:
    return f"event: close\ndata: {json.dumps({'reason': reason})}\n\n"


@router.get(
    "/v1/events",
    response_model=None,
    responses={200: {"content": {"text/event-stream": {}},
                     "description": "An SSE stream of collection events."}},
    summary="Stream collection events",
    description=_DESCRIPTION,
    tags=["Events"],
    operation_id="streamEvents",
)
def stream_events(
    timeout: Optional[float] = Query(
        None, gt=0, description="Close the stream cleanly after this many "
                                "seconds (for scripts and polling clients)."),
    max_events: Optional[int] = Query(
        None, gt=0, description="Close the stream cleanly after this many "
                                "events."),
    api_key: Optional[str] = Query(
        None, description="Alternative to the X-Api-Key header for clients "
                          "that cannot send headers (browser EventSource). "
                          "Checked by the auth middleware."),
) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        token = broker.subscribe()
        # Auth is checked by the middleware once, at connection time - but a
        # stream lives for hours. If the API key changes underneath us, the
        # connection was authorized under rules that no longer exist: close
        # it and make the client reconnect with the current key.
        key_at_connect: str = settings.get("api_key", "")
        try:
            # retry: sets the client's reconnect delay; the comment line
            # forces the response headers out through buffering proxies.
            yield "retry: 3000\n\n: connected\n\n"
            sent = 0
            start = last_beat = time.monotonic()
            while True:
                for event in broker.drain(token):
                    yield _sse_frame(event)
                    sent += 1
                    if max_events is not None and sent >= max_events:
                        yield _close_frame("max_events")
                        return
                if broker.is_draining():
                    yield _close_frame("shutdown")
                    return
                if settings.get("api_key", "") != key_at_connect:
                    yield _close_frame("auth")
                    return
                now = time.monotonic()
                if timeout is not None and now - start >= timeout:
                    yield _close_frame("timeout")
                    return
                if now - last_beat >= HEARTBEAT_SECONDS:
                    yield ": ping\n\n"
                    last_beat = now
                await asyncio.sleep(POLL_SECONDS)
        finally:
            broker.unsubscribe(token)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
