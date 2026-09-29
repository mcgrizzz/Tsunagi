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

There are three benchmarks, all on Anki **26.09.2** with the same testing
profile:

- **[Real client workloads](#real-client-workloads):** ten goals taken from
  real AnkiConnect clients, measured on **2026-09-29**.
- **[Complete tasks](#complete-tasks):** two whole things a user does in
  Yomitan, measured on **2026-09-29**.
- **[Many clients at once](#many-clients-at-once):** a burst of simultaneous
  note-ID lookups. AnkiConnect was measured on **2026-09-21**, the other two on
  **2026-09-23**.

The client workloads and complete tasks were measured with Tsunagi `main` as of
2026-09-29. The burst test was measured with `main` as of 2026-09-23 (around
`634baf3`). Later changes, such as the per-route permission checks and the
request log, add a few microseconds per request and are not in it.

## Summary

- **For the client goals, the Tsunagi API is fastest on six of ten,** often
  by a wide margin: fewer requests, and only the fields the client uses. It is
  1.4 ms behind the Shim on a seventh, and slower on three large reads (known
  words and both review histories).
- **For a whole mining session, the Tsunagi API took 323 ms against
  AnkiConnect's 2,862 ms,** in 50 requests instead of 80. Loading Yomitan's
  settings takes about 5 ms through either Tsunagi API.
- **The AnkiConnect Shim is faster than AnkiConnect on seven of ten goals**
  with the same requests, even on one, and slower on two.
- **All three APIs gave the same answers** in every run.
- **Under load, both Tsunagi APIs answered every request.** AnkiConnect began
  refusing connections at 64 simultaneous requests and refused most at 256.

## Real client workloads

Each workload is one goal from a real AnkiConnect client's source code. For
AnkiConnect and the AnkiConnect Shim it follows that client's request sequence,
with the test-profile adjustments listed under **Simplifications** below; for the Tsunagi API it uses the natural `/v1` requests for the same
goal. Each run records a fingerprint of the answer, and the fingerprints of the
three APIs were compared.

Median of ten runs after a first run, in milliseconds, on the `[DEV] Yomine`
testing profile: about 5,350 notes (mostly Kiku+ and Kaishi 1.5k mining cards),
their review history and media. Lower is faster.

| Client goal | Client code | AnkiConnect | AnkiConnect Shim | Tsunagi API |
| --- | --- | ---: | ---: | ---: |
| **Yomitan:** check 20 dictionary entries for duplicates and list the matching notes | [check](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L683-L700), [IDs](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/comm/anki-connect.js#L308-L362) | 188 (3 requests) | 97 (3) | **5.7** (2) |
| **Yomitan,** same check with "Check for duplicates across all models" on | [options](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/data/anki-note-builder.js#L118-L131) | 183 (3) | 117 (3) | **4.3** (1) |
| **Yomitan:** add a mined note with an audio file and a picture | [add](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/display/display-anki.js#L924), [media](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/comm/anki-connect.js#L279-L290) | 89 (3) | 27 (3) | **25** (2) |
| **asbplayer:** attach a screenshot to the most recently added note | [find](https://github.com/killergerbah/asbplayer/blob/ff63e8fff2aaa0171ab36b1977346500713e2667/common/anki/anki.ts#L549-L591), [update](https://github.com/killergerbah/asbplayer/blob/ff63e8fff2aaa0171ab36b1977346500713e2667/common/anki/anki.ts#L730-L752) | 152 (5) | 21 (5) | **19** (3) |
| **Yomine:** refresh known words: every note, plus each first card's latest interval | [notes](https://github.com/mcgrizzz/Yomine/blob/e3bb005b0f085c4a6269579b40f2f25f8faee595/src/anki/state.rs#L373-L392), [intervals](https://github.com/mcgrizzz/Yomine/blob/e3bb005b0f085c4a6269579b40f2f25f8faee595/src/anki/state.rs#L64-L95) | **1,264** (3, 84 MB) | 1,394 (3, 79 MB) | 2,058 (3, 96 MB) |
| **asbplayer:** first build of the mined-words cache: notes, card details, suspension and study status | [notes and cards](https://github.com/killergerbah/asbplayer/blob/ff63e8fff2aaa0171ab36b1977346500713e2667/common/dictionary-db/dictionary-db-anki.ts#L426-L509), [status](https://github.com/killergerbah/asbplayer/blob/ff63e8fff2aaa0171ab36b1977346500713e2667/common/dictionary-db/dictionary-db-anki.ts#L575-L633), [batch sizes](https://github.com/killergerbah/asbplayer/blob/ff63e8fff2aaa0171ab36b1977346500713e2667/common/anki/anki.ts#L8-L10) | 16,605 (434, 498 MB) | 10,589 (434, 468 MB) | **1,716** (8, 77 MB) |
| **asbplayer:** 10-second poll for edited or reviewed cards | [poll](https://github.com/killergerbah/asbplayer/blob/ff63e8fff2aaa0171ab36b1977346500713e2667/common/anki/anki.ts#L353-L364) | 30 | **3.7** | 5.1 |
| **Obsidian_to_Anki:** regenerate the note-type table (every note type's field names) | [names](https://github.com/ObsidianToAnki/Obsidian_to_Anki/blob/feb3db2708559bf386412ef6f8be00753faf7775/src/settings.ts#L350-L356), [fields](https://github.com/ObsidianToAnki/Obsidian_to_Anki/blob/feb3db2708559bf386412ef6f8be00753faf7775/main.ts#L62-L71) | 3,587 (114) | 148 (114) | **10** (1) |
| **anki-mcp-server:** review history for one deck | [one deck](https://github.com/ankimcp/anki-mcp-server/blob/2b2f9892d14dffa7f4fdedd05c4bcea09a4f61f5/src/mcp/primitives/essential/tools/review-stats/review-stats.tool.ts#L143-L157) | **407** (1, 9 MB) | 584 (1, 8 MB) | 775 (1, 19 MB) |
| **anki-mcp-server:** review history for all decks | [all decks](https://github.com/ankimcp/anki-mcp-server/blob/2b2f9892d14dffa7f4fdedd05c4bcea09a4f61f5/src/mcp/primitives/essential/tools/review-stats/review-stats.tool.ts#L248-L285) | 1,224 (2, 32 MB) | **1,209** (2, 27 MB) | 1,371 (1, 35 MB) |

Links point to each client at the commit that was read. Where a client's
behavior depends on settings, the workload uses the defaults unless the row
says otherwise.

**How to read it:**

- **Request counts come from the clients.** asbplayer fetches card details in
  batches of 10, because full card records are large; Obsidian_to_Anki asks for
  each note type's fields separately. The Tsunagi API does each goal in as few
  requests as it allows, selecting only the fields the client reads.
- **AnkiConnect's small requests take about 30 ms each** even when the work is
  tiny, as in the change poll. That per-request delay is why its many-request
  goals are slow.
- **The Tsunagi API is slower on three reads:** Yomine's known words and both
  review histories. Its responses are larger for these, because each row
  repeats its field names: for one deck's reviews, about 19 MB against
  `cardReviews`' 9 MB of plain arrays. How much of the time difference that
  explains has not been measured; the AnkiConnect Shim sends the smallest
  review response and is still slower than AnkiConnect there, so server work
  differs as well.
- **Listing duplicates:** Yomitan finds the matching notes with a search on
  the selected note type's first field name, which reads every note. The
  Tsunagi API asks for notes whose first field matches, using the index Anki's
  duplicate check uses. Both give the same notes on this profile. With "Check
  for duplicates across all models" on, the check's own IDs are the list, so
  the Tsunagi API needs one request.
- **Simplifications:** asbplayer's update searches only the benchmark deck
  instead of the whole collection, to keep the test profile safe, and skips an
  optional Browser refresh. Yomine asks for intervals only for its mapped note
  types; the workload asks for every note's first card. asbplayer's change
  poll normally also filters by deck and word field.

**Test setup:** Windows, client and Anki on the same machine, one API at a time
with the other add-on disabled and Anki restarted between AnkiConnect and
Tsunagi. Each request uses a new connection, one after another. Notes and media
added by a trial go into a dedicated `Tsunagi Benchmark` deck with a
`tsunagi-benchmark` tag and a `tsunagi_bench_` filename prefix, and are deleted
after each trial, outside the timed part. The run refuses to start if any
already exist, and checks at the end that the note count is unchanged. Anki
moves deleted media to its media trash; **Tools → Check Media → Empty Trash**
clears it.

## Complete tasks

Two things a user actually does, from start to finish, each written the way
Yomitan does it for AnkiConnect and the way a Yomitan integration would for the
Tsunagi API. Median of ten runs after a first run, in milliseconds, on the same
profile as above.

| Task | Client code | AnkiConnect | AnkiConnect Shim | Tsunagi API |
| --- | --- | ---: | ---: | ---: |
| **Mine 10 new words:** ten lookups; each popup checks its own 3 to 5 entries for duplicates (some already saved), then the user adds one new word with audio, a picture and automatic suspension | [duplicates](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L651-L753), [suspend](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L808-L816) | 2,862 (80 requests, 18 KB) | 953 (80, 17 KB) | **323** (50, 18 KB) |
| **Open Yomitan's Anki settings:** the deck list, the note types, and the selected note type's fields | [lists](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/pages/settings/anki-controller.js#L439-L484), [fields](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/pages/settings/anki-controller.js#L1100-L1170) | 92 (3, 4.7 KB) | **4.8** (3, 4.5 KB) | 5.1 (3, 4.7 KB) |

**How to read it:**

- **Mining:** each popup's duplicate check is 3 AnkiConnect requests (the
  check, then a search and a batch of searches to list the matching notes) and
  2 Tsunagi API requests (the check, then the matching notes by first field). Each new word then takes 5 AnkiConnect requests (store the
  audio, store the picture, add the note, find its cards, suspend them) and 3
  Tsunagi API requests (both files at once, the note with its card IDs,
  suspend).
- **Settings:** all three ask for the deck names, the note type names, and
  then only the selected note type's fields.
- **Same answers:** both tasks gave identical results through all three APIs:
  the same duplicates and matching notes, and the same notes, tags, suspended
  cards and media.

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

AnkiConnect's bursts at 64 and 256 take over two seconds. About a third of its
requests at 64 end in a refusal, and most at 256.

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

### A longer timeout doesn't stop AnkiConnect's refusals

With a **30-second** limit instead of 5, a 256-request burst still left
AnkiConnect with 154 / 768 answered (up from 145 with 5 seconds) and 614
refused. The AnkiConnect Shim and
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
  the working tree after `c717ceb` with the single-field query fix.
- **No retries.** Every attempt opens a new connection. The client only reads;
  it does not change collection data.

The runner checks the profile name and the server's identity before testing.
This benchmark does not cover write cancellation, media uploads, connection
pooling, or sustained traffic over a long period.

## Reproduce the benchmarks

### Real client workloads

Start Anki with a testing profile that has a `Kiku+` note type with an
`Expression` field, `Mining` and `Kaishi 1.5k` decks, and review history, then
run on the same machine:

```sh
python tools/benchmark_workloads.py \
  --url http://127.0.0.1:7777 --profile "YOUR TEST PROFILE" \
  --implementation native --output dist/benchmarks/workloads-native.json
```

Repeat with `--implementation shim`, then with AnkiConnect enabled instead of
Tsunagi and `--implementation upstream --url http://127.0.0.1:8765`.
`--workloads` runs a subset, and `--repeats` sets the number of timed runs.
The runner writes to the profile; use a testing profile.

### Many clients at once

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

Results are saved locally as JSON under `dist/benchmarks/` (not committed): `workloads-*.json` for the
client workloads and `live-connections-*.json` for the burst test. What they
record is described in
[performance notes](performance_notes.md#live-connection-reports).
