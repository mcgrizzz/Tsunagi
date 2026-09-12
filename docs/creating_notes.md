# Create notes in a batch

[← Documentation](README.md)

Send multiple notes to **`POST /v1/notes:batch-create`**. Each note uses the same
fields as the single-note `POST /v1/notes` endpoint:

```json
{
  "notes": [
    {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "犬", "Back": "dog"}},
    {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "犬", "Back": "dog"}},
    {"modelName": "Basic", "deckName": "Default", "fields": {"Front": "猫", "Back": "cat"}}
  ]
}
```

On an empty collection, the first and third notes are saved. The second is a
duplicate of the first. HTTP **200** returns both successes and failures:

```json
{
  "created": [
    {"index": 0, "id": 1789200000000, "cards": [1789200000001]},
    {"index": 2, "id": 1789200000002, "cards": [1789200000003]}
  ],
  "failed": [
    {
      "index": 1,
      "code": "duplicate",
      "message": "Note duplicates existing note(s): [1789200000000]",
      "duplicate_note_ids": [1789200000000]
    }
  ]
}
```

`index` is the zero-based position in your submitted `notes` array. It lets you
match each result to its input even when a note in the middle fails. The server
doesn't repeat note contents in the response.

| Result | What it contains |
| --- | --- |
| `created` | Successful note IDs and their generated card IDs. |
| `failed` | Rejected input positions, error codes and readable messages. |
| `duplicate_note_ids` | Matching saved notes for a duplicate failure; otherwise an empty list. |

For example, keep the successful IDs and show the rejected inputs for correction:

```js
const savedNoteIds = response.created.map(note => note.id);
const rejected = response.failed.map(failure => ({
    note: submittedNotes[failure.index],
    reason: failure.message,
}));
```

The failure codes are `duplicate`, `invalid_note` (such as a missing deck or empty
first field), and `anki_error` (a rejection from Anki). A response with an empty
`failed` array means every input was saved. An empty `notes` array adds nothing.

## Behavior to know

- **Valid notes stay saved when another is rejected.** Notes are processed in
  input order. Duplicate checks include notes already saved by this batch;
  `allowDuplicate: true` permits them for that input.
- **One undo step covers the successful additions.** Undo removes those notes
  and cards together. Earlier changes remain separate. A batch with no successful
  additions leaves undo history unchanged.
- **Invalid request structure returns 422 before any writes.** For example, a
  note missing its required `fields` property makes the request malformed.
  Per-note failures above apply to inputs that pass request validation.
- **Events describe the successful additions.** The normal event size limits
  still apply; see the [events guide](events.md).
- **Media is uploaded separately.** Use `POST /v1/media`, then include its returned
  filename in your field HTML or `[sound:filename]` markup. The batch doesn't
  accept AnkiConnect's `audio` or `picture` attachment envelope, and note undo
  does not remove previously uploaded media.

Resolve the reported problem before resubmitting a rejected input. Don't resend
successful inputs as part of a retry. As with other write endpoints, an interrupted
connection or an unexpected server error may leave the outcome uncertain.

Within a batch, Tsunagi resolves each distinct note type and deck once and reuses
that setup in one collection operation. Each note still gets a fresh validation
and an Anki write. There is no collection-data cache retained between requests.

Use the [interactive reference](playground.md) for the full input schema,
authentication controls and a runnable request.
