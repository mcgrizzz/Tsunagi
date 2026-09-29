# Create notes and upload media

[← Documentation](README.md)

**Send one object or an array to the same endpoint.** Both endpoints return
`created` and `failed` arrays, even for a single object.

| Create… | Endpoint | Each successful result includes… |
| --- | --- | --- |
| Notes | `POST /v1/notes` | `index`, `id` |
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
**`POST /v1/notes:upsert`**. It takes the same notes as creation, plus how to
find the existing note and how to merge into it:

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
  {"index": 0, "can_add": false, "state": "duplicate", "reason": "duplicate", "duplicate_note_ids": [1789200000000]},
  {"index": 1, "can_add": false, "state": "invalid", "reason": "Unknown deck 'Nope'", "duplicate_note_ids": []}
]}
```

`state` is one of:

- `normal`: it can be added.
- `duplicate`: a matching note exists; `duplicate_note_ids` lists it.
- `empty`: the first field is empty.
- `missing_cloze`: a cloze note without a cloze.
- `invalid`: something else is wrong, such as an unknown note type or deck;
  `reason` says what.

**Only need validation?** Use
**`POST /v1/notes:check?include_duplicate_ids=false`**. Anki still checks for
duplicates and applies your `allowDuplicate` policy, but Tsunagi skips the extra
search for matching IDs. `duplicate_note_ids` is then `null` for every result.
When IDs are requested, an empty array means no IDs were returned.

The default still includes IDs, so a dictionary popup can check a word and get
its existing note IDs in one request. A check reads the current collection;
it doesn't reserve a note or guarantee a later save will succeed.

**Want every note with the same word, in any note type?** Ask for notes by
their first field, the field Anki compares for duplicates:
**`GET /v1/notes?where=first_field in ["犬","猫"]&select=id,first_field`**.
`first_field` is the first field's exact value, HTML included. Add
`where=model_name=="Basic"` or other filters to narrow it.

## Upload files, then use their stored names

Send one upload object or an array to **`POST /v1/media`**. For example, this is
an array containing one small text file:

```json
[
  {"filename": "example.txt", "data": "aGVsbG8="}
]
```

```json
{
  "created": [
    {"index": 0, "filename": "example.txt", "requested_filename": "example.txt", "renamed": false, "size": 5}
  ],
  "failed": []
}
```

Each upload takes exactly one source:

- `data`: the file's contents, base64-encoded;
- `url`: an `http` or `https` address Anki downloads;
- `path`: a file on this computer. Off by default, because it lets an app read
  any file you can; only apps with the Everything role may use it. Otherwise
  that item fails as `invalid_media`. Base64 uploads need
a `filename`; URL and path uploads can derive it from the source. The configured
upload-size limit applies to each file.

**Use the returned `filename`.** Anki can rename a file when the requested name
already contains different bytes. Put the stored name in your note's
`<img src="filename">` or `[sound:filename]` markup, then send the prepared notes
to `/v1/notes`. This takes two requests for a batch: one for all uploads, one for
all notes. Tsunagi API note bodies don't accept AnkiConnect's attachment envelope.

Media uploads aren't undoable. Undoing note creation doesn't remove uploaded
files, and a rejected note can leave its media unused.

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
| Notes | `duplicate`, `invalid_note` (such as a missing deck), `anki_error`, and for upsert `ambiguous` (several notes matched; the message lists them) |
| Media | `invalid_media` (such as invalid base64 or a failed download), `source_error`, `storage_error` |

Correct the reported problem and retry only those inputs. A single object uses
the same failure format. An empty array returns empty `created` and `failed` arrays.

Some errors reject the whole request instead:

- **422**: the request is malformed, such as a note without `fields`. Nothing
  was written.
- **401**: no usable key.
- **403**: your app isn't allowed to create notes or upload media, or it is
  turned off. The message says which.
- **503**: Anki is busy, syncing or has no collection open (`reason` says
  which). See the note on timeouts below.

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
request, on `POST /v1/notes` and `POST /v1/media`, and reuse it when you retry
that request:

```sh
curl -X POST http://127.0.0.1:7777/v1/notes -H "Idempotency-Key: 9b2c…" -d '{...}'
```

- A retry with the same key returns the first attempt's response instead of
  writing again, with the header `Idempotent-Replayed: true`. This holds after
  a 503: the result is recorded when the write completes, not when the
  request gives up.
- A retry while the first attempt is still running waits for it, like any
  write (503 again if it still isn't done).
- The same key with a different body is refused (400). Use a new key for a new
  request.
- Keys belong to the app and route that sent them and are kept for ten
  minutes. A first attempt that failed with an error is forgotten, so its
  retry runs again.
- A 200 response is recorded even when some items are in `failed`. To retry
  just those items with corrected input, send a new request with a new key.
- `POST /v1/notes:upsert` doesn't take a key: repeating an upsert updates the
  same note and changes nothing more.

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
