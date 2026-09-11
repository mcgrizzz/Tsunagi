# API recipes: save a word to Anki

[← Back to the README](../README.md)

**Goal:** choose a note type, save a word, find the saved note, and correct its
meaning. Follow all four steps, or jump to the task you need.

| I want to… | Request |
| --- | --- |
| [Choose a note type](#1-choose-a-note-type) | `GET /v1/models` |
| [Save a word](#2-save-a-word) | `POST /v1/notes` |
| [Find my saved notes](#3-find-my-saved-notes) | `GET /v1/notes` |
| [Correct a note](#4-correct-a-note) | `PATCH /v1/notes/{note_id}` |

## Try the requests

1. Keep Anki open with Tsunagi enabled.
2. Open the [interactive reference](http://127.0.0.1:7777/). Use your configured
   port if it differs from `7777`.
3. Find the method and path shown below, then use **Test Request**. Enter the
   listed query parameters or paste the JSON body. If you set an API key, enter
   it in the reference's authentication controls.

Each step shows **what to send** and **what to look for in the response**.
Response examples show only the relevant fields; your IDs will be different.
Terminal commands are available under each step if you prefer `curl`.

> [!IMPORTANT]
> Steps 2 and 4 change your open Anki collection. Use a disposable profile to try
> the whole walkthrough without adding a sample note to your usual collection.

## 1. Choose a note type

**“Which fields does my app need to fill?”**

Send **`GET /v1/models`** with these query parameters:

| Parameter | Value |
| --- | --- |
| `select` | `id,name,fields[].name` |
| `limit` | `10` |

**Look for:** each note type's name and field names in `items`:

```json
{
  "items": [
    {"id": 1789162609922, "name": "Basic", "fields": ["Front", "Back"]}
  ]
}
```

We'll use **Basic**, **Front** and **Back** below. Replace those names if your
collection uses different ones. “Model” is the API's name for an Anki note type.
If `next_cursor` isn't `null`, there are [more pages](#more-than-one-page).

<details>
<summary>Run this with curl</summary>

```sh
curl --get "http://127.0.0.1:7777/v1/models" \
  --data-urlencode 'select=id,name,fields[].name' \
  --data-urlencode 'limit=10'
```

</details>

## 2. Save a word

**“Add ‘example’ to my Default deck, with a meaning on the back.”**

Send **`POST /v1/notes`** with this JSON body:

```json
{
  "modelName": "Basic",
  "deckName": "Default",
  "fields": {
    "Front": "example",
    "Back": "an illustration"
  },
  "tags": ["tsunagi-guide"]
}
```

**Change before sending:** the note type, field names or deck if yours differ.
This example requires an existing deck named **Default**. List your decks with
`GET /v1/decks` if needed.

**Look for:** HTTP **201**, with the new note's ID in `result.id`:

```json
{
  "result": {
    "id": 1789162609990,
    "cards": [1789162609990]
  }
}
```

**Keep your returned note ID for step 4.** You created a note containing the word
and meaning; Anki generated its cards from the note type's templates.
Sending the same note again is rejected as a duplicate by default.

<details>
<summary>Run this with curl</summary>

```sh
curl "http://127.0.0.1:7777/v1/notes" \
  -H "Content-Type: application/json" \
  -d '{"modelName":"Basic","deckName":"Default","fields":{"Front":"example","Back":"an illustration"},"tags":["tsunagi-guide"]}'
```

</details>

## 3. Find my saved notes

**“Show me the notes tagged by my app.”**

Send **`GET /v1/notes`** with these query parameters:

| Parameter | Value |
| --- | --- |
| `search` | `tag:tsunagi-guide` |
| `select` | `id,fields,tags` |
| `limit` | `10` |

**Look for:** the note from step 2 in `items`, including its field values:

```json
{
  "items": [{
    "id": 1789162609990,
    "fields": [
      {"name": "Front", "value": "example", "ord": 0},
      {"name": "Back", "value": "an illustration", "ord": 1}
    ],
    "tags": ["tsunagi-guide"]
  }],
  "next_cursor": null
}
```

An empty `items` list means no notes matched. `next_cursor: null` means this is
the last page. `search` uses Anki browser syntax: try `deck:Japanese` to search
for notes with cards in that deck instead.

<details>
<summary>Run this with curl</summary>

```sh
curl --get "http://127.0.0.1:7777/v1/notes" \
  --data-urlencode 'search=tag:tsunagi-guide' \
  --data-urlencode 'select=id,fields,tags' \
  --data-urlencode 'limit=10'
```

</details>

## 4. Correct a note

**“Change the meaning and mark the note as checked.”**

Send **`PATCH /v1/notes/{note_id}`**. Set `note_id` to **your returned ID from
step 2**, then use this JSON body:

```json
{
  "fields": {"Back": "a concrete illustration"},
  "addTags": ["checked"]
}
```

**Look for:** the updated note in `result`. Its Back field now contains
`a concrete illustration`, and its tags include both `tsunagi-guide` and `checked`.
The Front field keeps its previous value.

Use `addTags` to keep existing tags and add more. The separate `tags` property
replaces the whole tag list.

<details>
<summary>Run this with curl — replace NOTE_ID first</summary>

```sh
curl -X PATCH "http://127.0.0.1:7777/v1/notes/NOTE_ID" \
  -H "Content-Type: application/json" \
  -d '{"fields":{"Back":"a concrete illustration"},"addTags":["checked"]}'
```

</details>

## How this compares with AnkiConnect

These are equivalent client workflows. Existing AnkiConnect requests also work
through Tsunagi's compatibility API.

| Task | AnkiConnect workflow | Native Tsunagi workflow |
| --- | --- | --- |
| Note-type picker | `modelNames`, then `modelFieldNames` for each name | One models query returns names and fields together. |
| Save a word | `addNote` | Create a note with `POST /v1/notes`. |
| Find notes and their contents | `findNotes`, then `notesInfo` for the returned IDs | One notes query searches and returns the selected data. |
| Correct a field and add a tag | `updateNoteFields` and `addTags` | One `PATCH` accepts both changes. |

AnkiConnect's `multi` can batch actions. Native queries let the client ask for the
combined result directly, with field selection and pagination.

## More than one page

For any paginated query, read results from `items`. If `next_cursor` is not
`null`, send the same query again with that value as `cursor`. Keep the other
parameters unchanged. Stop when `next_cursor` is `null`.

<details>
<summary>Python example: read all matching notes</summary>

This uses the POST form of the step 3 query. Update the address and API key if
needed. `POST /v1/notes/query` searches; `POST /v1/notes` creates a note.

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

</details>

## Other tasks

| I want to… | Use |
| --- | --- |
| Check for duplicates before adding | `POST /v1/notes:check`, with candidate notes in a `notes` array. Inspect each result's `can_add` and `reason`. The check adds nothing and doesn't reserve the note. |
| Refresh my app after changes | `GET /v1/events`. Refetch on `reset` or reconnection; delivery is best-effort, without replay or a complete change history. |
| Check what this Anki version supports | [`GET /v1/capabilities`](capabilities.md), the single native report of available, disabled and unsupported operations. |

For full request schemas, errors and more operations, use the
[interactive reference](http://127.0.0.1:7777/). See
[compatibility notes](ankiconnect_parity.md) for AnkiConnect differences.

<details>
<summary>Terminal and authentication notes</summary>

The curl examples use POSIX syntax; on Windows, run them in Git Bash or WSL.
Replace `http://127.0.0.1:7777` if your port differs. For native requests with an
API key, add `-H "X-API-Key: YOUR_KEY"`; `Authorization: Bearer YOUR_KEY` also works.
AnkiConnect requests put `"key": "YOUR_KEY"` in the JSON body instead.
Browser apps also need their origin allowed under Tsunagi's **Access** settings.

</details>
