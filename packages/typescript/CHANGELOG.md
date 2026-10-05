# tsunagi-client changelog

Each version of the TypeScript client, newest first. Its major.minor is
Tsunagi's: 0.6.x speaks the API of Tsunagi 0.6.x. Patch versions are client
changes that need no add-on release.

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
