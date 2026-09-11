# Build with Tsunagi: API recipes

[← Back to the README](../README.md)

Suppose you're building a dictionary or mining app: the user chooses a note type,
saves a word to Anki, then looks up or corrects that note. These recipes walk
through that workflow using Tsunagi's native API.

| I want to… | Recipe |
| --- | --- |
| Populate a note-type picker | [Get names and fields together](#choose-a-note-type) |
| Save a flashcard | [Check and add a note](#add-a-note) |
| Find notes I've saved | [Search and page through results](#find-my-notes) |
| Correct a definition or add a tag | [Update a note](#update-a-note) |
| Keep my app up to date | [Follow collection activity](#follow-collection-activity) |

## Before you start

Keep Anki open with Tsunagi enabled. Examples use `http://127.0.0.1:7777`; replace
that address if you changed the port or imported AnkiConnect's settings.

The `curl` commands use POSIX shell syntax; on Windows, use Git Bash or WSL.
You can also enter the request body and parameters through **Test Request** in
the [interactive reference](http://127.0.0.1:7777/).

If you configured an API key, add `-H "X-API-Key: YOUR_KEY"` to native `curl`
requests. Native requests also accept `Authorization: Bearer YOUR_KEY`.
AnkiConnect requests instead put `"key": "YOUR_KEY"` in the JSON body.
Browser apps must also have their origin allowed in Tsunagi's **Access** settings.

> [!IMPORTANT]
> These requests use your open collection. The add and update recipes change it.
> Use a disposable Anki profile if you're just experimenting.

Three Anki terms matter here: a **note** holds fields and tags; a **model** (note
type) defines those fields and card templates; **cards** are generated from the
note and carry scheduling state. To save a flashcard, you usually create a note.

## Choose a note type

**“I want a picker that shows note types and the fields my app needs to fill.”**

Ask for names, IDs and field names together:

```sh
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=id,name,fields[].name' \
  --data-urlencode 'limit=10'
```

An entry in `items` looks like this; IDs and names depend on your collection:

```json
{
  "id": 1789162609922,
  "name": "Basic",
  "fields": ["Front", "Back"]
}
```

`select` leaves out data the picker doesn't need, such as card templates.
Selecting just `fields[].name` produces an array of names. Follow `next_cursor`
if the response has more pages, as shown in [Find my notes](#find-my-notes).

**With an AnkiConnect client:** a workflow can call `modelNames`, then
`modelFieldNames` for each name. For example, these JSON bodies go to `POST /`:

```json
{"action":"modelNames","version":6}
```

```json
{"action":"modelFieldNames","version":6,"params":{"modelName":"Basic"}}
```

`multi` can batch the field requests once the names are known. The client still
combines the results. The native query returns each type with its fields attached.

## Add a note

**“I want to save a word and its definition to Anki.”**

These examples assume a note type named **Basic** with **Front** and **Back**
fields, and a deck named **Default**. Use names from your own collection; list
decks with `GET /v1/decks?select=id,name&limit=10` if needed.

First, check whether the note can be added. This request adds nothing:

```sh
curl "http://127.0.0.1:7777/v1/notes:check" \
  -H "Content-Type: application/json" \
  -d '{"notes":[{
    "modelName":"Basic",
    "deckName":"Default",
    "fields":{"Front":"example","Back":"an illustration"},
    "tags":["tsunagi-guide"]
  }]}'
```

Read `results[0].can_add`. If false, inspect `state`, `reason` and
`duplicate_note_ids` before deciding what to show the user. A successful check
doesn't reserve the note; creation can still fail if the collection changes.

Create it with the same note data:

```sh
curl "http://127.0.0.1:7777/v1/notes" \
  -H "Content-Type: application/json" \
  -d '{
    "modelName":"Basic",
    "deckName":"Default",
    "fields":{"Front":"example","Back":"an illustration"},
    "tags":["tsunagi-guide"]
  }'
```

On success, HTTP **201** contains the note in `result`. Save `result.id` for later
updates; `result.cards` contains the generated card IDs. Anki creates the cards
from the note type's templates. Adding the same note again is rejected as a
duplicate by default.

**With an AnkiConnect client:** the corresponding actions are `canAddNotes` and
`addNote`. Tsunagi's compatibility API accepts those too; the native check also
explains why a candidate cannot be added.

## Find my notes

**“I want the notes my app saved, including their contents.”**

Search for the tag from the previous recipe and choose the returned fields:

```sh
curl --get "http://127.0.0.1:7777/v1/notes" \
  --data-urlencode 'search=tag:tsunagi-guide' \
  --data-urlencode 'select=id,fields,tags' \
  --data-urlencode 'limit=10'
```

`search` accepts Anki browser syntax. Replace it with `deck:Japanese`, for example,
to find notes with cards in that deck. `fields` here returns each field's name,
value and ordinal so your app can display the content.

Prefer JSON? This is the equivalent query:

```sh
curl "http://127.0.0.1:7777/v1/notes/query" \
  -H "Content-Type: application/json" \
  -d '{"search":"tag:tsunagi-guide","select":"id,fields,tags","limit":10}'
```

Read notes from `items`. Each page also has `stats` and `next_cursor`.
If `next_cursor` is not `null`, pass it as `cursor` with the **same query and
page size**. Stop at `null`; don't decode or modify cursor values.

This complete Python example prints every matching note, a page at a time:

```python
import json
from urllib.request import Request, urlopen

base_url = "http://127.0.0.1:7777"
headers = {"Content-Type": "application/json"}
# If configured: headers["X-API-Key"] = "YOUR_KEY"
query = {"search": "tag:tsunagi-guide", "select": "id,fields,tags", "limit": 10}

while True:
    request = Request(
        f"{base_url}/v1/notes/query",
        data=json.dumps(query).encode(),
        headers=headers,
    )
    with urlopen(request, timeout=30) as response:
        page = json.load(response)
    for note in page["items"]:
        print(note)
    if page["next_cursor"] is None:
        break
    query["cursor"] = page["next_cursor"]
```

**With an AnkiConnect client:** `findNotes` returns IDs, then `notesInfo` retrieves
their contents. The native query handles search, field selection and pagination
together. Use `select=id` if IDs are all you need.

## Update a note

**“I want to correct the definition and mark the note as checked.”**

Replace `NOTE_ID` with `result.id` from creation or an `items` entry from your query:

```sh
curl -X PATCH "http://127.0.0.1:7777/v1/notes/NOTE_ID" \
  -H "Content-Type: application/json" \
  -d '{"fields":{"Back":"a concrete illustration"},"addTags":["checked"]}'
```

The response contains the updated note in `result`. Only the supplied field is
changed; **Front** keeps its value. `addTags` appends to the existing tags. Use
`removeTags` to remove specific tags; `tags` replaces the entire tag list.

**With an AnkiConnect client:** `updateNoteFields` and `addTags` cover these changes
as separate actions, which can be batched with `multi`. Native `PATCH` accepts
the field and tag changes together.

## Follow collection activity

**“I want my app to refresh when something changes in Anki.”**

Open the Server-Sent Events stream:

```sh
curl -N "http://127.0.0.1:7777/v1/events"
```

Leave it running, then make a change in Anki. In a client, use incoming events to
trigger a fresh query. Delivery is best-effort, with no replay: refetch on a
`reset` event and after reconnecting. Not every operation emits an event, so this
isn't a complete change history. Press **Ctrl+C** to stop the command.

An existing AnkiConnect client keeps its polling behavior unless it adopts this
native stream.

## Where to go next

- **More operations:** browse cards, scheduling, media, import/export and other
  routes in the [interactive reference](http://127.0.0.1:7777/).
- **Version and settings support:** `GET /v1/capabilities` is the single native
  discovery report. It explains which operations are available, disabled in
  settings or unsupported. See [native discovery](capabilities.md).
- **Existing clients:** read the [AnkiConnect compatibility notes](ankiconnect_parity.md).
- **Working on Tsunagi itself:** use the [development guide](development.md).
