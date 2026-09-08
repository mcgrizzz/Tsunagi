# Upstream differential test results

2026-09-07. The reference is AnkiConnect commit
[`de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e`](https://git.sr.ht/~foosoft/anki-connect/commit/de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e).
Both implementations run against **Anki 23.10, Python 3.12.12**, with the same
seed data and IDs in separate disposable SQLite collections.

The initial run had **76 matches and 14 mismatches in 90 differential cases**.
All ten confirmed differences below are now fixed: **90/90 differential cases pass**,
with their expected-failure markers removed. Ten additional regression cases run
without an upstream checkout and pass on the Python 3.10 / Anki 23.10 test environment.

After the fix, the full suite reports **962 passed, 8 skipped, zero expected failures**
on Python 3.12.12 / Anki 23.10. Ruff and whitespace checks pass for the changed files.
The code is synced and reloaded in the installed addon. Read-only live checks on
`[DEV] Yomine` passed for version argument errors, numeric queries, unprefixed search
errors, null/zero card inputs, mixed valid/zero cards, missing note modification times,
missing-card deck fallback, reflection scope omission, and the 122-action inventory.
A 1002-note request confirmed ordering, missing-note placeholders and repeated card
IDs across the 999-ID boundary. Existing nested deck `TestSuite::Shim` reports leaf
name `Shim`. Default currently contains one card, so its empty-deck omission case
remains covered by the isolated upstream comparison rather than this live check.
No collection data was changed during these live checks.

## Mutation and media follow-up

The suite now contains **127 differential cases across 45 action names**: **126 pass**
and one strict expected failure records the local-path gate described below.
Full suite: **1001 passed, 8 skipped, one expected failure** on Python 3.12.12 /
Anki 23.10. Ruff passes for the changed Python files.
Added comparisons cover media collisions, explicit null deletion flags, skip hashes,
invalid base64, local files, a local HTTP download server, data/path precedence,
note updates, duplicate/missing-ID deletion, addNotes rollback, and probe media
side effects on valid, empty and duplicate notes. Media and note field/tag/card state
are compared in addition to responses. Mutation timestamps and undo state still
require separate comparison; the note-state helper does not assert those fields.

Two more mismatches were fixed:

- **D12:** `storeMediaFile(deleteExisting=null)` now preserves the original file
  and lets Anki choose the collision filename, as upstream does.
- **D13:** all four `canAddNote(s)`/error-detail variants now prepare media before
  the empty/duplicate check, including writing files on rejected probes. No probe
  note is inserted. Media work uses a collection operation; downloads/decode remain
  outside that operation. The standalone regression suite includes these effects.

**D11 remains open:** local-path uploads are blocked by Tsunagi's default
`gates.media_allow_local_path=false`; upstream permits them. The enabled-gate case
passes. A strict expected-failure case records the default mismatch, rather than
changing the live user's configuration. The settings/migration todo includes this
policy decision. This is the only expected failure in the current differential suite.

The original 90 cases below remain passing. After reload, the media/probe fixes also
passed live on `[DEV] Yomine`: `deleteExisting=null` retained the original bytes and
stored the replacement under Anki's collision filename. All four probe actions
wrote the expected media bytes for both accepted and rejected empty notes; searching
the unique probe prefix found no inserted notes. All ten temporary media files were
deleted, and the prefix listing was confirmed empty afterward. The active profile
remained `[DEV] Yomine`; no live configuration gates were changed.

## Model and scheduler follow-up

At this checkpoint: **164 passed, one expected failure in 165 differential cases**,
with 63 distinct action handlers observed. Full suite: **1044 passed, 8 skipped,
one expected failure** on Python 3.12.12 / Anki 23.10. The expected failure remains
D11 (default local-path policy). Changed-file Ruff and whitespace checks pass.

Added 38 differential cases covering template/style edits, field rename/order/add/
remove and metadata, template addition/removal, a no-op model replacement, and scheduling
on new and review cards (ease factors, due dates, forget, relearn, suspend/unsuspend).
These compare model cache contents, persisted models after cache invalidation,
note fields/tags, card scheduling columns and review rows as well as RPC responses.
Five standalone regressions run without the reference checkout.

The pass found and fixed five differences:

- D14: native field renaming left stale template references in the working model.
  Use Anki's rename-and-save helper before applying the final property save. The
  native regression verifies rendering, persisted references and simultaneous font
  changes; the shim continues to call the shared native mutation.
- D15: empty/unknown template updates now save the model as upstream does, including
  its sync metadata side effect.
- D16: adding an existing template changes Anki's model cache without saving it.
  Earlier documentation incorrectly described the change as simply discarded.
  This unusual behavior is isolated in a compatibility adapter; ordinary template
  creation still uses the native method.
- D17: a short ease-factor array now retains prior writes and raises the same
  error at the first present card lacking a factor. Missing cards are skipped
  before the factor lookup. The shim still delegates writes to the native method.
- D18: invalid due-date errors expose the original Anki message through the shim;
  native errors retain their additional context.

This is a focused mutation pass, not complete scheduler/model coverage. Remaining
cases include model creation, more malformed inputs and replacement side effects,
answer/partial-answer behavior, repeated suspension, review insertion and undo/Qt
effects.

After the user reloaded the synced addon, targeted live checks passed on Anki
26.08.1 using a disposable model, two notes/cards and a dedicated deck:

- Native field PATCH rewrote template references and preserved rendered content.
- An empty template update succeeded; adding an existing template immediately
  exposed its changed front through the model-template reader.
- A short ease-factor array returned `list index out of range` and retained only
  the first card's factor change, verified through `getEaseFactors`.
- Invalid due dates returned Anki's exact `invalid` error.

The notes, model, leaf deck and empty parent deck were deleted and cleanup verified.
Cache-versus-disk persistence and model sync metadata remain covered by the isolated
comparisons, not by these live HTTP checks. No additional production changes or
reload were needed after this verification.

## Creation, replacement and partial-answer follow-up

At this checkpoint: **195 passed, one expected failure in 196 differential cases**,
with 65 distinct action handlers observed. Full suite: **1083 passed, 8 skipped,
one expected failure** on Python 3.12.12 / Anki 23.10. D11 remains the sole expected
failure (default local-path policy). Ruff and whitespace checks pass.

Commit `06f9566` adds 31 differential cases: 13 model-creation cases, seven literal
replacement cases, eight answer sequences and three backend undo/redo cases. Eight
additional regressions run without an upstream checkout.

- D19: `createModel` now requires both template sides and returns Anki's model
  validation errors instead of a generic failure. Successful normal/cloze models,
  default/empty/custom CSS, duplicate names, missing sides, empty names and invalid
  templates are compared. Failed creation must leave no model behind.
- D20: `findAndReplaceInModels` now saves every targeted model, including nonmatches,
  and exposes Anki template-validation errors. The shared native method provides
  an explicit `save_unmatched` option; its default still saves only matches. Tests
  compare both template changes and sync metadata, including all-model calls.
- D21: `answerCards` now applies valid entries before a missing key. An invalid
  ease earlier in the sequence takes precedence over a later missing key. Writes
  still use the native scheduler method. Tests compare response errors, card
  state and review rows, including missing cards and duplicate IDs.

Backend undo/redo restores the matching collection state after a successful answer,
a missing-ease failure and an invalid-ease failure. This proves backend behavior
for those cases; real Qt refresh and grouping require separate live checks.

After reload, the installed addon passed the following checks on Anki 26.08.1:

- Missing `Front`/`Back` and an invalid field reference produced the expected
  creation errors, with no failed model left behind.
- An unmatched replacement returned zero; a literal replacement changed the
  template as expected. Sync-metadata equality remains an isolated-test assertion.
- Both missing-ease and invalid-ease failures retained the first valid answer.
  The card review counts were `[1, 0]` after each partial failure, then `[0, 0]`
  after calling the real `/v1/gui:undo` endpoint.
- The two temporary notes, deck and model were removed and their absence verified.

This live pass checks GUI undo through its endpoint, not menu labels, focus or
grouping of longer answer batches. No production edits or further reload were
needed after verification.

## Suspension, review insertion and mixed-queue follow-up

Current result: **249 passed, one expected failure in 250 differential cases**,
covering 66 distinct action handlers. Full suite: **1147 passed, 8 skipped, one
expected failure** on Python 3.12.12 / Anki 23.10. D11 remains the sole expected
failure. Changed-file Ruff and whitespace checks pass.

Commit `c3af5ce` adds 54 comparisons and ten standalone regressions:

- D22: suspension now reproduces upstream's removal from the list being iterated.
  Multiple already-matching cards can return true; a missing ID skipped by that
  iteration is not validated. State lookup remains batched, and actual writes use
  the native suspend/unsuspend methods. Tests cover both directions, duplicates,
  empty/single/multiple lists, mixed states and visited/skipped missing IDs.
- D23: `areDue` and last-only `getIntervals` now report upstream's empty-history
  error for non-new or missing cards. Complete interval history may still be empty.
  Shared native readers retain their default fallback behavior and batching; the
  shim opts into strict history. Comparisons include mixed new/review/learning
  cards, buried/suspended queues, duplicate IDs and negative-interval timing around
  the -1200-second branch threshold. The test clock is fixed for both sides.
- D24: review insertion preserves tested SQLite errors and scalar coercion rather
  than coercing every value to an integer first. Ordinary integer rows still use
  the native parameterized writer. Compatibility-only handling preserves floats,
  numeric strings, booleans, missing/null values, malformed rows and SQLite error
  text/offsets. Executable SQL fragments are rejected before database execution;
  arbitrary SQL-expression values are not covered by this scalar-only contract.

The earlier claim that upstream may retain preceding rows after these insertion
failures was incorrect: its single INSERT is atomic. Comparisons verify the full
revlog contents after successful inserts, duplicate IDs within a batch, conflicts
with existing rows and malformed rows. These match the native transaction's tested
atomic behavior. Review-insertion undo/grouping is not established by this pass.

After reload, live Anki 26.08.1 checks passed for repeated suspension/reversal,
single matching cards, skipped missing IDs, empty-history errors and complete
history, plus integer/scalar duplicate failures and malformed-row errors. Review
rows were checked after every failing insert and remained absent. The temporary
notes, deck and model were removed and cleanup verified. Successful scalar storage
is covered by the isolated real-backend tests; the live pass deliberately used
failing inserts and left no review history behind.

## Shim-only argument binding and missing-deck follow-up

The user confirmed that parity belongs only in the compatibility layer. The prior
`save_unmatched` and `strict_history` switches have been removed from native adapters.
The shim composes ordinary native replacement/patch operations to save unmatched
targets, and derives empty-history errors from complete native history results.
Native reads and unmatched replacements preserve their previous behavior. The
native field-renaming/rendering correction remains a native correctness fix.

This pass adds **241 differential cases**: 122 unexpected-argument checks, 86
missing-required-argument checks, one pinned signature-snapshot check and 32 focused
lookup/binding/value cases. Upstream's HTTP wrapper supplies the two permission
arguments, so the reference harness supplies them for that action too. Client
permission values cannot override Tsunagi's origin gate. Four standalone regressions
cover missing model scope before saves, nested rejected deletion, rejection before
permission prompting and permission-context spoofing.

Missing-deck lookups for `getDeckStats`, `cardReviews` and `getLatestReviewID` now
create decks only in the shim. Tests compare nested/blank/padded names, string
iteration, null errors and creation timing. Native read tests confirm no creation.
The compatibility resolver reports newly created decks through CollectionOp changes.
`areDue` uses one additional batched history read; it does not add per-card queries.

Total: **491 differential cases: 490 pass, one expected failure** for the existing
default local-path policy mismatch. Behavioral calls reach **68 registered handlers**;
binding rejection covers all 122 action names before handler execution. Full suite:
**1392 passed, 8 skipped, one expected failure** on Anki 23.10 / Python 3.12.12.
Ruff and whitespace checks pass. After reload, the live Anki 26.08.1 check
`/tmp/tsunagi-binding-decks-live.py` passed: missing/extra lookup arguments returned
exact errors without creating decks, omitted model scope returned the expected
error, the three missing-deck lookups created the expected parent/leaf decks with
matching stats/empty review results, and null card input returned the expected
error. All four temporary empty decks were removed and their absence verified.
No further reload is pending for this batch. These live checks cover responses
and collection state; they do not establish all Qt refresh or undo behavior.

Remaining binding work includes value coercion, malformed request containers,
nested permission requests and broader ordering/partial-effect comparisons. The
signature table records parameter names, not every value/default semantic.

## HTTP request shapes and multi aborts

This follow-up adds **84 differential cases** and seven standalone regressions.
The reference harness now runs the original upstream HTTP wrapper without opening
a socket. Comparisons exercise null/scalar/list parameter containers through the
shim's real HTTP endpoint, outer action/version/body validation, and schema-error
selection across 784 value/key-order combinations within one test.

The fixed, shallow request schema and its diagnostics live in compatibility code;
native routes and methods do not use it. Diagnostics are compared with
**jsonschema 4.23.0**, installed only in the reference test environment. A snapshot
test detects changes to upstream's schema. The installed addon gains no dependency.
Invalid outer requests now fail before dispatch instead of treating null/false/empty
parameters as an omitted object or coercing an invalid API version.

`multi` now mirrors direct iteration: empty lists, objects and strings produce an
empty result; non-iterable values fail; a non-request child aborts that batch,
preserves earlier writes and prevents later entries from running. A nested batch
returns its own error so its parent can continue. This differs from an ordinary
child action error, which remains an entry in the result array. Tests verify these
responses and deck side effects on separate disposable collections.

Total: **575 differential cases: 574 pass, one expected failure** for the existing
default local-path policy mismatch. Differential calls reach **69 registered
handlers**; overall registry execution remains **99/120**. Full suite:
**1483 passed, 8 skipped, one expected failure** on Anki 23.10 / Python 3.12.12.
Ruff and whitespace checks pass. Artifacts:
`/tmp/tsunagi-request-shapes-full.xml` and `/tmp/tsunagi-request-shapes-coverage.json`.
After reload, `/tmp/tsunagi-request-shapes-live.py` passed on Anki 26.08.1: outer
null parameters returned the exact schema error; empty list/object/string batches
returned empty results; a malformed child retained the preceding deck creation and
skipped the later creation; a nested abort returned its own error while the parent
continued. The uniquely named empty parent and leaf deck were removed and their
absence verified. No further reload is pending for this batch. These live checks
verify responses and collection state, not all Qt refresh or undo effects.

Still unverified or different: malformed JSON/empty-body transport responses,
nested child parameter containers and version coercion, nested permission context,
broader action-value coercion, browser headers and real Qt/undo effects. This batch
does not establish complete request or transport parity.

## Nested parameters, versions and permission context

This follow-up adds **74 differential cases** and **eleven standalone regressions**.
Child parameter containers are no longer replaced with an empty object; known
actions report Python mapping errors, while unknown actions remain unsupported.
Child API versions retain their JSON values. In particular, 4.5 keeps an envelope,
and an invalid version can fail during response formatting after the action has
already written. Tests verify retained deck creation, sibling continuation and
argument errors taking precedence over version formatting.

Only outer permission requests receive HTTP context. Nested calls bind their own
`origin`/`allowed` arguments; missing arguments fail before prompting, truthy allowed
values grant immediately, and false reaches the prompt even for an empty/local
origin. The reference permission action runs unchanged against simulated Qt widgets;
denials and prompt counts are compared. This does not establish real dialog parity,
accepted empty/non-string origin persistence or the ignored-origin checkbox behavior.
Native methods and routes are unchanged.

**Error qualification limit:** Python's non-mapping `**params` error includes the
loaded addon's module name, which depends on its installation. The shim returns
the portable `AnkiConnect.<action>()` portion. These nested comparisons remove only
the reference module prefix for that specific error and compare the remaining text
exactly. They do not establish byte-for-byte equality of the installation prefix.

Total: **649 differential cases: 648 pass, one expected failure** for the existing
default local-path policy mismatch. Differential calls reach **69 registered
handlers**; overall registry execution remains **99/120**. Full suite:
**1568 passed, 8 skipped, one expected failure** on Anki 23.10 / Python 3.12.12.
Ruff and whitespace checks pass. Artifacts: `/tmp/tsunagi-nested-rpc-full.xml` and
`/tmp/tsunagi-nested-rpc-coverage.json`. After reload,
`/tmp/tsunagi-nested-rpc-live.py` passed on Anki 26.08.1: null/list/string/false child
params returned the expected mapping errors while siblings continued; version 4.5
kept its envelope; a null child version failed during formatting after deck creation;
missing permission context failed and explicit allowed context returned the expected
result. Permission cases avoided prompts/configuration changes. The uniquely named
empty parent and leaf deck were removed and their absence verified. No further reload
is pending for this batch. Live dialog, permission persistence and Qt/undo behavior
remain outside these checks.

## Malformed JSON and empty HTTP bodies, 2026-09-08

Added **90 differential cases** against the unchanged upstream HTTP wrapper:
18 raw byte payloads across absent, localhost, extension, denied and explicitly
empty origins. Before the fix, **63 failed and 27 passed**; all 90 now pass.
The harness accepts raw bytes and request headers and exposes response status,
headers and bytes, while retaining its existing decoded-payload convenience API.

Allowed empty POST bodies return `{"apiVersion":"AnkiConnect v.6"}`. Whitespace
is not empty. Malformed JSON, multiline/trailing-data errors, control characters,
invalid UTF-8, UTF-8 BOMs and UTF-16 bodies retain upstream's exact decoder errors.
Decoding explicitly uses UTF-8 rather than Python's byte-input encoding detection.
Denied origins receive an empty 403 even for decoding/schema failures; malformed
`requestPermission` requests cannot bypass that gate. Valid JSON and Unicode
payloads are included as controls. All production changes are confined to the
compatibility POST endpoint; native root GET still redirects to `/docs`.

Eleven standalone regressions cover discovery, exact errors, origin rejection,
Content-Type/charset independence and native root GET. Full suite: **1669 passed,
8 skipped, 1 xfailed** on Anki 23.10 / Python 3.12.12. The differential file has
**739 cases: 738 passed, 1 xfailed**. Observed handler counts remain **69** for
differential calls and **99/120** overall. Ruff and whitespace checks pass.
Artifacts: `/tmp/tsunagi-http-bodies-full.xml` and
`/tmp/tsunagi-http-bodies-coverage.json`.

These cases compare status, decoded JSON (including exact errors), empty response
bytes and JSON Content-Type. They do not establish equality of all CORS/transport
headers, JSON whitespace, preflights, fragmented socket requests or concurrency.
The original upstream wrapper runs without a listening socket.

After the user confirmed the reload of `9d50a0b`, all **26 read-only live checks**
in `/tmp/tsunagi-http-bodies-live.py` passed: discovery, exact parser diagnostics,
allowed/denied/empty origins, invalid permission requests and the native root
documentation redirect. No fixtures, permission dialogs or setting changes were
needed. Before sync/reload, live Anki returned the old generic JSON error for an
empty POST. No further reload or live verification is pending for this batch.

## Permission persistence and Anki 26.08.1, 2026-09-08

Added 79 comparisons in `tests/test_upstream_permissions.py`, executing the
unchanged upstream permission handler with simulated Qt choices and isolated
configuration. Before the fix, 36 failed; all 79 now pass. Thirteen standalone
regressions exercise the HTTP endpoint, persistence across settings reloads,
falsy ignored origins and duplicate acceptance writes without an upstream checkout.

An explicitly empty HTTP Origin now prompts instead of being granted automatically.
The dialog supports **Ignore further requests**: No with the checkbox selected
persists a truthy origin in `ankiconnect_ignore_origins`; closing the dialog or
denying a falsy origin does not. Allowed context takes precedence over the ignore
list. Acceptance appends every origin exactly as upstream does, including repeated
and non-string nested values. Those compatibility semantics remain in the shim;
the native settings helper retains its deduplication contract. Tests compare replies,
prompt counts, persisted snapshots and subsequent requests. No live settings were
changed by these automated comparisons. Live interaction is recorded below.

The full suite now passes on both backends with Python 3.12.12:

| Backend | Passed | Skipped | Expected failure |
| --- | ---: | ---: | ---: |
| Anki 23.10 | 1761 | 8 | 1 |
| Anki 26.08.1 | 1765 | 4 | 1 |

The newer run executes the retention, optimizer and simulator cases unavailable
on 23.10. Its four skips assert 23.10-only behavior. D11 remains the default
local-path policy mismatch. Across both differential files there are **818 cases:
817 passed and 1 expected failure**. Registry execution remains 99/120 overall;
permission and multi actions bypass that registry.

Reports: `/tmp/tsunagi-permissions-full.xml` and `/tmp/tsunagi-26-full.xml`;
coverage: `/tmp/tsunagi-permissions-coverage.json` and `/tmp/tsunagi-26-coverage.json`.
The newer interpreter is `/tmp/tsunagi-26-parity-venv/bin/python`, with
`anki==26.8.1`, `httpx==0.27.2` and `jsonschema==4.23.0`.

The subsequent live empty-origin check exposed an existing timeout lifecycle
bug: an expired HTTP waiter returned denied while its Qt dialog remained open.
The script then opened another dialog. That observation is **not** a successful
live denial/persistence check. Permission timeouts now queue rejection of their
active dialog on the UI thread and suppress an expired callback before it can
open another window. Late dialog results are discarded. The shared native
main-thread operation helper is unchanged.

Two optional real-Qt tests in `tests/test_permission_dialog_lifecycle.py` exercise
an active modal dialog and a request that expires while its UI callback is still
queued. They run headlessly with PyQt6, without loading a real Anki profile.
The live script now sends one prompt per invocation and refuses to count a
response near the timeout as a successful manual click. After the user confirmed
reload, two sequential empty-origin requests returned denied before timeout. The
user confirmed that checking Ignore and selecting No closed the first dialog;
the second request prompted again, as required for a falsy origin. No live settings
were changed. The Windows timeout-expiry path itself remains covered by the
headless Qt tests rather than a manual 120-second wait.

Lifecycle verification on Anki 26.08.1: **1767 passed, 4 skipped, 1 xfailed**,
including both real-Qt tests. The focused Anki 23.10 permission/settings run has
129 passing tests. Ruff and whitespace checks pass. One earlier full run crossed
a one-second review timestamp boundary in the existing undo/redo comparison;
that comparison and the subsequent full run passed unchanged. The comparison
remains strict. Final report: `/tmp/tsunagi-permission-lifecycle-full.xml`.

## Media HTTP failures and nested errors, 2026-09-08

Added 57 upstream comparisons covering HTTP 200, other 2xx responses, redirects,
4xx/5xx failures, invalid URLs, disconnected downloads and escaped errors inside
note fields. The status matrix covers `storeMediaFile`, `updateNoteFields` and
`canAddNote`, comparing both replies and resulting note/media state. Before the
fix, 22 of its 42 cases failed.

The shim now uses Anki's Requests client and accepts only HTTP 200 after redirects,
matching upstream's status and transport-error text. Downloads finish before any
existing file is deleted. Nine standalone regressions check failed replacements,
declared and streamed size limits, and the native API's existing HTTP 201 behavior.
The shim retains Tsunagi's configured download timeout and size limit; these limits
remain deliberate boundaries on the comparison with upstream.

Full verification with Python 3.12.12: **1833 passed, 4 skipped, 1 xfailed** on
Anki 26.08.1 and **1827 passed, 10 skipped, 1 xfailed** on Anki 23.10. The old
environment additionally skips the two optional Qt lifecycle tests. Across both
differential files, **874 pass and 1 remains expected to fail** (D11 local-path
policy). Registry execution remains 99/120 overall and 69 differential handlers.
Ruff and whitespace checks pass. Reports: `/tmp/tsunagi-media-errors-full.xml`,
`/tmp/tsunagi-media-errors-old-full.xml`; registry evidence:
`/tmp/tsunagi-media-errors-coverage.json`. After confirmed reload, a live local
HTTP 404 download returned the upstream error text and preserved an existing
disposable media file. The file was removed and its absence verified afterward.

## Media replacement option values, 2026-09-08

Added 84 upstream comparisons for `deleteExisting` defaults, null, booleans,
numbers, strings and containers, plus matching `skipHash` values. Seventy-two
exercise audio, video and picture attachments through `updateNoteFields` and
`canAddNote`; twelve exercise standalone `storeMediaFile`. Comparisons check
replies and resulting note/media state, including repeated and unknown field names.
Before the fix, 35 cases failed. All 84 now pass.

The shim preserves the raw replacement value so Python truthiness matches upstream.
For example, the nonempty string `"false"` requests replacement; empty lists and
objects do not. The default remains true for standalone storage and falsy for
nested attachments. Matching hashes skip deletion and writing. Ten standalone
regressions verify file contents, returned filenames and probe side effects without
an upstream checkout. These compatibility models do not change native API inputs.

Full verification: **1927 passed, 4 skipped, 1 xfailed** on Anki 26.08.1 and
**1921 passed, 10 skipped, 1 xfailed** on Anki 23.10, both with Python 3.12.12.
Across the two differential files, 958 comparisons pass and D11 remains the sole
expected failure. Registry execution remains 99/120 overall and 69 differential
handlers. Ruff and whitespace checks pass. Reports:
`/tmp/tsunagi-media-options-full.xml`, `/tmp/tsunagi-media-options-old-full.xml`;
coverage: `/tmp/tsunagi-media-options-coverage.json`. After confirmed reload, live
checks passed for nonempty-string replacement, empty-list preservation, nested
replacement and hash skipping. The probe added no note, and all disposable media
files were removed with their absence verified.

## Nested media field selection and storage failures, 2026-09-08

Added 52 upstream comparisons: 44 cover field selections on successful and failed
attachments, four check partial media writes when an error aborts later attachments,
and four inject a storage failure into both implementations. The field-selection
matrix initially had 24 mismatches; all 52 comparisons now pass. Nine standalone
regressions check exact replies, persisted note fields and media contents without
an upstream checkout.

The shim preserves field-selection values and key presence. Successful attachments
append markup only for lists; other selections still allow media storage. Upstream's
error path instead iterates the provided value and can abort on a missing or
noniterable selection. Download and storage errors share that path, with HTML
escaping applied once. If a later attachment aborts, earlier media writes remain
and later attachments are not written. Native note/media operations are unchanged.
An older standalone test explicitly expected suppression of upstream's missing
`fields` error. It now requires that error and verifies that no note is added.

Full verification: **1988 passed, 4 skipped, 1 xfailed** on Anki 26.08.1 and
**1982 passed, 10 skipped, 1 xfailed** on Anki 23.10, both with Python 3.12.12.
Across the differential files, 1010 comparisons pass and D11 remains the sole
expected failure. Registry execution remains 99/120 overall and 69 differential
handlers. Ruff and whitespace checks pass. Reports:
`/tmp/tsunagi-media-fields-full.xml`, `/tmp/tsunagi-media-fields-old-full.xml`;
coverage: `/tmp/tsunagi-media-fields-coverage.json`. Live field-selection checks
await reload confirmation.

## Method and limits

[upstream_reference.py](../tools/upstream_reference.py) verifies the checkout's HEAD
and rejects tracked plugin modifications. It loads upstream's original action class,
utility functions, HTTP wrapper/schema and RPC response formatters without opening
a listening socket or starting its UI.
Collection access, edit notifications, logging and addon configuration are supplied
by the harness. API settings use upstream defaults. No action implementation is
rewritten or copied into a hand-maintained mock.

[test_upstream_differential.py](../tests/test_upstream_differential.py) compares the
RPC dispatchers' JSON-compatible output, including list order, duplicate IDs,
response keys and exact errors. It also checks persisted tag/queue changes and
media file contents/deletion. Native Anki collection methods use the real Rust
backend. Each case starts from freshly seeded and cloned collections. No live user
collection is opened by this suite.

The request-shape and raw-body cases also compare the original HTTP wrapper
against Tsunagi's HTTP endpoint. Raw-body cases use stateless actions and do not
need cloned collections. These are not socket-transport, browser permission or real Qt tests.
The fake main window and suppressed edit notifications
cannot prove GUI undo, refresh, focus or dialog behavior. Backend undo/redo has
separate comparisons described above. The full automated suite now runs on
Anki 26.08.1 as well as 23.10; this still does not establish complete compatibility.
The initial collection is cloned so requests address identical IDs. RPC responses
are compared without normalization except deck-stat IDs and successful model creation.
Nested non-mapping argument errors also omit the installation-specific reference
module prefix, as detailed above; all other error text remains compared.
Deck-stat response keys and `deck_id` values are resolved to full deck names because
missing-deck lookups allocate IDs independently; all other stats remain compared.
For successful model creation, independently
allocated model/field/template IDs and model modification timestamps are normalized,
with the returned schema and other values retained. Answer tests hold measured
review time at zero in both implementations. Model/scheduler state comparisons exclude
model modification timestamps and field/template IDs allocated independently by
Anki; new cards are matched by note ID and template ordinal. Sync metadata is
retained. Existing note/card/media comparisons keep their original strict checks.

## Fixed differences

These were the ten differences observed before the fix. The shim now matches the
upstream column for every listed trigger. Compatibility-specific collection reads
live in `tsunagi/adapters/anki/compat.py`; native search validation and deck statistics
keep their existing contract. Broader argument binding/coercion across other actions
remains a separate coverage task; D06 specifically verifies `version`.

| ID | Trigger | Shim | Upstream |
| --- | --- | --- | --- |
| D01 | `getDeckStats` for an empty Default deck alongside a populated child deck | Includes Default's statistics | Omits Default |
| D02 | `findCards` / `findNotes` with `(` or `prop:ivl=nope` | Prefixes the Anki error with `Invalid Anki search: ` | Returns Anki's error without that prefix |
| D03 | `notesModTime` with a missing note ID, including zero | `{"noteId": id, "mod": null}` | `{}` |
| D04 | `cardsInfo` list containing card ID zero | Entire request returns `Action failed` | Returns valid cards and `{}` for zero |
| D05 | `notesInfo` with the same note repeated across the 999-ID batch boundary | One card ID in each note's `cards` list | Repeats that card ID once per relevant batch |
| D06 | `version` with an unexpected argument | Ignores the argument and returns 6 | Python unexpected-keyword error |
| D07 | `findCards` with numeric `query: 123` | Coerces to text and returns an empty result | Rejects the non-string query |
| D08 | `cardsInfo` with `cards: null` | Pydantic validation error | `'NoneType' object is not iterable` |
| D09 | `getDecks` with a missing card ID | Empty map | Groups the ID under Default |
| D10 | `getDeckStats` for `Parity::日本語` | Name is `Parity::日本語` | Name is `日本語` |

D05 reproduces an upstream batching quirk; it is still a visible response difference.
D04 is specifically triggered by zero: a separate 1002-entry `cardsInfo` case with
a positive missing ID matches upstream. D03 also reproduces with a positive missing
ID. Passing large-list tests that omit these combinations would miss these gaps.

## Matching cases

The matching cases include the corrected `apiReflect` responses/errors; API versions
1, 4, 5 and 6; model metadata; ordinary card/note reads; tag additions/removals;
suspension and unsuspension; and base64 media storage, retrieval, listing and deletion
with actual file checks. Search cases include Unicode deck names, hierarchical tags,
negation, nested AND/OR, field regex, queue/property filters and review/date filters.

The initial requests exercised 37 existing action names, with multiple calls in the media and
suspension cases. This is a first differential suite, not proof that those 37 actions
are complete or that all 122 actions match. Error-only equality also does not establish
a successful path. Further media failures/options, advanced scheduler state, mutating model/note
operations, GUI, lifecycle, transport and other supported Anki versions remain in the
[full coverage plan](shim_behavioral_coverage.md).

## Reproduction

Use Python 3.12 or newer because the pinned upstream source uses Python 3.12 f-string
syntax. Install the project's test dependencies with `anki==23.10`, `httpx<0.28`
and `jsonschema==4.23.0` in the reference test environment.
The repository's vendored runtime dependencies must already be built.

```sh
TSUNAGI_ANKICONNECT_CHECKOUT=/tmp/tsunagi-anki-connect-audit \
  python -m pytest -q tests/test_upstream_differential.py tests/test_upstream_permissions.py
```

One strict expected-failure marker remains for D11; use `--runxfail` to reproduce
the default local-path mismatch as an ordinary test failure.
Omit the environment variable to skip these optional comparisons;
the ordinary test suite does not require an upstream checkout. The complete run's
JUnit artifact for the mutation/media follow-up is `/tmp/tsunagi-mutation-media-full.xml`.
