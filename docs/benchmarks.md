# Bulk API benchmarks

[← Development](development.md)

`tools/benchmark_compat.py` compares **upstream AnkiConnect**, **Tsunagi’s
AnkiConnect API**, and **native Tsunagi** on equivalent tasks. All three run
**sequentially**, using fresh copies of the same collection.
It creates its own temporary collections; it doesn't connect to your open Anki.

**This measures headless API processing, not real desktop latency.** It uses
Anki's real backend, the project's fake Qt operations, upstream's original HTTP
wrapper, and FastAPI's TestClient. It does not measure API sockets, Qt scheduling,
Anki window responsiveness, or network media downloads. Upstream’s GUI edit hooks
are disabled in this harness. The two HTTP harnesses
also have different overhead, so small timing differences aren't evidence of a
faster implementation.

## Run a comparison

Use Python 3.12 or newer with the development dependencies and `jsonschema==4.23.0`.
Build the bundled dependencies first as described in [development setup](development.md#environment-and-build).
The reference loader requires an unchanged AnkiConnect checkout at commit
`de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e`.

Start with a short run:

```sh
python tools/benchmark_compat.py \
  --checkout /path/to/anki-connect \
  --read-sizes 20 --write-sizes 3 --batches 0,7 --repeats 2 \
  --output /tmp/tsunagi-bulk-smoke.json
```

Then run the larger workloads:

```sh
python tools/benchmark_compat.py \
  --checkout /path/to/anki-connect \
  --output /tmp/tsunagi-bulk-benchmark.json
```

Defaults are 1,000 and 10,000 cards, 100 and 1,000 new notes, five repeated
samples plus a first-use sample, and 16 KiB per media attachment. Set
`--read-sizes 0` or `--write-sizes 0` to omit that family. `--batches 0` puts all
card IDs in one `cardsInfo` request; a positive batch size splits those requests.
By default, `--batches 0` requests every card in one response: `cardsInfo` gets
all IDs and native `GET /v1/cards` uses a limit equal to the fixture size. Native
queries no longer impose a 5,000-row cap. Use `--batches 500` for a separate
comparison in which both APIs return cards in smaller chunks.

To investigate one case, select workloads and implementations:

```sh
python tools/benchmark_compat.py \
  --checkout /path/to/anki-connect \
  --workloads read_cards --read-sizes 10000 --batches 500 \
  --implementations upstream,shim,native \
  --output /tmp/tsunagi-card-benchmark.json
```

Large new-media runs can take several minutes per implementation. The default
`--worker-timeout 1200` limits the **whole worker process**, including every
restored trial and profiling. It is not Tsunagi’s operation timeout. Increase it
for slower storage; this does not change any API setting.

## What each workload does

| Task | AnkiConnect and shim | Native Tsunagi |
| --- | --- | --- |
| Read every card | `findCards`, then `cardsInfo` for every ID | Page through `GET /v1/cards`, selecting every field needed to reproduce `cardsInfo` |
| Add text notes | One `addNotes` batch | One `POST /v1/notes` per note |
| Add notes with new media | One `addNotes` batch with an inline image and audio file per note | Two `POST /v1/media` uploads, then `POST /v1/notes`, per note |
| Add notes with existing media | The same batch, with identical files already present | The same uploads and creates, with identical files already present |

The native read covers the **same card data**, including rendered question and
answer, note fields, scheduling values, and next-review labels. Representation
differences are normalized outside the timer; card order, IDs and every returned
value must match. A smaller projection that omits rendering would answer a
different question and is not substituted into this comparison.

Writes must produce the same note/card counts, fields, tags, attachment references
and media bytes, with no extra media files. The native workflow uses the filenames
returned by uploads. It also returns richer note creation responses; their cost
is included even though this workload only needs their note IDs. There is no
native batch-create endpoint in this comparison. These are successful-workload
comparisons; failure behavior and undo grouping are not measured as equivalent
contracts.

Fixtures use Basic notes with one card each, no review history, and synthetic
media. They test storing and referencing attachments, not image/audio playback.
Candidate notes are new in every write trial; “existing media” means the files
already exist, not that the notes are duplicates.

Each implementation runs in a separate process. Collection copies are restored
before every trial, including reads. Setup, copying, opening collections and
verification are outside the timer. Timings include request encoding, API
handling, response serialization and client decoding. Implementation order
rotates between workloads. Workers and requests never run concurrently with
each other. Do not run a second benchmark or test suite alongside them.

“First” means the first request in that worker. Repeated samples reuse the
process, but open a fresh collection copy; they are not a fully warmed Anki
session. Operating-system caches are not cleared.

## Read the report

The JSON report contains:

- First-use and repeated timings, per-action timings, response sizes and throughput.
- Median, minimum and maximum repeated times; raw samples remain available.
- Backend calls, fake Qt dispatch counts and the most expensive Python functions
  from a separate profiling trial. These are function-call counts, not SQL-query counts.
- Peak resident memory for each worker on platforms providing `getrusage()`.
  This includes imports, requests, decoding, profiling and verification; it is
  not the memory allocation of an individual request.
- Exact Anki/Python/Tsunagi versions, upstream revision, source hashes and workload settings.
- Correctness fingerprints, failures, and whether the entire run completed.
  `equal_results` is `null` when only one implementation was selected.

The tool stops on errors, timeouts or differing results and leaves a partial
report marked incomplete. A process timeout also saves verified progress and any
completed implementations beside the report. A speed measurement is useful only when its results
are correct. Note IDs generated by write trials differ naturally; those trials
compare saved fields, tags, media and counts instead of generated ID values.

These are opt-in benchmarks. They aren't part of routine pytest runs and do not
impose timing thresholds on CI. Real desktop/socket measurements, media URLs,
reviewed cards and more complex templates remain separate follow-up work.

## Initial findings — Anki 26.8.1 / Python 3.12.12

Measured sequentially on Linux/WSL using the fixtures above. Times below are
medians of repeated trials, excluding the first request and profiling. They
measure this harness and collection, not end-to-end desktop performance.

| Task | Upstream | Shim | Native | Repeated trials |
| --- | ---: | ---: | ---: | ---: |
| Read all 10,000 cards, one card-data response | 0.73 s | 1.13 s | 2.07 s | 5 |
| Add 1,000 text notes | 1.65 s | 1.57 s | 2.62 s | 5 |
| Add 100 notes with new image/audio files | 1.68 s | 1.70 s | 2.03 s | 3 |
| Add 100 notes with existing image/audio files | 0.34 s | 0.36 s | 0.63 s | 3 |
| Add 1,000 notes with new image/audio files | 17.11 s | 44.42 s | 39.49 s | 2 |
| Add 1,000 notes with existing image/audio files | 2.55 s | 6.28 s | 5.73 s | 2 |

The full-card task takes two requests through AnkiConnect/shim (IDs, then card
data), and one native query. Native writes take one request per text note or
three per media note; AnkiConnect/shim use one `addNotes` request per workload.
All comparisons passed the saved-data and returned-data checks.

**Large-media timings need further isolation.** During the 1,000-note run,
shim new-media samples rose from 36.89 s on the first trial to 47.00 s on the
last timed trial. Most profiled time was inside Anki's `write_data` /
`add_media_file`, which all three paths call 2,000 times. This does not establish
why their write times differed. Repeat with reversed implementation order and
check storage behavior before attributing the large gap to routing.

The read profiles identified two changes worth keeping:

- Compatibility responses now encode directly to JSON on the request worker.
  Avoiding FastAPI's extra conversion pass reduced a separate 1,000-card check
  from 144 ms to 119 ms (three repeated trials).
- Simple top-level native selections now use dictionary lookups. A 10,000-card
  comparison with 500-card pages fell from 3.55 s to 2.03 s (five repeated trials).
  Nested selections retain their existing behavior; no collection data is cached.

The full-card native response still costs more than upstream in this fixture.
Typed response construction and serialization remain candidates for investigation.
The shim's attachment validation also repeats collection reads across operation
boundaries to preserve live state and error ordering; those checks remain intact.

The final single-response read was measured at `4f5796e`; the text baseline at
`ba3a1ae` and media workloads at `6626913` use the same write implementation.
Use `--repeats 2 --write-sizes 1000 --workloads add_media_new,add_media_existing`
to reproduce the larger media configuration, or increase repeats for more samples.
