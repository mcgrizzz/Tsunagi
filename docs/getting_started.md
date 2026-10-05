# Build your first Tsunagi integration

[← Documentation](README.md) · [Install Tsunagi](../README.md#install)

Five requests that cover how the Tsunagi API works: check the connection, add
a note, read it back, undo it, and send an app key. Anki must be open with a
profile loaded. The examples use `curl` and the default port, 7777.

Step 2 changes your collection and step 4 undoes it. To be safe, try this in
a throwaway profile (**File → Switch Profile → Add**).

## 1. Check the connection

```sh
curl http://127.0.0.1:7777/v1/health
```

```json
{
  "ok": true, "server": "tsunagi", "version": "0.7.0",
  "versions": {"api": "v1", "addon": "0.7.0", "anki": "26.09.3"},
  "port": 7777,
  "collection": {"profile": "User 1", "state": "ready"},
  "caller": {"name": "No key, this computer", "role": "Default", "enabled": true,
             "key": "none", "this_computer": true, "host": "127.0.0.1:7777"}
}
```

`caller` is who your requests count as. Without a key, a program on this
computer gets the Default role, which can read and change the collection.

## 2. Add a note

```sh
curl http://127.0.0.1:7777/v1/notes -H 'Content-Type: application/json' -d '
  {"deckName": "Default", "noteTypeName": "Basic",
   "fields": {"Front": "犬", "Back": "dog"}, "tags": ["tsunagi-test"]}'
```

```json
{"created": [{"index": 0, "id": 1791145125487}], "failed": []}
```

Writes report each input: what was `created` and what `failed`, and why. Send
an array to add several notes in one request. To retry a write safely after a
timeout, add an `Idempotency-Key` header with a new UUID, and send the same
key again: the retry returns the first result instead of adding the note
twice. [Creating notes](creating_notes.md) covers duplicates, media and
failures.

## 3. Read it back

```sh
curl --get http://127.0.0.1:7777/v1/notes \
  --data-urlencode 'search=tag:tsunagi-test' \
  --data-urlencode 'select=id,fields,tags'
```

```json
{
  "items": [{"id": 1791145125487,
             "fields": [{"name": "Front", "value": "犬", "index": 0},
                        {"name": "Back", "value": "dog", "index": 1}],
             "tags": ["tsunagi-test"]}],
  "next_cursor": null
}
```

Every list works this way, whether notes, cards, reviews, decks, note types,
tags or media:

- `search` takes Anki's browser syntax (`deck:Mining`, `is:due`), on notes,
  cards and reviews.
- `where` filters on the fields you get back (`where=first_field in ["犬"]`).
- `select` picks those fields; leave it out for all of them.
- `order` sorts, and `limit` with `next_cursor` reads a page at a time.

## 4. Undo it

```sh
curl -X POST http://127.0.0.1:7777/v1/gui:undo
```

```json
{"undone": "Add Note", "stats": {"duration_ms": 18.5}}
```

`undone` names the step, as Anki's Edit menu does; it's `null` when there's
nothing to undo. The note from step 2 is gone: step 3's request now returns
`{"items": [], "next_cursor": null}`. API writes are Anki operations, so
they're on Anki's undo list like anything you do in its windows, and
**Edit → Undo** works on them too. Media files and some add-on actions
are the exceptions.

## 5. Give your app a key

Programs on this computer work without a key, but a key lets the user decide
what your app may do, and turn it off.

![The Apps & keys page in Tsunagi's settings](images/settings-apps.png)

1. In **Tools → Tsunagi Settings → Apps & keys**, click **Add app**, name it
   and pick a role, such as Read-only. Copy its key.
2. Send it with every request: `curl -H 'X-Api-Key: <key>' …`.
3. `GET /v1/health` now names your app and its role in `caller`. A request
   the role doesn't allow gets 403 naming the app, the role and what's missing.

[API discovery](capabilities.md) reports everything your app may do in one
request, so it can hide what it can't use.

## Next

- **Every operation:** the [API reference](https://mcgrizzz.github.io/Tsunagi/),
  or the [interactive one in Anki](playground.md) that sends real requests.
- **Notes and media:** [creating notes](creating_notes.md), with duplicate
  checks and adding to a note you already have.
- **Live updates:** [events](events.md) tell your app what changed, so it
  doesn't poll.
- **A real integration:** the [Yomitan case study](api_recipes.md) takes an
  AnkiConnect integration request by request.
- **Who can call what:** the [security model](security.md), and roles in the
  [settings reference](../config.md#roles).
- **TypeScript:** the [client](../packages/typescript/README.md) does all of
  this with typed queries and named values.
