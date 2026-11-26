# tsunagi-client changelog

Each version of the TypeScript client, newest first. Its major.minor is
Tsunagi's: 0.7.x speaks the API of Tsunagi 0.7.x. Patch versions are client
changes that need no add-on release.

## 0.7.2 (2026-10-24)

Needs Tsunagi 0.7.7.

- **Only some elements of a list:** `narrow(list, step)` keeps the elements
  of a list in each row whose key is a value (`eq`) or one of several (`in`;
  `in []` keeps none), and with `select` in the step only those parts:
  `anki.notes.select("id", "fields").narrow("fields", f => f.where("name",
  "in", ["Word", "Reading"]))`. It works on a note's and card's `fields` and
  a note type's `fields` and `templates`, is typed from the API description,
  and can be watched.
- **A field's text:** `narrow`'s `select` can name `text`, the field without
  HTML as Anki's Browser shows it; whole fields leave it out.
- **Resending a write safely:** `WriteOutcomeUnknownError` has `retry()`,
  which sends the same request with the same key: Tsunagi answers the first
  attempt's result, or writes once if it never arrived. `resendableUntil`
  says until when that is safe; after it, or once Anki restarted or switched
  profile, `retry()` raises `ResendExpiredError` (check before writing
  again). `{ resendIfUnknown: true }` on any write resends by itself. A
  client's first write reads `/v1/health` once, for the server session.
- **Watching an app's own copy:** watch handlers may return a promise, and
  the watch waits for it; changes during an Anki sync are delivered together
  when it ends; a `status` handler hears `reconnecting` and `live`; a profile
  switch ends the watch with `ProfileChangedError`.
- **Fewer reads while watching:** a watch whose `select` names plain fields
  gets the changed notes, cards or reviews with each change from Tsunagi,
  instead of reading them after it. With a search or filter it still asks
  which of them match, reading only their keys. Nothing changes in how you
  call it; with an older Tsunagi it reads as before.

## 0.7.1 (2026-10-11)

Needs Tsunagi 0.7.1 for `requestAccess()` and day changes; the rest works with 0.7.0.

- **Ask for access:** `anki.requestAccess({ name, role })` asks Tsunagi for a
  key. Anki shows the user your app (its website, or the name you give) and
  the role you suggest; if they allow it, the answer carries the key, once.
  Keep it and make a client with it. It waits for the user, up to two minutes.
  Needs Tsunagi 0.7.1.
- **Typed `raw`:** `anki.raw.request("PATCH /v1/notes/{id}", { path: { id },
  body })` reaches every operation in Tsunagi's API description. The route
  autocompletes; path and query parameters, the body and the answer are typed
  in Tsunagi's own names (`note_type_name`), so a misspelled key doesn't
  compile; the answer's type follows its status (`202` for a job still
  running). Writes are keyed like the client's own methods. `PUT` routes
  (field and template order) are reachable now.
- `notes.update(id, { noteType })` is deprecated, as the server's PATCH retype
  is: both go with Tsunagi 0.8. To change notes' note type, use
  `anki.raw.request("POST /v1/notes:change-note-type", { body })`: it maps
  fields and cards (with their reviews) for many notes at once, and
  `dry_run: true` answers what would change first.
- `raw.request(method, path, options)` still works but is deprecated: it is
  untyped, and a write is keyed only when you pass an `idempotencyKey`.
- **Watches stay right overnight:** when Anki's day changes, a watch reads
  everything again (a search like `is:due` or `rated:1` matches other cards
  though none changed), and `onChange` is called. Needs Tsunagi 0.7.1; with
  0.7.0 nothing changes.

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
