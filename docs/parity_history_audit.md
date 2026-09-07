# AnkiConnect history and native-query audit — 2026-09-07

## Source and scope

Upstream: [SourceHut AnkiConnect](https://git.sr.ht/~foosoft/anki-connect),
master `de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e`. This commit was authored
2025-12-03 and committed 2025-12-05. The remote advertised only master.
The checkout contains all 658 reachable commits, not a shallow snapshot.

This pass reviewed the plugin change log since 2023 and relevant older API
history, then checked selected resulting implementations and request behavior.
It did not individually revalidate the semantics of all 658 commits. The
current source exposes 122 actions; the parity document, test registry, and
live `apiReflect(scopes=["actions"])` agree on that inventory. Removed APIs
such as `updateCompleteDeck` are historical, not additional current routes.

Commit history matters: optional arguments, result fields, renamed parameters,
and rollback semantics can change without adding a name to that inventory.
The tests below are grounded in current upstream source, not README examples.

## Reproduced and fixed

1. **Deprecated GUI alias used the wrong parameter.**
   [ab4d964](https://git.sr.ht/~foosoft/anki-connect/commit/ab4d964) introduced
   `guiSelectCard(card=...)` and retained `guiSelectNote(note=...)`, where
   `note` still holds a card ID. Tsunagi registered the old alias with
   `CardParams`, rejecting canonical `note` input. It now uses `NoteParams`
   and forwards that ID to the card selector. A regression checks both action
   names and their distinct parameter names without opening the Browser.

2. **Undocumented `addTags(..., add=False)` was ignored.**
   The current upstream `addTags(self, notes, tags, add=True)` passes `add` to
   Anki's bulk tag operation. Tsunagi's parameter model discarded it and
   always added tags. The shim now selects add/remove according to the flag.
   An isolated real-collection test proves removal preserves unrelated tags
   and default addition still works.

3. **Malformed RPC containers escaped as HTTP 500.**
   Live requests with an object-valued action or list-valued `multi.params`
   produced unhandled exceptions. The same invalid action inside `multi`
   aborted the entire request. Upstream's handler catches lookup/invocation
   errors in its RPC exception boundary. Tsunagi now checks these containers
   after authentication and returns protocol errors; subsequent `multi`
   entries still execute. Validation text for malformed params is Tsunagi's,
   not an attempt to reproduce Python-version-specific TypeError wording.

The new tests reproduced six failures before the fixes: the two parameter
bugs and four malformed-RPC cases. They pass after the changes.

## Changes found in history that are already represented

| Upstream change | Result of this pass |
| --- | --- |
| [de6e6e1](https://git.sr.ht/~foosoft/anki-connect/commit/de6e6e1), Add Note dialog field update | `guiAddNoteSetData` registered with `note` and `append`; open-dialog behavior remains a manual GUI check. |
| [532a3c8](https://git.sr.ht/~foosoft/anki-connect/commit/532a3c8), replay reviewer audio | `guiPlayAudio` registered; this pass did not run interactive reviewer audio. |
| [b4f26b1](https://git.sr.ht/~foosoft/anki-connect/commit/b4f26b1) and [068b7ec](https://git.sr.ht/~foosoft/anki-connect/commit/068b7ec), media without target fields | New regression stores the attachment without altering a field. |
| [6ae3d59](https://git.sr.ht/~foosoft/anki-connect/commit/6ae3d59), [cf4c902](https://git.sr.ht/~foosoft/anki-connect/commit/cf4c902), [fcd67b2](https://git.sr.ht/~foosoft/anki-connect/commit/fcd67b2), batched note-card/review reads | 1,002-entry notesInfo regression preserves input order/duplicates/missing slots; live 1,002-entry getReviewsOfCards preserves an empty missing-card entry. This verifies behavior, not identical internal batch sizes. |
| [e5e6d25](https://git.sr.ht/~foosoft/anki-connect/commit/e5e6d25), notesInfo query and setDueDate | Query takes precedence over explicit note IDs in regression and live checks; setDueDate is in the registry and existing scheduling coverage. |
| [a382fdf](https://git.sr.ht/~foosoft/anki-connect/commit/a382fdf), card flags | Live cardsInfo includes flags. |
| [81c39a2](https://git.sr.ht/~foosoft/anki-connect/commit/81c39a2), note modification times | notesInfo mod is checked against the collection; notesModTime is registered. |
| [f52e0c2](https://git.sr.ht/~foosoft/anki-connect/commit/f52e0c2), addNotes rollback | New regression verifies a later invalid note removes earlier successful additions. This is note rollback, not a claim that imported media is rolled back. |
| [7c171d6](https://git.sr.ht/~foosoft/anki-connect/commit/7c171d6), nextReviews | Live cardsInfo includes nextReviews and preserves `{}` for a missing card. |
| [bbf271c](https://git.sr.ht/~foosoft/anki-connect/commit/bbf271c), can-add error detail | Single/batch detail actions are registered; read-only media-probe differences remain documented. |
| [50d062e](https://git.sr.ht/~foosoft/anki-connect/commit/50d062e), full-model reads | findModelsById/findModelsByName are included in the 122-action inventory and existing model tests. |

The public but easily overlooked `suspend(..., suspend=False)` switch was
also verified with a real-collection regression. One documentation correction:
Tsunagi's reliable false-on-no-change result differs from upstream's buggy
list-removal loop for multiple already-matching cards. This is now explicit.

The 2025 web-server payload/empty-request changes (`72c228e`, `47da1c5`) were
identified in history. The server itself was not replaced or exhaustively
differential-tested at the raw socket level in this pass.

## Native routing and complex queries

The live OpenAPI document contains 97 method/path operations. The six generic
collection-query families are models, decks, notes, cards, deck-configs, and
reviews. All six passed live checks for:

- ID membership with unsorted and duplicate input IDs;
- combined membership, range, and inequality filters;
- page-by-page completeness and stable ordering;
- GET versus POST query equivalence, including cursors;
- explicit object projection;
- malformed-filter errors and out-of-range limit errors.

Models, notes, and cards additionally passed nested `fields[].name` predicates
combined with an ID index and narrow projection. Expected results came from
independent comparisons against a small full-row snapshot.

**Open behavior to decide:** malformed cursor text is accepted with HTTP 200
and restarts the first page on all six families. It is not rejected. This pass
records that behavior without changing the cursor contract. These checks also
do not cover every possible predicate, every mutation, or every GUI state.

## Validation and installed state

- `check_parity.py --clone /tmp/tsunagi-anki-connect-audit`: 122/122, in sync.
- Focused existing and new tests: 120 passed.
- New history regressions alone: 10 passed.
- Full suite: 852 passed, 8 skipped; Ruff passed.
- Live read checks ran on Anki 26.08.1 / `[DEV] Yomine`.
- Automated tests use Python 3.10 / Anki 23.10 in the existing test environment.
- Three code fixes were synced and reloaded. All four malformed-RPC checks
  passed live with HTTP 200 error envelopes; a following valid `multi` entry
  still returned version 6. GUI alias and tag-removal fixes are verified by
  isolated automated tests, not by changing the user's active GUI or notes.

No commits or publication were performed. Existing unrelated changes remain.
