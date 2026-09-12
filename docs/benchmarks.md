# API benchmarks

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

Bulk fixtures use Basic notes with one card each, no review history, and synthetic
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

## Workflows that combine related answers

These cases compare several AnkiConnect actions with one native request. Run
both separate-action and `multi` variants; batching is available to AnkiConnect
clients too.

```sh
python tools/benchmark_compat.py \
  --checkout /path/to/anki-connect \
  --workloads model_fields,model_fields_multi,duplicate_ids,duplicate_ids_multi,duplicate_mixed_multi,save_card_ids \
  --workflow-sizes 10,100 --repeats 5 \
  --output /tmp/tsunagi-related-workflows.json
```

| Needed result | AnkiConnect and shim | Native Tsunagi |
| --- | --- | --- |
| Every model's ID, name and ordered field names | `modelNamesAndIds`, then `modelFieldNames` for each model | `GET /v1/models?select=id,name,fields[].name` |
| Each candidate's duplicate status and matching note IDs | `canAddNotesWithErrorDetail`, then `findNotes` for each duplicate | `POST /v1/notes:check` |
| A newly saved note's ID and generated card IDs | `addNote`, then `findCards` using the returned note ID | `POST /v1/notes` |

`_multi` batches the field or duplicate-ID lookups into the second HTTP request.
The initial action must finish first because its result determines those lookups.
The report counts child actions separately from HTTP requests; the `multi`
wrapper is not an additional child action.

Model fixtures contain exactly the requested number of Basic-derived note types.
Duplicate fixtures use distinct first-field values and collection-wide duplicate
checking. `duplicate_ids` checks already-saved words; `duplicate_mixed_multi`
alternates duplicates and new words. The AnkiConnect lookup uses an exact regular
expression on the first field within Basic. This is a controlled equivalent
workflow, not a reproduction of every Yomitan search option or optimization.

`save_card_ids` always saves **one** Basic (and reversed card) note, generating two
cards. It models one add-button click, not a bulk insertion. All returned card IDs
must belong to the created note. IDs, model fields and duplicate states are
checked against the collection outside the timer; native's extra response data
is still included in the timed serialization and decoding.

The native model request omits `limit` to get every model in one response. All
workflows retain the same fresh-collection and sequential-run rules as the bulk
cases above. These timings do not include network round trips; fewer requests
are recorded as a separate benefit, without assigning them an invented latency.

## Read the report

The JSON report contains:

- First-use and repeated timings, per-request timings, response sizes and throughput.
- HTTP request counts and API action counts, including children of `multi`.
- Median, minimum and maximum repeated times; raw samples remain available.
- Anki API calls, backend calls, fake Qt dispatch counts and the most expensive Python functions
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

## Related-workflow findings — Anki 26.8.1 / Python 3.12.12

Five repeated samples per implementation, plus a separate first-use and profiling
trial. Every trial passed the result checks. An eight-case Anki 23.10 smoke run
also verified the new workflows and existing card-read/text-create paths.
The table uses AnkiConnect's `multi`
variant where available, so all three columns compare **two HTTP requests versus
one native request**, rather than assuming every child action needs a round trip.

| Task | Items | AnkiConnect | Shim | Native |
| --- | ---: | ---: | ---: | ---: |
| Duplicate status + IDs (`multi`) | 10 | 4.8 ms | 4.3 ms | 2.0 ms |
| Duplicate status + IDs (`multi`) | 100 | 36.3 ms | 30.3 ms | 13.2 ms |
| Half duplicate, half new (`multi`) | 10 | 3.1 ms | 3.2 ms | 2.1 ms |
| Half duplicate, half new (`multi`) | 100 | 20.3 ms | 16.6 ms | 10.8 ms |
| Models + field names (`multi`) | 10 | 2.0 ms | 1.6 ms | 2.6 ms |
| Models + field names (`multi`) | 100 | 8.3 ms | 3.8 ms | 16.6 ms |
| Save one note + its two card IDs | 1 | 6.3 ms | 6.3 ms | 6.2 ms |

**Duplicate checks show a processing benefit as well as fewer requests.** For
100 duplicates, native takes about 64% less time than upstream's `multi` flow in
this harness. All three still validate 100 candidates and perform 100 duplicate-ID
searches. Upstream resolves the model and deck 100 times each; the shim does that
twice because it validates in chunks of 64; native does it once for the batch.
The native response also avoids dispatching 100 separate `findNotes` actions.
Without `multi`, the upstream check-and-ID workflow takes 93.5 ms and 101 requests.

**Model reads save Anki calls, but native processing is still too expensive.**
For 100 models, upstream makes 200 model-name-to-ID lookups, the shim makes 100,
and native makes none. Each implementation loads 100 model records. Native still
loses to `multi`: building and converting Pydantic objects and evaluating the
nested `fields[].name` selection outweigh those savings. The profile records
7,208 `_get_value` calls, 402 `validate_model` calls and 2,400 glom `_glom` calls
on the native path. These counts identify work to investigate; they are not
additional database queries. Separate upstream field requests take 58.2 ms, but
that comparison alone would hide the better `multi` option.

**Saving one note is roughly tied in processing time.** Native saves one request
and returns both generated card IDs directly. Its path also reloads the saved
note to report persisted values; that correctness step remains included. The
small timing difference does not establish a speed win.

These are headless results. Real Qt dispatch and socket measurements may change
the balance: native's 100-model read uses two fake QueryOp dispatches versus 101
for the shim. The harness counts them but does not reproduce their desktop cost.
Changing implementation order reproduced the same conclusions: 100 duplicates
took 13.0 ms native versus 35.2 ms upstream; 100 models took 16.2 ms native
versus 7.9 ms upstream, both using `multi` on the AnkiConnect side. Single-save
medians rounded to 6.4 ms for all three.

Raw reports: `tsunagi-related-workflows.json` and the separately ordered check
`tsunagi-related-workflows-reordered.json`. For the second run, use the command
above with `--workloads model_fields_multi,duplicate_ids_multi,save_card_ids`
and `--implementations native,shim,upstream`, and change the output filename.

## Next overhead investigations

1. **Avoid repeated response conversion.** Native reads currently pass through
   Pydantic conversion, projection, envelope construction and FastAPI response
   handling. Measure which passes can be removed while keeping validation,
   human-readable field names and JSON behavior identical.
2. **Avoid constructing unused model data.** A field-name picker should not pay
   to build and convert template/style response objects it never receives.
   Preserve the shared query machinery and the current Anki source of truth.
3. **Speed up common nested selections.** Simple scalar selections already use
   direct dictionary lookups. Check whether common array projections can have a
   similarly small fast path, keeping aliases and missing-field behavior intact.
4. **Measure real operation dispatch.** The headless harness cannot tell us how
   much time is spent queueing work through Anki's QueryOp/CollectionOp. Measure
   that before combining dispatches or changing hydration chunk sizes.

Native batch creation and media-plus-note requests could reduce per-note request
costs too, but need deliberate API and failure/undo semantics. They are separate
from eliminating overhead in existing endpoints. None of these proposals relies
on keeping a cached copy of collection results.
