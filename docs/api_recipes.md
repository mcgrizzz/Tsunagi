# Yomitan's Anki workflow, with Tsunagi

[← Documentation](README.md) · [Install Tsunagi](../README.md#install)

You look up **食べる** in Yomitan. Before you click anything, the popup needs to
know whether it's already in Anki. If it is, the popup needs the existing note's
ID. If you save a new note, it may also need the generated card IDs.

Tsunagi can keep related work together inside Anki: reuse the note type and deck
while checking a batch, return duplicate IDs with the check, and build a save
response from the note it just created. The examples below show both the endpoint
calls and the Anki work behind them.

The AnkiConnect side below follows Yomitan's source at
[`d34832d`](https://github.com/yomidevs/yomitan/tree/d34832d756e05dc00945e5b7d7ebc80963299a7a).
The native side shows how a client could implement the same workflow with
Tsunagi. **Yomitan itself still uses AnkiConnect requests**; it can already send
those to Tsunagi's compatibility API. This guide doesn't install a native Yomitan integration.

| What the interface needs | Yomitan's AnkiConnect workflow | With native Tsunagi |
| --- | --- | --- |
| Duplicate status and existing note IDs | Check candidates, recognize duplicates in error text, then search for IDs | Read `state` and `duplicate_note_ids` from the check response |
| New card IDs, when automatic suspension is enabled | Add the note, find its cards, then suspend them | Add the note, then suspend the returned cards |
| Note types and their field names | Fetch fields when a type is selected | Fetch fields alongside the model list |

## Try these examples

The pseudocode shows call order and how results feed the next step:

- `AC(action, params)` sends an AnkiConnect action to **`POST /`** and unwraps
  its result, including child results in `multi`.
- `GET` and `POST` make native HTTP requests and return the decoded JSON.
  `GET_PAGES` repeats a GET with the returned cursor until all pages are loaded.
- UI helpers such as `showExisting` stand in for the client's interface code.
  Connection checks, authentication and transport-error handling are omitted.

Open the [interactive reference](http://127.0.0.1:7777/) while Anki is running.
Use your configured port if different. Select the method/path below and use
**Test Request** to enter the query parameters or JSON body.

For the examples, imagine Yomitan is configured with the **Basic** note type:
**Front** gets the word, **Back** gets its meaning, and notes go into **Default**.
Substitute your actual deck and field names. Response snippets show the relevant
fields only; your IDs will differ.

> [!IMPORTANT]
> The save example adds a note to your open collection. Use a disposable profile
> for experiments. If you configured an API key, supply it in the reference's
> authentication controls.

## 1. You look up a word that's already in Anki

**The popup needs two answers:** is this candidate a duplicate, and which saved
note does it match? A yes/no check alone can't supply the ID needed to open an
existing note.

**With AnkiConnect**, Yomitan first calls `canAddNotesWithErrorDetail`. Its
[duplicate detection](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L651-L659)
recognizes duplicates by checking the returned error text.

For this single-candidate example, `acNote` and `nativeNote` contain the word,
meaning and duplicate options shown in the expandable request examples below.

**AnkiConnect — actions sent to `POST /`:**

```text
# Request 1: check whether the candidate can be added
check = AC("canAddNotesWithErrorDetail", {notes: [acNote]})[0]

if check.error contains "cannot create note because it is a duplicate":
    query = buildYomitanNoteSearch(acNote)
    # Request 2: find the existing note IDs
    matches = AC("multi", {actions: [
        {action: "findNotes", params: {query: query}}
    ]})
    showExisting(matches[0])                 # IDs from the second request
else:
    showValidation(check)
```

Yomitan's [lookup helper](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/comm/anki-connect.js#L308-L364)
builds the search from the candidate's fields and scope. For multiple distinct
queries, it can first search their union, then narrow the searches inside `multi`.
The pseudocode above shows the one-candidate path.

**Native Tsunagi:**

```text
# Request 1: get validation state and existing note IDs together
check = POST("/v1/notes:check", {notes: [nativeNote]}).results[0]

if check.state == "duplicate":
    showExisting(check.duplicate_note_ids)   # IDs from the check itself
else:
    showValidation(check)

setAddingAllowed(check.can_add)
```

**Inside Tsunagi: share the setup across the batch.** A dictionary popup can
prepare several candidate notes using the same note type and deck. Send them in
one `notes:check` request and Tsunagi resolves each distinct note type and deck
once, then reuses them:

```text
POST /v1/notes:check with 10 candidates using Basic / Default
    resolve Basic once
    resolve Default once

    for each candidate:
        ask Anki to check its fields and duplicate status
        if duplicate:
            ask Anki's duplicate search for the matching note IDs
        collect the state and IDs in that candidate's result

    return all 10 results
```

The duplicate search uses Anki's note-type ID and first field directly. Yomitan
therefore doesn't have to interpret a duplicate error, construct a separate Anki
search string, and send it back to recover the IDs.

For ten candidates sharing a note type and deck, the native adapter performs
**one note-type resolution and one deck resolution**. Each candidate still gets
its own validation and, when duplicate, an ID search. The shared setup is reused
within this request, so it doesn't become a persistent cache that the client has
to keep up to date.

For one already-saved word, that also removes the second HTTP request. If the
word is new, both APIs can finish with the initial check.

<details>
<summary>Request bodies and duplicate responses</summary>

For our example, the AnkiConnect check looks like this:

```json
{
  "action": "canAddNotesWithErrorDetail",
  "version": 6,
  "params": {
    "notes": [{
      "modelName": "Basic",
      "deckName": "Default",
      "fields": {"Front": "食べる", "Back": "to eat"},
      "options": {"allowDuplicate": false, "duplicateScope": "collection"}
    }]
  }
}
```

For a duplicate, that response looks like:

```json
{
  "result": [{
    "canAdd": false,
    "error": "cannot create note because it is a duplicate"
  }],
  "error": null
}
```

There is no note ID in this result. Yomitan then
[finds IDs for the duplicate candidates](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L705-L753).

**With native Tsunagi**, send the candidate to **`POST /v1/notes:check`**:

```json
{
  "notes": [{
    "modelName": "Basic",
    "deckName": "Default",
    "fields": {"Front": "食べる", "Back": "to eat"},
    "allowDuplicate": false,
    "duplicateScope": "collection"
  }]
}
```

The response contains both answers:

```json
{
  "results": [{
    "index": 0,
    "can_add": false,
    "state": "duplicate",
    "duplicate_note_ids": [1789162609990]
  }]
}
```

</details>

| From this response | The popup has what it needs to… |
| --- | --- |
| `state: "duplicate"` | Recognize the duplicate without matching an error message |
| `duplicate_note_ids: [1789162609990]` | Offer to open the saved note without searching for its ID |
| `can_add: false` | Respect the requested `allowDuplicate: false` policy |

For several dictionary entries, put their candidates in the same `notes` array.
Each result's `index` identifies its input candidate, with duplicate IDs attached
to that result. Both APIs accept batches for the initial check; the difference
here is that the native response also supplies the IDs.

If the candidate can be added, `can_add` is `true`; for a new word, `state` is
`"normal"` and `duplicate_note_ids` is empty. Other states can describe invalid
fields or a missing note type. Keep those separate from duplicates when deciding
what to show. The check doesn't add anything or reserve a note.

This response covers duplicate status and IDs. Yomitan can also request note and
card details through `notesInfo` followed by `cardsInfo`; a native client needing
those details would still fetch them separately.

The example deliberately uses collection-wide duplicate checking. A native port
must also map Yomitan's configured duplicate scope and related options; don't
silently substitute this example's policy for the user's settings.

## 2. You click the add-note button

**What Yomitan does.** The popup passes the prepared note to its backend, which
calls AnkiConnect's `addNote`. The returned note ID is used to update the popup's
existing-note controls. If enabled, Yomitan also requests suspension of the new
cards and a sync. See [the add-note handler](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/display/display-anki.js#L924-L961)
and [the backend call](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L621-L623).

Suppose you've enabled automatic suspension. Yomitan's
[suspension handler](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L808-L816)
must first find the cards generated from the new note:

**AnkiConnect — actions sent to `POST /`:**

```text
noteId = AC("addNote", {note: acNote})
showSaved(noteId)

if settings.suspendNewCards:
    cardIds = AC("findCards", {query: "nid:" + noteId})
    if cardIds is not empty:
        AC("suspend", {cards: cardIds})
```

**Native Tsunagi:**

```text
note = POST("/v1/notes", nativeNote).result
showSaved(note.id)

if settings.suspendNewCards and note.cards is not empty:
    POST("/v1/cards:suspend", {cardIds: note.cards})
```

<details>
<summary>Request bodies and save responses</summary>

The text-only AnkiConnect request is:

```json
{
  "action": "addNote",
  "version": 6,
  "params": {
    "note": {
      "modelName": "Basic",
      "deckName": "Default",
      "fields": {"Front": "食べる", "Back": "to eat"},
      "tags": ["yomitan"],
      "options": {"allowDuplicate": false, "duplicateScope": "collection"}
    }
  }
}
```

Its success response contains the ID: `{"result":1789162609990,"error":null}`.

**With native Tsunagi.** Send **`POST /v1/notes`**:

```json
{
  "modelName": "Basic",
  "deckName": "Default",
  "fields": {"Front": "食べる", "Back": "to eat"},
  "tags": ["yomitan"],
  "allowDuplicate": false,
  "duplicateScope": "collection"
}
```

HTTP **201** returns the note in `result`, including:

```json
{
  "result": {
    "id": 1789162609990,
    "cards": [1789162609990],
    "tags": ["yomitan"]
  }
}
```

The popup uses `result.id` for its existing-note controls. The suspension step
can use `result.cards` immediately, without a card-ID lookup. If suspension is
disabled, there's no suspension request to make. Suspension and sync remain separate,
explicit requests, conditional on the user's settings.

</details>

**Inside Tsunagi: use the note that's already in memory.** After Anki adds the
note and generates its cards, Tsunagi builds the response from that same note
object. It already knows the note type and fields. For the generated card IDs,
it uses Anki's direct lookup for cards belonging to that note:

```text
POST /v1/notes
    resolve the note type and deck
    build and validate the note
    Anki: add_note(note, deck_id)
    Anki: card_ids_of_note(note.id)
    return the existing note data together with those card IDs
```

Yomitan's current flow receives only a note ID, then sends `findCards` with a
`nid:...` search before it can suspend the cards. The native save path gets those
IDs through the direct Anki method and includes them immediately. It neither
reloads the saved note nor calls Anki's browser card-search method to build this
response.

Suspension still changes the cards in a separate operation, conditional on the
user's setting. The save-and-suspend flow uses two HTTP requests instead of three.
Optional sync is omitted from the pseudocode and remains a separate request.

To try the duplicate case in step 1, run its check again after saving this note.
If the example word is already saved, use a different word for the create request.
Run only one of the two create requests unless you intend to test duplicate rejection.

## 3. Load note types together with their fields

Anki stores a note type's name, fields and templates together in its model
record. Tsunagi can return the parts needed for the field-mapping controls in the
same result, so the client doesn't have to ask for the field names separately.

**What Yomitan does.** Its settings controller fetches deck names and model names
in parallel. When a note type is selected, it requests that type's field names to
build the field-mapping controls. See the [settings controller](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/pages/settings/anki-controller.js#L439-L484)
and [field selection](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/pages/settings/anki-controller.js#L1100-L1170).

**AnkiConnect — actions sent to `POST /`:**

```text
when settings opens, in parallel:
    decks = AC("deckNames")
    models = AC("modelNames")

when the user selects a model:
    fields = AC("modelFieldNames", {modelName: selectedModel})
    showFieldMapping(fields)
```

**Native Tsunagi:**

```text
when settings opens, in parallel:
    decks = GET_PAGES("/v1/decks", {select: "id,name", limit: 10})
    models = GET_PAGES("/v1/models", {
        select: "id,name,fields[].name", limit: 10
    })

when the user selects a loaded model:
    showFieldMapping(selectedModel.fields)   # already in the response
```

The model query returns entries like:

```json
{
  "items": [
    {"id": 1789162609922, "name": "Basic", "fields": ["Front", "Back"]}
  ]
}
```

Assuming each list fits in one page, the requests look like this:

| Moment | AnkiConnect | Native example |
| --- | --- | --- |
| Open settings | Two parallel requests: decks and models | Two parallel requests: decks and models with fields |
| Select a model | One request for that model's fields | No request; read the loaded fields |

**Inside Tsunagi: shape the model data for the picker.** Once the model record
is loaded through Anki's model manager, its field names are already there:

```text
GET /v1/models?select=id,name,fields[].name
    load the Anki model records needed for the query
    take each model's ID, name and field names
    return them together; leave templates and styling out of the response
```

The picker receives a ready-to-use relationship: each model has its own fields.
An AnkiConnect client can prefetch those too, but it needs a `modelFieldNames`
action for each model and must combine the results itself. Putting those actions
in `multi` batches their transport; they remain separate actions.

The model record is still loaded internally; `select` trims the returned data.
The benefit here is getting related information together and keeping unused
model data out of the payload. Decks need a separate query, and `GET_PAGES`
follows any additional pages. A page size of ten may also load fields for models
the user never selects.

<details>
<summary>Implementation references and call checks</summary>

- [Batch validation and duplicate lookup](../tsunagi/adapters/anki/notes.py#L120-L243):
  the native adapter keeps request-local note-type/deck caches and uses Anki's
  duplicate search to collect IDs.
- [Note creation](../tsunagi/adapters/anki/notes.py#L251-L270) and
  [response construction](../tsunagi/adapters/anki/notes.py#L49-L73): reuse the
  created note and call `card_ids_of_note` for its card IDs.
- [Model adapters](../tsunagi/adapters/anki/models.py#L27-L40): read Anki's model
  records before the query response is projected to the requested fields.

A disposable-collection check confirmed that ten distinct duplicate candidates
sharing Basic / Default resolved the note type once and the deck once, with ten
Anki duplicate-ID searches. A native save made one `card_ids_of_note` call, zero
`find_cards` calls and zero `get_note` calls. These are adapter/API call counts,
not SQL-query counts or a latency benchmark.

These examples describe native requests. Existing Yomitan integrations can use
Tsunagi's AnkiConnect compatibility API and its shared adapters, but retain
Yomitan's separate action calls until the client adopts the native endpoints.

</details>

## What a real native integration still needs

This walkthrough covers the request flow, not a complete Yomitan port. Field
rendering and media handling still need to work, and the client must map Yomitan's
options, errors and update behavior. Native requests don't accept the complete
AnkiConnect note envelope unchanged: notice how duplicate options moved out of
`options` in the examples.

For paginated reads, keep the same query and pass `next_cursor` as `cursor` until
it becomes `null`. Browser clients also need an allowed origin and any configured
API key. Native requests use `X-API-Key` or a Bearer token; AnkiConnect requests
put the key in the JSON body's `key` property.

Use the [interactive reference](playground.md) for full request schemas,
[native discovery](capabilities.md) for supported operations and settings, and
[compatibility notes](ankiconnect_parity.md) for the existing AnkiConnect API.
