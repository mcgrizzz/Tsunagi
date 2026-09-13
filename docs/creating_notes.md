# Create notes and upload media

[← Documentation](README.md)

**Send one object or an array to the same endpoint.** Both endpoints return
`created` and `failed` arrays, even for a single object.

| Create… | Endpoint | Each successful result includes… |
| --- | --- | --- |
| Notes | `POST /v1/notes` | `index`, `id` |
| Media files | `POST /v1/media` | `index`, `filename`, `requested_filename`, `renamed`, `size` |

`index` is the zero-based input position, or `0` for a single object. Keep your
submitted inputs to match failures back to them. Successful items aren't rolled
back because another input is rejected.

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

For a successful single-note request, `created` has one entry with `index: 0`,
and `failed` is empty. The response doesn't repeat your note contents or search
for existing duplicate IDs.

**Need the generated card IDs too?** Use **`POST /v1/notes?include=cards`**.
Each successful entry then includes `cards: [1789200000001]`. This uses Anki's
direct card-ID lookup and avoids a separate card search. Leave `include` out
when you only need the note IDs.

Notes are checked and saved in input order. `allowDuplicate` defaults to `false`;
set it to `true` on an input to permit duplicates, including earlier notes in the
same batch. Native checking supports collection scope; omit `duplicateScope`
or set it to `"collection"`. Other scopes return 422 instead of being silently
interpreted as collection-wide checks.

One undo step removes all successful additions in the request,
without undoing earlier work. A request that creates nothing leaves undo history
unchanged.

## Check without saving

Use **`POST /v1/notes:check`** with a body containing `{"notes": [...]}`.
Each entry uses the same note fields as creation. The response reports
`can_add`, `state` and any `duplicate_note_ids` for each input. Nothing is saved.

**Only need validation?** Use
**`POST /v1/notes:check?include_duplicate_ids=false`**. Anki still checks for
duplicates and applies your `allowDuplicate` policy, but Tsunagi skips the extra
search for matching IDs. `duplicate_note_ids` is then `null` for every result.
When IDs are requested, an empty array means no IDs were returned.

The default still includes IDs, so a dictionary popup can check a word and get
its existing note IDs in one request. A check reads the current collection;
it doesn't reserve a note or guarantee a later save will succeed.

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

Each upload accepts exactly one source: base64 `data`, an HTTP(S) `url`, or a
local `path` when that option is enabled in Tsunagi settings. Base64 uploads need
a `filename`; URL and path uploads can derive it from the source. The configured
upload-size limit applies to each file.

**Use the returned `filename`.** Anki can rename a file when the requested name
already contains different bytes. Put the stored name in your note's
`<img src="filename">` or `[sound:filename]` markup, then send the prepared notes
to `/v1/notes`. This takes two requests for a batch: one for all uploads, one for
all notes. Native note bodies don't accept AnkiConnect's attachment envelope.

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
| Notes | `duplicate`, `invalid_note` (such as a missing deck), `anki_error` |
| Media | `invalid_media` (such as invalid base64 or a failed download), `source_error`, `storage_error` |

Correct the reported problem and retry only those inputs. A single object uses
the same failure format. An empty array returns empty `created` and `failed` arrays.

Malformed request structure, such as a note missing `fields`, returns **422
before any writes**. Authentication, an unavailable collection, or an unexpected
server error are request-level errors instead. After a connection loss or
request-level error, some writes may already have completed; reconcile the
collection before retrying. Events are optional notifications, not a substitute
for handling the request result.

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
