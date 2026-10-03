# Create notes and upload media

[← Documentation](README.md)

**Send one object or an array to the same endpoint.** Both endpoints return
`created` and `failed` arrays, even for a single object.

| Create… | Endpoint | Each successful result includes… |
| --- | --- | --- |
| Notes | `POST /v1/notes` | `index`, `id`, and `files` when the note had files |
| Media files | `POST /v1/media` | `index`, `filename`, `requested_filename`, `renamed`, `size` |

`index` is the input's position (`0` for a single object), so you can match
each result to what you sent. One rejected input doesn't stop the others from
being saved.

## Save notes

For one note, send this object to **`POST /v1/notes`**:

```json
{
  "modelName": "Basic",
  "deckName": "Default",
  "fields": {"Front": "犬", "Back": "dog"},
  "allowDuplicate": false
}
```

For several, send an array of those objects:

```json
[
  {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "犬", "Back": "dog"}, "allowDuplicate": false},
  {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "犬", "Back": "dog"}, "allowDuplicate": false},
  {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "猫", "Back": "cat"}, "allowDuplicate": false}
]
```

In a collection without these words, the first and third notes are saved. The
second is a duplicate of the first. HTTP **200** returns:

```json
{
  "created": [
    {"index": 0, "id": 1789200000000},
    {"index": 2, "id": 1789200000002}
  ],
  "failed": [
    {"index": 1, "code": "duplicate", "message": "Note duplicates an existing note"}
  ]
}
```

**Need the new cards too?** Add `?include=cards` and each created note lists
its card IDs (`"cards": [1789200000001]`), so you can act on the cards (suspend
them, set a due date) without searching for them first.

**Need the note a duplicate matches?** Add `?include=duplicate_ids` and
each duplicate lists the notes it duplicates, the same ones `POST /v1/notes:check`
reports. In the example above, the second note's failure becomes
`{"index": 1, "code": "duplicate", "message": "Note duplicates an existing note", "duplicate_note_ids": [1789200000000]}`,
so you can link to or update the existing note without searching for it. It
costs a search for each duplicate, so it's off by default.

Notes are saved in input order. `allowDuplicate` defaults to `false`; set it to
`true` on an input to allow a duplicate, including of an earlier note in the
same request.

By default, a duplicate is a note of the **same note type** with the same first
field, anywhere in the collection; this is Anki's own check. To check only
within a deck, or across all note types, add AnkiConnect's duplicate options:

```json
{
  "modelName": "Kiku+",
  "deckName": "Mining",
  "fields": {"Expression": "犬"},
  "duplicateScope": "deck",
  "duplicateScopeOptions": {"deckName": "Mining", "checkChildren": true, "checkAllModels": true}
}
```

- `duplicateScope`: `"collection"` (default) or `"deck"`, the note's own deck
  unless `duplicateScopeOptions.deckName` names another.
- `checkChildren`: with deck scope, also check subdecks.
- `checkAllModels`: match notes of every note type, not only this one.

With deck scope or `checkAllModels`, notes match on the first field's checksum,
as in AnkiConnect, and `duplicate_note_ids` lists exactly those notes. Empty
and missing-cloze checks are still Anki's. An unknown `deckName` is reported as
an invalid input, and other `duplicateScope` values return 422, instead of
either being silently ignored.

## Create, or add to the note you already have

"I already have this word; add the new sentence to it" is one request with
**`POST /v1/notes:upsert`**. It takes the same notes as creation, without files
(upload those with `POST /v1/media`), plus how to find the existing note and
how to merge into it:

```json
{
  "modelName": "Mining", "deckName": "Mining",
  "fields": {"Expression": "食べる", "Sentence": "もう食べた。", "Audio": "[sound:taberu.mp3]"},
  "tags": ["mined"],
  "match": {"field": "Expression"},
  "onMatch": {
    "fields": {"Sentence": "append", "Audio": "replace_if_empty", "*": "keep"},
    "tags": "union",
    "separator": "<br>"
  }
}
```

- **Finding the note.** Without `match`, Anki's duplicate check decides: the
  first field, ignoring HTML, within the note type, honoring `duplicateScope`.
  With `match.field`, that field's exact content decides (case-insensitive;
  `*` and `_` are literal).
- **No match:** the note is created, exactly as `POST /v1/notes` would.
- **One match:** it is updated. Its cards stay in their decks.
- **Several matches:** the item fails with code `ambiguous`, and its message
  lists the matching note IDs. None of them is changed.

Field rules, per field or for all others with `"*"`:

| Rule | The existing field becomes |
| --- | --- |
| `replace_if_empty` (default) | the new value if it was empty; otherwise unchanged |
| `keep` | unchanged |
| `replace` | the new value (unless the new value is empty) |
| `append` | old + `separator` + new; unchanged if that value is already there |

Fields the request doesn't send are never touched. `tags` is `union` (add the
request's tags, default), `replace` or `keep`.

If a note with that `Expression` already exists, the response is:

```json
{
  "created": [],
  "updated": [
    {"index": 0, "id": 1789200000000, "fields_changed": ["Sentence"], "tags_changed": true}
  ],
  "failed": []
}
```

Its sentence was appended, its audio kept (it wasn't empty) and the tag added.
Sending the same request again changes nothing: `fields_changed` is empty and
`tags_changed` is false. `?include=cards` works here too.

## Check without saving

**`POST /v1/notes:check`** answers "could I add these?" without saving
anything. Send the notes you would create, inside `{"notes": [...]}`:

```json
{"notes": [
  {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "犬", "Back": "dog"}},
  {"modelName": "Basic", "deckName": "Nope", "fields": {"Front": "猫", "Back": "cat"}}
]}
```

If 犬 already exists and there is no deck called Nope:

```json
{"results": [
  {"index": 0, "can_add": false, "state": "duplicate", "reason": "duplicate", "duplicate_note_ids": null},
  {"index": 1, "can_add": false, "state": "invalid", "reason": "Unknown deck 'Nope'", "duplicate_note_ids": null}
], "stats": {"duration_ms": 0.16}}
```

`state` is one of:

- `normal`: it can be added.
- `duplicate`: a matching note exists; `duplicate_note_ids` lists it if you
  ask (below).
- `empty`: the first field is empty.
- `missing_cloze`: a cloze note without a cloze.
- `invalid`: something else is wrong, such as an unknown note type or deck;
  `reason` says what.

**Need the matching notes too?** Add **`?include=duplicate_ids`**: each
result then lists the existing notes it duplicates, so a dictionary popup can
check a word and get its existing notes in one request. Without it, Anki still
checks for duplicates and applies your `allowDuplicate` policy, but Tsunagi
skips the extra search, and `duplicate_note_ids` is `null`. When IDs are
included, an empty array means none matched.

`include` works the same everywhere: each part (`cards`, `duplicate_ids`, or
`total` on lists) costs an extra step before the answer, so none is sent unless
you ask, and several go together with commas (`?include=cards,duplicate_ids`).
A check reads the current collection; it doesn't reserve a note or guarantee a
later save will succeed.

**Want every note with the same word, in any note type?** Ask for notes by
their first field, the field Anki compares for duplicates:
**`GET /v1/notes?where=first_field in ["犬","猫"]&select=id,first_field`**.
`first_field` is the first field's exact value, HTML included. Add
`where=model_name=="Basic"` or other filters to narrow it.

## Add files to your notes

Send the files with the note: **`POST /v1/notes`** takes `audio`, `video` and
`picture`, each one file or a list, as AnkiConnect's `addNote` does:

```json
{"modelName": "Basic", "deckName": "Default",
 "fields": {"Front": "犬", "Back": "dog"},
 "audio": {"url": "https://example.com/inu.mp3", "filename": "inu.mp3", "fields": ["Front"]},
 "picture": {"data": "iVBORw0KGgo...", "filename": "inu.png", "fields": ["Back"]}}
```

Tsunagi stores each file and appends `[sound:inu.mp3]` or `<img src="inu.png">`
to the fields you list; with no `fields`, the file is only stored. A note's
files are stored only once the note passes its checks, so a rejected note (a
duplicate, say) leaves no files behind. A file that can't be read or
downloaded fails its note with `invalid_attachment`, and the failure's
`attachment` says which one: `{"kind": "picture", "position": 1, "filename":
"bad.png"}` is the second picture. Batches work the same way: each note in the
array carries its own files.

Each created note lists its files in `files`, audio first, then video, then
pictures, in the same form `POST /v1/media` returns:

```json
{"index": 0, "id": 1790000000000,
 "files": [{"filename": "inu.mp3", "requested_filename": "inu.mp3", "renamed": false, "size": 5120},
           {"filename": "inu-187b733b8c6ec3c0e7701da8b57b7add487eaa07.png", "requested_filename": "inu.png", "renamed": true, "size": 20480}]}
```

Anki renames a file when its name already holds different bytes. The
references Tsunagi adds to the fields you list follow the new name; a reference
you wrote into the fields yourself doesn't. If a file shows `renamed: true`,
update your own references to its `filename`.

Each file takes exactly one source:

- `data`: the file's contents, base64-encoded;
- `url`: an `http` or `https` address Anki downloads;
- `path`: a file on this computer. Off by default, because it lets an app read
  any file you can; only apps whose role allows **Read files on this
  computer** may use it (Everything does).

Base64 files need a `filename`; URL and path files can derive it from the
source. The configured upload-size limit applies to each file.

**Adding files to a note you already have:** send the same `audio`, `video` and
`picture` to **`PATCH /v1/notes/{id}`**, with or without `fields` and tags. The
references go after the fields' new values, renames are followed, and the whole
change is one undo step. A field that already has a file's reference doesn't get
a second one, so retrying a PATCH after a timeout is safe:

```json
{"audio": {"url": "https://example.com/inu.mp3", "fields": ["Back"]}}
```

A file that can't be read fails the request with 400, naming the file, and
nothing is changed or stored. The answer is the updated note; to learn a file's
stored name without referencing it, upload it with `POST /v1/media` instead.

**Many or large files, or one file for several notes?** Upload them first with
**`POST /v1/media`** (one object or an array, same sources), then put the
returned names in your fields:

```json
[{"filename": "example.txt", "data": "aGVsbG8="}]
```

```json
{
  "created": [
    {"index": 0, "filename": "example.txt", "requested_filename": "example.txt", "renamed": false, "size": 5}
  ],
  "failed": []
}
```

Use the returned `filename`: Anki renames a file when the requested name already
holds different bytes. (Files sent with a note are renamed the same way, and
their references follow.) Uploading first keeps each request small and sends a
shared file once.

Stored files aren't part of undo: undoing note creation removes the notes, not
their files.

## Handle failures

HTTP **200** means the request was processed; inspect `failed` to see whether
all inputs succeeded. The successful count is `created.length`.

```js
const rejected = response.failed.map(failure => ({
    input: submitted[failure.index],
    reason: failure.message,
}));
```

| Endpoint | Failure codes |
| --- | --- |
| Notes | `duplicate`, `invalid_note` (such as a missing deck), `invalid_attachment` (a file that can't be read or downloaded; `attachment` names it), `anki_error`, and for upsert `ambiguous` (several notes matched; the message lists them) |
| Media | `invalid_media` (such as invalid base64 or a failed download), `source_error`, `storage_error` |

Correct the reported problem and retry only those inputs. A single object uses
the same failure format. An empty array returns empty `created` and `failed` arrays.

Some errors reject the whole request instead:

- **422**: the request is malformed, such as a note without `fields` or with
  a key the note doesn't take (a misspelled `allowDuplicates`). Nothing was
  written. `detail` sums up the problems and `errors` lists each one.
- **401**: no usable key.
- **403**: your app isn't allowed to create notes or upload media, or it is
  turned off. The message says which.
- **503**: Anki is busy, syncing or has no collection open (`reason` says
  which). See the note on timeouts below.

Every status the Tsunagi API uses, and what to do about it, is listed under
Errors in the API reference's overview.

After a lost connection or an unexpected error, some writes may already have
happened; check the collection before retrying.

## Undo

Each request is one step in Anki's **Edit → Undo**: undoing it removes the
notes it created and reverts the notes it updated, and nothing else. A request
that changes nothing adds no undo step. Media uploads can't be undone.

An operation-timeout **503 does not cancel the write**. Work already queued in
Anki may run after the response, and a running operation may finish later.
Retrying immediately can create another note or repeat a media write. Check
what was saved before retrying, or send an `Idempotency-Key` (below) so a
retry is safe. Do not treat a timeout as a `failed` result for every
submitted input.

### Retry safely with an idempotency key

Send an `Idempotency-Key` header, a new unique value (such as a UUID) per
request, on any write, and reuse it when you retry that request: creating
notes and media, answering cards, a PATCH or DELETE, the other note, card,
deck, note type, tag, preset and review writes, exports, jobs, switching
profile, checking the database and actions on Anki's windows (`/v1/gui:…`).

A retried job (import, sync, FSRS computations, add-on actions) gets the same
job, its result if it has finished or the same `job_id` to poll, so it never
starts twice. A job that failed starts again.

```sh
curl -X POST http://127.0.0.1:7777/v1/notes -H "Idempotency-Key: 9b2c…" \
  -H "Content-Type: application/json" -d '{...}'
```

- A retry with the same key returns the first attempt's response instead of
  writing again, with the header `Idempotent-Replayed: true`. This holds after
  a 503: the result is recorded when the write completes, not when the
  request gives up.
- A replay is the first attempt's result as it was then, even if the data has
  changed since (someone edited the note, or undid the write).
- A retry while the first attempt is still running waits for it, like any
  write (503 again if it still isn't done).
- The same key with a different body is refused (400). Use a new key for a new
  request. For writes other than creating notes and media, "the same" means
  the same path, query and body bytes.
- For those other writes, a retry runs the request again, but each write in
  it returns its recorded result instead of writing; only the response's
  `stats` timing can differ.
- Keys belong to the app and route that sent them and are kept for ten
  minutes. A first attempt that failed with an error is forgotten, so its
  retry runs again.
- A 200 response is recorded even when some items are in `failed`. To retry
  just those items with corrected input, send a new request with a new key.
- Some writes are safe to repeat without a key: an upsert updates the same
  note and changes nothing more, setting tags, flags or fields to the same
  values changes nothing, and adding a file to a note with PATCH doesn't add
  a second reference. Answering a card or repositioning with `shift_existing`
  is not, so send a key with those.

## Add many notes

Send notes in requests of about 10 to 25, each with its own files attached.
In a test on the Anki desktop, 100 mined notes with about 270 KB of files each
took 3.4 to 3.7 s that way, and the first notes were saved in under a second.

- **One request per note** is nearly as fast (3.9 s for 100 notes), and suits a
  tool that adds each note as the user mines it.
- **One request for everything** is no faster. Nothing is saved until the
  whole request finishes, and other requests that read the collection wait for
  it: during a 100-note request, reads waited up to 6 s. With files, a few
  hundred notes in one request take longer than the operation timeout, and the
  request answers 503 while the write carries on (see [Undo](#undo)).
- **Files take most of the time.** Adding a note took about 5 ms; storing its
  files took the rest of its 35 to 40 ms.

The measurements are in
[performance notes](performance_notes.md#adding-mined-notes-in-batches).

## How batching reduces repeated work

Note creation resolves each distinct note type and deck once within a collection
operation. Each candidate still gets fresh validation against the live collection
and its own Anki write. No collection data is cached between requests.

Media uploads decode and download on the request thread, then dispatch bounded
groups of files to Anki for storage. This avoids one collection dispatch per
base64 upload. Pending decoded data is bounded internally; the JSON request
itself still occupies memory, so choose a batch size that suits your payload.
A profile switch stops the request before it can store files in another collection.

Use the [interactive reference](playground.md) for the full schemas and runnable
requests, and the [events guide](events.md) for change notifications.
