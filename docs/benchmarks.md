# API benchmarks

[← Documentation](README.md)

This page compares three ways of talking to Anki:

- **AnkiConnect**: the upstream add-on.
- **AnkiConnect Shim**: Tsunagi's AnkiConnect-compatible API.
- **Tsunagi**: Tsunagi's own `/v1` API.

It reports only measurements taken on the **full Anki desktop app**, over real
HTTP connections: what a client actually experiences. Test-harness
measurements, which run Anki's collection code without a window, the Qt
main-thread handoff or an HTTP server, are developer profiling data. They are
in [performance notes](performance_notes.md).

Measured with Anki **26.09.2**: AnkiConnect on **2026-09-21**, the AnkiConnect
Shim and the Tsunagi API on **2026-09-23**. The page is updated in place; it is
a current snapshot, not a history.

## Summary

- **Under load, both Tsunagi APIs answered every request.** AnkiConnect refused
  most connections once 64 or more requests arrived at the same moment.
- **For a plain note-ID lookup, the AnkiConnect Shim is still faster than the
  Tsunagi API,** about 2 times at every level. The gap was 3 to 5 times before
  the 2026-09-23 fix to single-field queries. The Tsunagi API still does more
  per request, and closing the rest of the gap is ongoing work.
- **Only a note-ID lookup has been measured so far.** Other tasks, such as
  reading cards, creating notes or uploading media, have no desktop results yet.

## Many clients at once

**What happens:** a test client releases N requests at the same moment. Each
opens its own new connection and asks for the IDs of every note in a real Anki
testing profile (4,547 notes for AnkiConnect, 4,561 for the later runs). Each request gets **5 seconds**. Every level runs three
times, and the tables add the three runs together.

### Requests answered

| Simultaneous requests | AnkiConnect | AnkiConnect Shim | Tsunagi |
| --- | --- | --- | --- |
| 1 | 3 / 3 | 3 / 3 | 3 / 3 |
| 16 | 48 / 48 | 48 / 48 | 48 / 48 |
| 64 | 124 / 192 | 192 / 192 | 192 / 192 |
| 256 | 145 / 768 | 768 / 768 | 768 / 768 |

"Answered" means a complete response with exactly the expected note IDs.
**Every AnkiConnect failure was a refused connection:** the client got no
response at all, not an error message or a timeout. On this Windows machine,
each refusal took about **2 seconds** to report. Those clients waited, then
got nothing.

### Time until the whole burst finished

The clock starts when all requests are released. It stops when the last one has
either succeeded or failed, so **failures are included**. Values are the median
of the three runs, in milliseconds.

| Simultaneous requests | AnkiConnect | AnkiConnect Shim | Tsunagi |
| --- | ---: | ---: | ---: |
| 1 | 33 | 3 | 6 |
| 16 | 1,156 | 27 | 60 |
| 64 | 2,260 | 112 | 243 |
| 256 | 2,597 | 371 | 858 |

AnkiConnect's bursts at 64 and 256 take over two seconds, and most of their
requests end in a refusal.

### How long a successful request waited

Median / 95th percentile in milliseconds, for each request that got an answer,
from release to the complete, verified response. **Failed requests are not
included.** AnkiConnect's 64 and 256 rows describe only the requests that got
through (124 and 145 of them).

| Simultaneous requests | AnkiConnect | AnkiConnect Shim | Tsunagi |
| --- | --- | --- | --- |
| 1 | 32.6 / 33.5 | 3.2 / 3.9 | 5.5 / 6.0 |
| 16 | 612.9 / 1,124.9 | 25.9 / 33.0 | 58.2 / 64.2 |
| 64 | 1,186.8 / 2,187.2 | 103.4 / 122.5 | 217.3 / 252.3 |
| 256 | 1,559.1 / 2,525.4 | 263.9 / 364.1 | 570.2 / 855.0 |

The Tsunagi API still plans the query and builds its response envelope, which
the AnkiConnect Shim does not. Both use the IDs Anki's search returns without
loading the notes, and every request reads fresh data.

### Giving AnkiConnect more time does not help

With a **30-second** limit instead of 5, a 256-request burst still left
AnkiConnect with 154 / 768 answered and 614 refused. The AnkiConnect Shim and
the Tsunagi API each answered 768 / 768.

Across both limits, the AnkiConnect Shim and the Tsunagi API each answered
**1,779 / 1,779** requests. AnkiConnect answered **474 / 1,779** and refused
1,305 connections. These counts describe this burst pattern on this Windows
machine, not a general limit on the number of clients.

### Clients that hang up or stall

| Situation | AnkiConnect | AnkiConnect Shim | Tsunagi |
| --- | --- | --- | --- |
| A client disconnects while sending headers, or right after sending a request (384 attempts) | 286 got that far; 98 were refused first. Later requests worked. | All 384 got that far. Later requests worked. | All 384 got that far. Later requests worked. |
| One client starts an upload and stops sending. Another client makes a normal request meanwhile (3 attempts, 1-second limit). | All 3 took longer than 1 second | 4.0–5.1 ms | 6.8–10.1 ms |

A request that was sent before the client hung up may or may not have run; the
test only checks that the server keeps working.

### Test setup

- **Machine:** Windows, client and Anki on the same machine (loopback).
- **Anki:** full desktop 26.09.2 with the same testing profile, which had 4,547
  notes for the AnkiConnect run and 4,561 for the later runs.
- **Request:** `findNotes` through AnkiConnect and the AnkiConnect Shim;
  `GET /v1/notes?select=id&search=` through the Tsunagi API. No pagination.
- **Isolation:** one add-on enabled at a time, with Anki restarted when switching
  between AnkiConnect and Tsunagi. Tsunagi reported version **0.2.0**, running
  the working tree after `64e6824` with the single-field query fix.
- **No retries.** Every attempt opens a new connection. The client only reads;
  it does not change collection data.

The runner checks the profile name and the server's identity before testing.
This benchmark does not cover write cancellation, media uploads, connection
pooling, or sustained traffic over a long period.

## Planned

Desktop workloads defined by **client goals**, in both directions, are planned.
An example goal is "notes matching a search, with only the Front field, 50 at a
time". Each goal would be written the natural way for each API, instead of
measuring every API with AnkiConnect's action shapes. Until those exist, the
note-ID lookup above is the only desktop comparison.

## Reproduce the benchmark

Start Anki with a testing profile, then run the client on the same operating
system as Anki:

```sh
python tools/benchmark_connections.py \
  --url http://127.0.0.1:7777 --profile "YOUR TEST PROFILE" \
  --implementation shim --output dist/benchmarks/live-connections-shim.json
```

`--implementation shim` measures the AnkiConnect Shim, `native` the Tsunagi API
and `upstream` AnkiConnect. Repeat with `--implementation native` in the same
session. Then disable Tsunagi, enable AnkiConnect, restart Anki, and run with
`--implementation upstream` and AnkiConnect's port. Keep the profile, server
settings and background activity the same. `--preflight-only` checks the setup
without load. If needed, set `TSUNAGI_BENCH_API_KEY` in the client's
environment; keys are not saved in reports.

## Raw reports

Results are saved as JSON under `dist/benchmarks/live-connections-*.json`. What
they record is described in
[performance notes](performance_notes.md#live-connection-reports).
