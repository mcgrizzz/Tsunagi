# Full AnkiConnect shim: behavioral coverage

Target: a client can switch from AnkiConnect to Tsunagi's compatibility endpoint
and retain the same observable behavior. Rare actions remain in scope. Native
`/v1` routes have their own contract; passing native filter tests does not establish
AnkiConnect search or RPC parity.

Reference revision: [`de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e`](https://git.sr.ht/~foosoft/anki-connect/commit/de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e).
The [history audit](parity_history_audit.md) records source and commit-history findings.
The [action inventory](ankiconnect_parity.md) records implementations and known deviations;
“implemented” does not mean behaviorally equivalent.

## Measured coverage, 2026-09-07

An opt-in pytest recorder now measures calls reaching the compatibility registry.
The initial full run observed **97 of 120 registered handlers**. `multi` and
`requestPermission` bypass that registry and have separate protocol tests.

That run found 23 handlers with no observed calls, and `modelTemplateRemove` had
only raised errors. New tests exercise `apiReflect`, `deckNameFromId`, and successful
template removal. The reflection tests exposed and fixed omitted-scope behavior,
an extra response key, and parameter-validation error differences. The updated
[122-action matrix](shim_coverage_matrix.md) provides per-action evidence and links
to test files. It includes uncommon and undocumented actions.

Latest run: **99/120 registered handlers observed; 1083 tests passed, 8 skipped,
one expected failure** on the Anki 23.10 test environment, including 195 passing
upstream comparisons across 65 observed action names and the default local-path
gate mismatch. The model/scheduler pass added 38 differential cases and five
standalone regressions, including a native field-rename rendering check. Ruff passes
for the changed Python files. After reload, read-only live checks passed for the
corrected errors, missing IDs, mixed card lists, 1002-note batching and nested deck
names. See the [results](shim_differential_results.md) for the scope and remaining limits.

Execution evidence is a lower bound, not semantic coverage. Tests may mock adapters;
a handler can return false or an embedded error; assertions may cover only part of
the result. Direct adapter tests and earlier manual tests are not counted here.
An optional argument having appeared once does not cover its values or interactions.

Reproduce with the project's test environment:

```sh
python -m pytest -q -p tools.shim_coverage --shim-coverage=/tmp/tsunagi-shim-coverage.json
python -m tools.shim_coverage /tmp/tsunagi-shim-coverage.json docs/shim_coverage_matrix.md
```

The JSON includes individual test IDs, test outcomes, parameter names/types and call
outcomes. It excludes request values. Use a single pytest process. The plugin is
inactive unless explicitly enabled and restores its wrapper when pytest finishes.

## Remaining handlers without observed calls

After adding reflection and deck-name tests, these 21 handlers still need tests
through the compatibility endpoint:

| Group | Actions | Required evidence |
| --- | --- | --- |
| Add/edit dialogs | `guiAddCards`, `guiAddNoteSetData`, `guiEditNote` | Correct dialog, deck/model selection, field/tag replacement and append, media, saving, canceling, focus and dialog reuse. |
| Reviewer | `guiAnswerCard`, `guiCurrentCard`, `guiDeckReview`, `guiPlayAudio`, `guiReviewActive`, `guiShowAnswer`, `guiShowQuestion`, `guiStartCardTimer`, `guiUndo` | Inactive/question/answer states, scheduling and undo effects, timer/audio behavior, identical result/error shapes. |
| Navigation/selection | `guiDeckBrowser`, `guiDeckOverview`, `guiSelectedNotes` | Screen transitions, selection ordering, empty selection, invalid deck and note IDs. |
| Collection/UI lifecycle | `getProfiles`, `loadProfile`, `sync`, `guiCheckDatabase`, `guiImportFile`, `guiExitAnki` | Completion timing, busy/unavailable collection, user cancellation, profile switch/reload, sync authentication/full-sync/error branches, package import and shutdown. |

`guiBrowse`, `guiSelectCard`, and `guiSelectNote` have calls in the test suite but
still need live UI equivalence checks. Mocked forwarding does not prove selection
or focus. Existing manual results should be attached as evidence for individual
cases, not used to mark an entire GUI family complete.

## Known differences to close

These are compatibility debt under the full-shim target, including differences
previously described as intentional improvements. Resolve them in the compatibility
layer where possible so native routes keep their documented behavior. Confirm
upstream behavior on the same Anki version before reproducing an obsolete quirk.

| Priority | Surface | Difference / missing comparison |
| --- | --- | --- |
| 1 | RPC argument binding and errors | Pydantic coercion, ignored extra keys, missing/null/false/empty values, Python argument-binding errors, generic internal-error messages, and malformed request containers need a systematic upstream comparison. Reflection now has focused exact-response tests. |
| 1 | `guiEditNote` | Browser navigation currently substitutes for upstream's standalone editor. This is a user-visible gap, not an acceptable UI equivalence claim. |
| 1 | `answerCards`, `addNotes`, `insertReviews` | Answer prefixes now survive malformed entries and backend undo/redo matches tested success/partial-failure cases. Extend mixed queues, malformed value types and real Qt undo behavior. `insertReviews` is transactional where upstream may leave preceding writes. The existing `addNotes` rollback test covers one failure sequence only. |
| 1 | Media and note probes | Probe media writes now match tested valid/empty/duplicate cases, and null deleteExisting behavior is fixed. Comparisons also cover local URL downloads, base64, scalar/list media, missing fields, skip hashes, collisions and appended decode errors. The default local-path gate remains different (D11); extend failed-download and nested-option coverage. Native media tests alone do not cover shim mapping. |
| 2 | Deck lookup side effects | `getDeckStats`, `cardReviews`, `getLatestReviewID` skip missing decks where upstream creates them. `getDecks` now matches the missing-card fallback. Compare `deckNameFromId` missing-ID fallback too. |
| 2 | Scheduling edge cases | `areDue`/`getIntervals` differ for non-new cards without review history. `suspend` differs for multiple already-matching cards because of upstream's list mutation. Cover duplicate/missing IDs, mixed queues, negative learning intervals, filtered decks, FSRS and legacy scheduler state. |
| 2 | Model mutation | Existing-template cache-only edits, empty template-update saves, field-rename rendering, unmatched replacement saves and creation errors now match tested cases. Extend modification-time, card generation/deletion, field/template ordinal, creation/cloze edge cases and model-conversion comparisons. |
| 2 | GUI transitions and collection lifecycle | `guiDeckReview` avoids upstream's overview transition; `sync` omits an obsolete `mw.onSync()` call. Compare observable behavior on supported Anki versions, including focus, completion timing and errors. |
| 3 | Transport and browser permission | Compare HTTP status/body/headers, API-version envelopes, nested multi/key handling, empty and fragmented requests, UTF-8 byte lengths, CORS/Origin permission persistence and concurrent requests. Existing tests establish local behavior, not equality with upstream's web server. |

Priorities order the work; none removes an action from scope. Exact errors and
side effects belong to the compatibility contract even when the behavior is rare.

## Required cases for every action

Each action needs a case ledger with the request, upstream revision, Anki version,
initial fixture state, expected response, expected side effects and test evidence:

1. Minimal valid request; each optional parameter omitted and explicitly supplied;
   relevant combinations of flags and nested note/media options.
2. Empty, missing, duplicate, unknown and out-of-order IDs; exact output ordering,
   map keys, null/false/empty distinctions and omitted versus present response keys.
3. Malformed values and extra/missing arguments; exact RPC envelope and error text;
   failure before, during and after a multi-item mutation.
4. Persisted state, media files, modification times, undo entries and UI state after
   success and failure. No response-only assertion can establish these effects.
5. Large inputs crossing SQL batch boundaries (including 999/1000), repeated IDs
   across boundaries, and Unicode names, tags, HTML and filenames.

For `findCards`/`findNotes`, compare real Anki search expressions: quoted deck/tag/field
names, escaped characters, parentheses, AND/OR/negation, regex, property/date/review
filters and invalid queries. Check note-versus-card result semantics and ordering.
The six native query families already exercised use a separate filter grammar.

The runtime inventory also found no explicitly supplied `back` argument for
`findAndReplaceInModels` and no `path`/`url` arguments for shim `storeMediaFile`.
Those are concrete missing cases even though both handlers are exercised elsewhere.

## Reference comparison and completion gate

The first differential runner now executes the pinned upstream implementation
against isolated, equivalent collections on the **same Anki version**. See the
[comparison results](shim_differential_results.md): 127 cases cover 45 action names;
126 pass and one records the default local-path gate mismatch. The original ten
differences and the subsequent null-flag/probe-media differences are fixed. Extend this runner
to the remaining cases; these results do not establish complete action coverage.
Run each mutating case on a fresh copy for each implementation. Compare responses
and state changes; normalize only nondeterministic IDs/times with documented rules.
Do not normalize away ordering, missing keys, false/null, errors or side effects.
Do not run either mutating reference against the user's normal collection.

GUI cases need a real Qt window and equivalent disposable profiles. A fake `mw` is
useful for branch tests but cannot establish the standalone-editor experience,
reviewer behavior, import dialogs, audio, shutdown or profile-switch timing.

Completion requires all 122 actions to have reviewed cases and upstream comparison
evidence, all known user-visible differences resolved (or explicitly accepted by
the user), and the collection/GUI cases verified on supported Anki versions. Keep
the pinned reference and history inventory in sync as upstream changes. The current
suite and matrix do **not** yet meet that gate.
