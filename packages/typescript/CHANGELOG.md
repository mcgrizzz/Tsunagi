# tsunagi-client changelog

Each version of the TypeScript client, newest first. Its major.minor is
Tsunagi's: 0.7.x speaks the API of Tsunagi 0.7.x. Patch versions are client
changes that need no add-on release.

## 0.7.0 (2026-10-05)

Needs Tsunagi 0.7.0. Breaking: what to change is below.

- **Find-or-create in one request:** `notes.create(note, { ifDuplicate: "skip" })`
  adds the note, or answers the saved one (`action: "skipped"`, its `id` and
  every `duplicateIds`) without adding anything. `"allow"` adds a duplicate
  anyway; the default `"error"` refuses it and names the saved notes.
- **Open things in Anki:** `query.openBrowser()` on card and note queries,
  `notes.openEditor(id)`, `notes.openAdd(note)` (Add Cards prefilled, files
  included), `decks.openOverview(deck)` and `decks.openReview(deck)`. Each
  resolves once Anki shows the window.
- **Misuses say why:** `openBrowser()` after `where()`, or `watch()` after
  `orderBy()`, is a compile error naming the reason, and a `TypeError` with the
  same words.

### Migrating from 0.6

| 0.6 | 0.7 |
| --- | --- |
| `notes.exists([a, b])` | `notes.existsMany([a, b])` |
| `notes.check([a])` | `notes.check(a)` (one) or `notes.checkMany([a, b])` |
| `duplicates: { allow: true }` on a note | `create(note, { ifDuplicate: "allow" })` |
| `create(note, { duplicateIds: true })` | nothing: a refused duplicate always names the saved notes |
| `audio`, `video`, `picture` on `upsert` | upload with `media.upload` and put the names in the fields (the server refused them) |
| `note.noteType`, `card.noteType` (a row's note type name) | `noteTypeName` |
| `orderBy("easeFactor")` on cards and notes | `orderBy("ease")`: Anki's ease sort, which isn't the `easeFactor` field's order |

Row fields keep their client names otherwise; only the wire names changed,
which matters only for `anki.raw` requests (see Tsunagi 0.7.0's notes).

## 0.6.1 (2026-10-05)

- `query.is(state)`: Anki's states by name (`new`, `learning`, `review`,
  `due`, `buried`, `siblingBuried`, `manuallyBuried`, `suspended`), added to
  the search as Anki's `is:` terms, on cards, notes and reviews:
  `anki.cards.search("deck:Mining").is("suspended").count()`.
- `notes.exists(note)`: whether a note is already saved, by the rules a create
  uses to refuse a duplicate. A list answers each note.
- The README has a short guide to `exists`, `create`, `upsert` and `check`.

## 0.6.0 (2026-10-04)

First release on npm. Typed queries on every resource, with field names,
named values and sorts checked as you type; note, card and media writes with
per-item results and safe retries; `access()` kept current; `query.watch()`
and listeners for answers, syncs and deck counts.
