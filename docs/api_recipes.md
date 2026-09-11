# Yomitan's Anki workflow, with Tsunagi

[← Documentation](README.md) · [Install Tsunagi](../README.md#install)

Yomitan turns a dictionary entry into an Anki note. Let's follow the requests
behind three things you do in Yomitan: **choose a note type**, **check whether a
word is already saved**, and **add it to Anki**.

The AnkiConnect side below follows Yomitan's source at
[`d34832d`](https://github.com/yomidevs/yomitan/tree/d34832d756e05dc00945e5b7d7ebc80963299a7a).
The native side shows how a client could implement the same workflow with
Tsunagi. **Yomitan itself still uses AnkiConnect requests**; it can already send
those to Tsunagi's compatibility API. This guide doesn't install a native Yomitan integration.

| In Yomitan | Its AnkiConnect workflow | A native Tsunagi client could use |
| --- | --- | --- |
| Choose a deck and note type | `deckNames`, `modelNames`, then `modelFieldNames` for the selected type | Deck and model queries, with fields included in model results |
| Check whether a word is saved | `canAddNotesWithErrorDetail`, then a lookup for duplicate note IDs | `POST /v1/notes:check`, which includes duplicate IDs |
| Save the word | `addNote`, returning a note ID | `POST /v1/notes`, returning the note and generated card IDs |

## Try these examples

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

## 1. You choose a note type in Yomitan settings

**What Yomitan does.** Its settings controller fetches deck names and model names
in parallel. When a note type is selected, it requests that type's field names to
build the field-mapping controls. See the [settings controller](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/pages/settings/anki-controller.js#L439-L484)
and [field selection](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/pages/settings/anki-controller.js#L1100-L1170).

The [AnkiConnect wrapper](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/comm/anki-connect.js#L208-L234)
sends these action bodies to `POST /` (version/auth checks omitted here):

```json
{"action":"deckNames","version":6}
```

```json
{"action":"modelNames","version":6}
```

```json
{"action":"modelFieldNames","version":6,"params":{"modelName":"Basic"}}
```

**With native Tsunagi.** Fetch deck names with **`GET /v1/decks`** and note types
with **`GET /v1/models`**:

| Request | Query parameters |
| --- | --- |
| `GET /v1/decks` | `select=id,name` and `limit=10` |
| `GET /v1/models` | `select=id,name,fields[].name` and `limit=10` |

The model query returns entries like:

```json
{
  "items": [
    {"id": 1789162609922, "name": "Basic", "fields": ["Front", "Back"]}
  ]
}
```

**What changes for the app:** each model arrives with its field names attached,
so selecting a model already loaded doesn't need another field-name request.
Decks remain a separate query. Follow `next_cursor` when there are more pages;
`limit=10` is a page size, not a limit on the collection's note types.

## 2. You look up a word that's already in Anki

**What Yomitan does.** The backend checks candidate notes for duplicates through
`canAddNotesWithErrorDetail`. For duplicates, it then looks up matching note IDs;
it may also fetch additional information. This supports the existing-note behavior
in the popup. See [duplicate detection](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L651-L659)
and [assembling note information](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L705-L753).

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

**With native Tsunagi.** Send **`POST /v1/notes:check`**:

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

If the word is already present, a result includes:

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

If it can be added, `can_add` is `true` and `duplicate_note_ids` is empty.
The check doesn't add anything or reserve a note.

**What changes for the app:** the check returns the duplicate IDs directly, so
there's no separate ID lookup for this case. The client decides whether to offer
viewing, updating or adding a duplicate. Keep the user's choice: don't treat every
`can_add: false` as a duplicate; inspect `state` and `reason` for other problems.

The example deliberately uses collection-wide duplicate checking. A native port
must also map Yomitan's configured duplicate scope and related options; don't
silently substitute this example's policy for the user's settings.

## 3. You click the add-note button

**What Yomitan does.** The popup passes the prepared note to its backend, which
calls AnkiConnect's `addNote`. The returned note ID is used to update the popup's
existing-note controls. If enabled, Yomitan also requests suspension of the new
cards and a sync. See [the add-note handler](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/display/display-anki.js#L924-L961)
and [the backend call](https://github.com/yomidevs/yomitan/blob/d34832d756e05dc00945e5b7d7ebc80963299a7a/ext/js/background/backend.js#L621-L623).

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

**What changes for the app:** use `result.id` for the saved note and `result.cards`
for any card follow-up, such as suspension. Suspension and sync remain separate,
explicit requests. Keep them conditional on the user's settings.

To try the duplicate case in step 2, run its check again after saving this note.
Run only one of the two create requests unless you intend to test duplicate rejection.

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
