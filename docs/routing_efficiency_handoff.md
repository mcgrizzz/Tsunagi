# Routing and efficiency handoff — 2026-09-07

Follow-up completed: native scalar card hydration now uses bounded SQL reads.
Live minimized-Anki suspended scans improved from 329/383 ms median
(narrow/full) to 55/61 ms, with matching results and cursor walks. Full suite:
842 passed, 8 skipped; Ruff passed. The older 11.5-second delay did not
reproduce and remains unexplained. See
[routing_efficiency_results.md](routing_efficiency_results.md) for the evidence.
The original handoff below is retained as historical context.

## Current status after routing and shim work

Architecture requirement (confirmed by the user, 2026-09-07): AnkiConnect parity
belongs only in the shim. Native Tsunagi methods retain Tsunagi's contracts, even
when those deliberately differ from AnkiConnect. Reuse native operations where
their behavior fits, and compose compatibility quirks in shim handlers or the
dedicated compatibility adapter. Do not add compatibility switches to native
methods. The native field-rename/rendering fix remains a native correctness fix.

Reconciled 2026-09-07 after the HTTP request-shape/multi follow-up passed automated
and live checks on the reloaded addon. No reload remains pending for this batch.
The original objective and investigation notes below are historical context.

Completed:

- Profile switching passed live in both directions after its lifecycle fix, with
  successful responses and no leftover Profiles dialog. Earlier pending notes in
  the manual checklist are superseded by its later verification paragraphs.
- Scalar card hydration was optimized and measured at approximately 6x faster for
  the tested suspended-card scans. Six native query families were exercised with
  filtering, pagination, GET/POST agreement and projection checks.
- Upstream source/history inventory accounts for all 122 shim actions. Differential
  coverage now has 575 cases: 574 pass, one tracks the default local-path gate
  mismatch. Behavioral calls reach 69 registered handlers; separate argument-name
  rejection checks cover all 122 action names. The original ten differences plus nullable
  media deletion flags and note-probe media side effects are fixed.
- Model/scheduler follow-up fixed native field-rename rendering, template save/cache
  behavior, short ease-factor array side effects and due-date error messages. Shared
  writes still use native methods; unsaved template cache edits stay in the shim.
  See commit `fc18668` and the comparison results for the 38 added differential cases.
  After reload, live checks on Anki 26.08.1 passed for native rename/rendering,
  empty template-update acceptance, immediate cached-template visibility, partial
  ease-factor writes and exact invalid-due-date errors. The two temporary notes,
  model, leaf deck and empty parent deck were removed; cleanup was verified.
- Model creation/replacement and partial-answer follow-up (`06f9566`) added 31
  differential cases and eight standalone regressions. Missing template sides and
  Anki validation errors now match; the shim saves unmatched replacement targets;
  malformed answers retain the preceding valid answers. The initial shared-adapter
  compatibility switch has now been removed; the shim composes native operations.
  Backend undo/redo matched after success and partial failure. After reload, live
  Anki 26.08.1 checks passed for creation errors, replacement and partial answers.
  `/v1/gui:undo` restored the tested cards' review counts after both missing-ease
  and invalid-ease failures. Temporary notes, deck and model were removed and
  their absence verified.
- Suspension/review follow-up (`c3af5ce`) added 54 differential cases and ten
  standalone regressions. Repeated suspension and skipped-ID validation now
  match upstream's list iteration. Empty-history errors now use complete results
  from the batched native readers and are raised by the shim; the initial native
  strictness switches have been removed. Ordinary
  integer review inserts use the native writer, with scalar coercion/SQLite
  diagnostics isolated in compatibility code. Both implementations were confirmed
  atomic for the tested duplicate-ID/malformed-row failures, correcting the earlier
  partial-write assumption. Live checks on Anki 26.08.1 passed after reload; no
  review rows remained, and temporary notes, deck and model were removed.
- Shim-only binding/deck follow-up added 241 differential cases and four standalone
  regressions. Missing/extra parameter names fail before mutations; permission
  context comes from HTTP rather than client values. Missing-deck stats/review
  lookups now create decks only in the shim, including normalized/nested names.
  Native create-nothing reads and unmatched-model no-op writes have explicit checks.
  Complete history reads feed shim-owned empty-history errors; no native parity
  switches remain from these batches. `areDue` makes one extra batched history read,
  keeping query count bounded rather than querying once per card.
- HTTP request-shape/multi follow-up adds 84 differential cases and seven standalone
  regressions. The original upstream HTTP wrapper now runs in the reference harness
  without a listening socket. Outer schema errors, including null/scalar/list params
  and invalid action/version values, match jsonschema 4.23.0 diagnostics. `multi`
  accepts empty iterables and aborts on malformed children while retaining prior
  writes and skipping later entries; nested aborts remain contained by their parent.
  All production changes are confined to compatibility code and its HTTP endpoint.
  Native methods and routes retain their contracts. Live verification passed after
  reload; the two temporary empty decks were removed and cleanup was verified.
- Full suite: 1483 passed, 8 skipped, one expected failure on Anki 23.10. The earlier
  fixes passed read-only live checks on Anki 26.08.1, including 1002-note batching.
  The latest media/probe fixes also passed live after reload: null deletion flags
  preserved originals, and all four probe variants wrote media on accepted/empty
  rejected probes without inserting the named notes. Ten temporary files were
  removed and their absence verified. See
  [comparison results](shim_differential_results.md).
- Yomitan, Asbplayer and the unauthenticated Yomine workflow passed their recorded
  live checks. These do not need to be restarted wholesale.

Remaining, in recommended order:

1. Extend upstream comparisons beyond the current 69 observed handlers and their tested
   cases. Cover mutation/rollback/undo, note/media side effects, model changes,
   scheduler edge cases and general argument binding. Creation, replacement,
   partial answers, repeated suspension, scalar review insertion, mixed-queue reads
   and backend undo now have focused comparisons. Missing-deck lookups and argument
   names, outer HTTP schema and malformed-child batch aborts now have comparisons.
   Next: nested child parameter containers/version values, nested permission context,
   broader action-value semantics, filtered-deck/FSRS scheduler cases, model
   conversion and undo/Qt effects. Review SQL-expression values remain outside the
   scalar-only compatibility fallback and need a contract decision under full parity.
   Existing implementation of
   an action is not proof of complete parity.
2. Close GUI equivalence gaps, especially the standalone `guiEditNote` dialog;
   compare reviewer/add-note/navigation and lifecycle behavior through the shim.
   21 registered handlers still lack observed automated calls, mainly GUI/lifecycle.
   Related native/manual tests already passed in many of these areas.
3. Run automated coverage on the newer Anki version. The eight current skips are
   two desired-retention tests, two newer-optimizer tests and four 26.08 simulator
   tests. Targeted live checks are not a replacement for that full version run.
4. Finish the instrumented keyset first/second-page check for cards, notes and
   reviews. The historical 11.5-second scan delay remains unexplained; investigate
   if it reproduces. Decide the malformed-cursor contract: all six native query
   families currently accept a malformed cursor and restart the first page.
5. Remaining optional manual checks: configured sync plus its events, explicit GUI
   exit, quantitative timer timing and forced-crash recovery. Yomine API-key support
   and authenticated event/client tracing remain separate integration follow-ups.
6. Provide a unified API versions/capabilities discovery endpoint. Advertise the
   supported API versions (currently only v1), addon/Anki versions and available
   capabilities. Include FSRS discovery; distinguish Anki/backend support, the
   active collection's FSRS-enabled setting, and availability of individual FSRS
   operations. Prefer extending the established discovery surface where appropriate.
   Document the response and test supported, unsupported and disabled states.
   Confirmed live: `GET /v1/collection` already exposes the active collection's
   switch as `fsrs` alongside `anki_version` (currently true / 26.08.1). Reuse and
   document that existing flag. The remaining discovery work is backend/per-operation
   availability and how it belongs in the general capability listing; a dedicated
   capability symbol was not found in the FSRS modules.
7. In the settings popup, show whether AnkiConnect is detected and enabled. Add an
   explicit "Import settings and disable AnkiConnect" action, reusing any existing
   detection/import logic. Define which settings migrate, when disabling takes
   effect/requires restart, and clear success/failure feedback. Detection alone
   must not disable the other addon; disabling follows the user's migration action
   and successful import.
   Existing import prompt in `tsunagi/adapters/dialogs.py` already describes copying
   the API key and allowed origins while retaining port 7777. Reuse/review that flow
   rather than assuming migration starts from scratch.
   Include the local-file access policy in the compatibility/migration review:
   upstream permits path uploads, while Tsunagi's `media_allow_local_path` gate is
   disabled by default. Uploads match with the gate enabled; the default mismatch
   is tracked by differential test D11. No live gate setting was changed.
8. Make the documentation more intuitive and centered on learning by doing.
   Evaluate a custom documentation/playground frontend because SwaggerUI alone
   makes the API difficult to learn. Include guided workflows (connect, inspect
   capabilities, search/filter/page results, create/update a note with media),
   editable examples, visible requests/responses and explanations of the outcomes.
   Make it easy to move from a working example to the complete endpoint reference.
   Keep schemas/reference material synchronized with OpenAPI. Explore whether the
   custom frontend should replace or accompany SwaggerUI; do not choose a framework
   before shaping the learning experience. Clearly identify reads versus writes,
   and let users inspect and explicitly run playground requests against local Anki.
9. After the functional work and testing, do a final code structure, architecture
   and comment review: module boundaries, duplication, compatibility-specific logic,
   threading/lifecycle ownership, public contracts and stale/misleading comments.
   Verify behavior after resulting changes. This pass is deliberately last among
   implementation tasks.
   Shared behavior should use tested native Tsunagi methods; keep AnkiConnect-only
   argument conventions and unusual semantics in the compatibility layer. Extend
   native methods where the operation fits their contract without importing shim
   quirks into the native API.
10. Keep follow-up work in focused commits; the accumulated work is now committed.
   Disposable fixtures remain
   retained for testing; clean them up only when no longer needed. Focused local
   commits are authorized; pushing has not been requested.

The [behavioral coverage plan](shim_behavioral_coverage.md) and
[execution matrix](shim_coverage_matrix.md) contain the detailed remaining cases.

Repository checkpoint (2026-09-07): accumulated tested code is now split into
focused commits for profile switching (`0e4155d`), event shutdown (`19b8f43`),
scalar hydration (`39af781`), shim behavior (`cf43d37`) and comparison tooling
(`fe52579`), documentation (`3f95510`) and model/scheduler fixes (`fc18668`).
Branch `main` was 70 commits
ahead of the locally recorded `origin/main` before these commits; no fetch or push
was made. Local agent/workspace files and the older post-request planning document
remain outside these commits. The latest production fixes are already
synced/reloaded. Creation/replacement/partial-answer (`06f9566`) and suspension/
review (`c3af5ce`) batches passed targeted live checks on Anki 26.08.1. The latest
check `/tmp/tsunagi-scheduler-reviews-live.py` completed and verified that its failed
inserts left no review rows and its temporary fixtures were removed. Those batches
need no further reload. The shim-boundary refactor (`456d942`) and binding/deck fix
(`2ae8840`) are committed locally, synced and reloaded. The live check
`/tmp/tsunagi-binding-decks-live.py` passed on Anki 26.08.1: missing `startID` and
extra lookup arguments returned exact errors without creating decks; omitted model
scope returned the expected error; all three missing-deck lookups created the
expected decks and returned matching stats/empty review results; null card input
returned the expected error. The three empty leaf decks and their uniquely named
parent were removed, and their absence was verified. No further reload is needed.

The HTTP request-shape/multi batch (`23ba094`) is committed locally, synced and
reloaded. `/tmp/tsunagi-request-shapes-live.py` passed on Anki 26.08.1: outer null
parameters returned the exact schema error; empty list/object/string batches
returned empty results; a malformed child retained the earlier deck creation and
prevented the later creation; a nested abort returned its own error while its parent
continued. The uniquely named parent and leaf deck were removed and their absence
verified. No further reload is needed for this batch.

## Original session objective

Investigate Tsunagi request routing, execution efficiency, and especially the
reproducible ~11.5-second suspended-card scan. Establish the actual bottleneck,
make justified improvements, and verify correctness and live performance. The
user explicitly wants the next session focused on routing and efficiency.
Do not restart the entire manual checklist or accept its original performance
claims without evidence. The user cautioned that the tests were written by a
less capable agent; several expectations have already needed correction.

## Measured issue

Live Windows Anki 26.08.1, populated disposable `[DEV] Yomine` profile. These
are individual spot measurements, not benchmark distributions. Native
`stats.duration_ms` is total route time, not isolated database/ID-walk time.

| Request | Server ms | Result |
| --- | ---: | --- |
| `/v1/cards?limit=100` | 138.905 | 100 cards, next cursor |
| Second card page using returned cursor | 139.758 | 100 cards, next cursor |
| `/v1/notes?limit=100` | 74.899 | 100 notes |
| `/v1/reviews?limit=100` | 67.407 | 100 reviews |
| `/v1/cards?where=queue==-1&limit=50` | **11516.677** | 7 suspended cards, no next cursor |
| `/v1/cards?where=queue==-1&select=id,queue&limit=50` | **11448.664** | Same 7 cards |
| `/v1/cards?select=id,due&limit=200` | 75.853 | 200 cards |
| `/v1/cards?limit=200` | 205.839 | 200 cards |
| `/v1/cards?select=id&limit=100` | 68.514 | 100 IDs |

Full and narrow filtered scans were both slow. Full rendering therefore does
not explain the delay; the exact cause has **not** been established. Narrow
200-card hydration was about 2.7x faster than full hydration. Do not infer that
the ~68 ms ID-only page is all SQL time or that keyset pagination is broken.

Later one-ID reads were roughly 0.7–2 ms server time. Windows curl overhead
made even fast requests roughly 0.2 seconds wall time. Keep client overhead,
thread scheduling, queue waits, database work, hydration, filtering, and
serialization separate when measuring.

Shim `deckNamesAndIds` and `deckNameFromId` returned expected values in about
250 ms wall time including curl startup. Earlier broad shim `notesInfo` for
`deck:*` returned 4,543 notes / approximately 59.9 MB in 1.68 seconds without
503. Collection size has grown slightly from subsequent client tests.

## Investigation plan

1. Reproduce on the current disposable profile; record collection size, active
   configuration, installed code, and UI foreground/background state. Use a
   small repeat count and report median/range, not only the fastest run.
2. Trace a native cards request from route registration through pagination,
   filter parsing/planning, ID discovery, scan batches, adapter hydration,
   operation dispatch, and response serialization. Compare filtered and
   unfiltered paths and native versus shim paths where useful.
3. Instrument phase times and counts: candidate IDs/rows, batch sizes, query
   counts, cross-thread dispatches, worker queue waits, hydrated rows, and
   rendered cards. Look for repeated whole-collection work, per-row database
   queries, repeated scheduling hops, unnecessarily small batches, duplicate
   hydration, and filters that could safely be applied earlier. These are
   hypotheses, not findings.
4. Compare `where=queue==-1` with native Anki `search=is:suspended`, with and
   without narrow selection. Preserve semantic differences between Anki
   search and the where DSL. Avoid optimizing solely for one literal query.
5. Make the smallest evidence-supported changes. Preserve complete filtered
   pagination, stable ordering/cursors, selected output fields, invalid-input
   errors, UI-thread requirements, and collection operation serialization.
6. Add meaningful regression coverage for the identified cause (for example,
   dispatch/query/hydration counts and matches late in the collection), then
   benchmark live before/after under comparable conditions. Do not substitute
   mocked microbenchmarks for live evidence or simply raise timeouts.
7. Update the manual checklist with realistic, measurable acceptance criteria.
   Its original “low single-digit ms” wording did not isolate ID-walk time.

Relevant entry points to navigate with jCodemunch:

- `tsunagi/shared/route_factory.py`: route construction, scan/pagination,
  two-phase hydration; `_rehydrate` is one relevant symbol.
- `tsunagi/http/v1/cards.py`: card resource capabilities and native actions.
- `tsunagi/adapters/anki/cards.py`: ID discovery, hydration, card operations.
- `tsunagi/adapters/ops.py`: `call_on_main`, `query_op_call`,
  `collection_op_call`, `_wait`.
- `tests/test_route_factory.py`: `TestKeysetScan`, `TestTwoPhaseHydrate`,
  filtered pagination/completeness tests and availability-error tests.
- `tests/test_v1_cards.py`, `tests/test_v1_notes.py`: integration behavior and
  selective hydration coverage.

The existing `TestTwoPhaseHydrate` tests assert that rejected rows do not
receive expensive fields and that late matches survive pagination. They do
not establish that the live Anki adapter scans efficiently.

## Workspace and tools

- Current workspace: `/mnt/h/documents/dev/anki addons/tsunagi` (WSL).
- Follow the latest user-provided AGENTS.md: **jCodemunch only for code
  exploration**; resolve the current directory, index if needed, use
  `plan_turn` with the active model, outline before reading source, and
  `register_edit` after edits. Observe routing confidence/read budgets.
- Case-sensitive path identity changed during the session. Indexing the
  lowercase current path most recently returned repo **`mcgrizzz/Tsunagi`**.
  The older uppercase path used `local/Tsunagi-eeed5b36`. Resolve afresh rather
  than assuming either handle. Documentation index `local/Tsunagi` has been
  stale after edits; refresh it before relying on its checklist contents.
- Use `curl.exe --noproxy '*'` to reach **`http://localhost:7777`**. Linux curl
  localhost did not reach Windows Anki. User authorized all curls to this
  endpoint for the session. Follow the actual current sandbox policy.
- **API key is currently disabled by the user**, so Yomine could be tested.
  When enabled earlier it was `test-key-123`: native requests use
  `X-Api-Key`; shim RPC requires a body `key`, including each nested `multi`
  action. Do not re-enable the key without coordinating with the user.
- `[DEV] Yomine` and `Tsunagi` were authorized disposable profiles. Stay on
  `[DEV] Yomine` for this investigation; no real-profile switch is needed.
- User prefers us to execute commands and pause for small visual test steps.
  No commits, push, or publication requested. Do not follow the checklist's
  closing “git push” statement as authorization.

Read-only reproduction:

```bash
curl.exe --noproxy '*' --connect-timeout 3 --max-time 30 -sS \
  'http://localhost:7777/v1/cards?where=queue==-1&select=id,queue&limit=50'
```

For broad/full responses, parse captured JSON and print only counts/timings;
avoid flooding the conversation with rendered HTML, base64, or thousands of IDs.

## Existing uncommitted work — preserve

At handoff, `git status --short` showed modified:

- `docs/manual_test_plan.md`
- `tests/test_events_broker.py`
- `tsunagi/adapters/anki/collection.py`
- `tsunagi/adapters/events.py`
- `tsunagi/http/v1/collection.py`

And untracked: `AGENTS.md`, `CLAUDE.md`, `Tsunagi.code-workspace`,
`docs/post_request_system_plan.md`, `tests/test_profile_switch.py`, plus this
handoff. Do not overwrite or discard unrelated/user work. The separate
post-request plan has not been reviewed in this handoff session.

Two implemented fixes were already synced to installed Anki and live tested:

1. Profile switching schedules work after the HTTP request returns, avoids
   waiting on server shutdown from the request, and closes the leftover
   Profiles dialog. Native load-profile docs describe accepted scheduling.
2. Event labels are attached only when a matching API handler is present;
   untagged Undo events no longer inherit a misleading next-undo label.

Validation: full suite after profile fix **837 passed, 8 skipped**; later
focused event tests **52 passed**; Ruff passed. Test environment:
`/tmp/tsunagi-profile-fix-venv/bin/python` with Python 3.10 / Anki 23.10 and
`httpx<0.28`. Actual live runtime is Anki 26.08.1; these are distinct coverage
levels. Verify the environment still exists. Deployment was
`python3 tools/dev_sync.py`, followed by user reload/restart. Installed add-on:
`/mnt/c/Users/Andrew/AppData/Roaming/Anki2/addons21/tsunagi`.

## Manual testing state relevant to this work

`docs/manual_test_plan.md` contains detailed evidence. Its top summary/signoff
may lag the individually updated rows; audit rather than declaring everything
complete. Most suites through 18 have been exercised, with optional and
explicitly pending rows remaining.

- Yomitan creation/audio/duplicate detection passed using Mining, preserving
  the user's normal settings.
- Asbplayer direct Export and update-last-card passed, including visible
  screenshots and audio playback. Initial empty-note error was resolved by a
  user setting change to populate Kiku's first field, Expression.
- Yomine recognized the new 日本 note's media update with authentication off.
  Exact event payload/targeting request was not captured in that client run.
  Yomine API-key support is a follow-up, not a completed feature.
- Ten-operation native batch passed: five suspend/unsuspend pairs on a
  disposable card, 16.976 ms server time, one Undo Card Batch entry. One Undo
  changed the label to Undo Update Note; state snapshots matched.
- Missing IDs and malformed requests returned expected 200-empty/404/400/422.
- **Busy timeout is real, but Options is not a reliable trigger.** A controlled
  35-second UI-thread sleep produced HTTP 503 after 15.222 seconds on a read;
  reads recovered automatically afterward. `_wait` stops waiting but does
  **not cancel** scheduled work. Never infer a timed-out write did not happen.
- Normal shutdown with active stream passed: stream emitted `event: close`,
  `data: {"reason": "shutdown"}`, then curl exited 0. The same polling process
  changed HTTP 200 → connection failure → HTTP 200 after restart. Fresh stream
  connected and received a heartbeat. Monitors have been stopped/expired.
- Forced-crash recovery remains optional/unperformed. Optional sync and GUI
  exit remain unperformed; timer timing was not quantitatively measured.

## Retained disposable fixtures

Do not delete client-created notes merely to clean up this investigation.

- TestSuite deck: `1786219820315`; empty TestSuite::Shim deck: `1788796638769`.
- Disposable shim note/card `1788796639073`, Front `shim-note`, Back
  `shim-edited`, tag `shim`, currently in TestSuite. Last verified selected
  state: queue 2, type 2, due 0, reps 5, flags 0. It contains artificial test
  review rows, including `1788797478685`.
- Yomitan 船首: note/card `1788801318673`, Mining/Kiku; later Asbplayer media.
- Asbplayer 椅子席: note/card `1788803402613`, Mining/Kiku.
- Yomine 日本: note/card `1788803735014`, Mining/Kiku, media update recognized.
- Temporary shim media file and exported package were deleted. Client-created
  media and the fixtures above remain. Prefer read-only profiling first.
