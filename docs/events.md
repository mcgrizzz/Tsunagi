# Listen for changes in Anki

[← Documentation](README.md)

`GET /v1/events` keeps a connection open and tells your app when something in
the collection changes, so it can update without polling.

## Try it

Start Anki, then run:

```sh
curl -N 'http://127.0.0.1:7777/v1/events?resources=notes'
```

Add a note in Anki (or through the API) and this arrives:

```text
event: ready
data: {"type":"ready","session_id":"5f0c…","after_seq":0,"ts":1790000000000,"resources":["notes"]}

event: notes.created
id: 5f0c…:1
data: {"type":"notes.created","ids":[1790000000123],"origin":"ui",…}
```

`ready` means you're connected: load the data you show now. After that, each
message names what changed and gives the IDs. Messages carry IDs, not
contents; fetch what you need through the normal API.

If your app has a key, add `-H 'X-Api-Key: <key>'`. Use your port if it isn't
`7777`.

## The messages

| Message | Means |
| --- | --- |
| `notes.created` | These notes were added. |
| `notes.updated` | These notes changed. |
| `notes.deleted` | These notes are gone. |
| `notes.stale` | Some notes changed, but Tsunagi can't say which (after an undo or a sync, for example): reload the notes you show. |
| `cards.created`, `cards.updated`, `cards.deleted`, `cards.stale` | The same, for cards. |
| `cards.answered` | A card was answered, in Anki or through the API: which card, the button, and the card's new interval, due date and memory state. |
| `reviews.created` | Rows were added to the review history. Includes their IDs. |
| `sync` | A sync started or finished. |
| `decks.counts` | A deck's new, learning or review counts changed. |
| `decks.stale`, `models.stale`, `tags.stale`, … | That kind of thing changed. |

One change can produce several messages. Deleting a note sends
`notes.deleted` with its ID and `cards.stale`, because its cards went with it.
Answering a card in Anki sends `cards.answered` for the card and
`reviews.created` for the row it added to the review history. Setting a due
date or forgetting a card also adds a row, so it sends `reviews.created` but
not `cards.answered`.

## Choose what to receive

| You want | Ask for |
| --- | --- |
| Every change to notes | `?resources=notes` |
| Notes and cards | `?resources=notes,cards` |
| Only note deletions | `?types=notes.deleted` |
| Card answers | `?types=cards.answered` |
| Sync start and finish | `?types=sync` |
| Due counts for a deck list | `?types=decks.counts` |

To keep a list of notes up to date, use `resources=notes`. An exact type such
as `types=notes.deleted` leaves out `notes.stale`, so it can miss a deletion
Tsunagi couldn't give IDs for.

Your app must be allowed to read the collection. Card answers (`cards.answered`,
`reviews.created`) are only sent to apps allowed to see review activity; by
default that is the Everything role.

## React in your app

Keeping a note list current takes one listener per message. `loadAll`,
`loadNotes` and `removeNotes` are your app's own functions: they call
`/v1/notes` and update what you show.

```js
const events = new EventSource("http://127.0.0.1:7777/v1/events?resources=notes");
const ids = (message) => JSON.parse(message.data).ids;

events.addEventListener("ready", () => loadAll());          // connected: load your list
events.addEventListener("notes.created", (m) => loadNotes(ids(m)));
events.addEventListener("notes.updated", (m) => loadNotes(ids(m)));
events.addEventListener("notes.deleted", (m) => removeNotes(ids(m)));
events.addEventListener("notes.stale", () => loadAll());    // changed, but not which
events.addEventListener("gap", () => loadAll());            // messages were missed
```

`loadNotes` asks for just those notes:
`GET /v1/notes?where=id in [123,456]&select=id,fields,tags`. If your app has a
key, add `&api_key=<key>` to the events URL; a browser `EventSource` can't send
headers. It also reconnects by itself, and `ready` then reloads the list.

Two things to watch:

- **Overlapping loads.** A message can arrive while a load is still running.
  Let only the newest load update your list, so an older response doesn't
  undo a newer one.
- **Searches.** If your list is a search, a note can leave or join it without
  a `notes.*` message you'd act on: an updated note may no longer have your
  `tag:verb`, a renamed deck changes `deck:Japanese` results, and answering
  cards changes `is:due`. Listen to each kind of thing your search names (for
  example `resources=notes,decks`), and when in doubt run `loadAll()` instead
  of `loadNotes(ids)`.

<details>
<summary>What every message contains</summary>

```text
event: notes.updated
id: 5f0c…:42
data: {"origin":"api","client":"Yomitan","anki":{"changes":["note","mtime","browser_table","note_text"],"label":"Update Note"},"type":"notes.updated","ids":[123],"seq":42,"session_id":"5f0c…","ts":1790000000000}
```

| Field | Meaning |
| --- | --- |
| `type` | The message name, also sent as `event:`. |
| `ids` | The IDs that changed. Not on `.stale`. |
| `origin` | `api` for changes made through either API, `ui` for changes made in Anki. |
| `client` | For changes made through the API: the app that made them. A dashboard can tell its own writes from another tool's. |
| `seq`, `session_id`, `ts` | Order, server session and time (milliseconds). The `id:` line is `session_id:seq`. |
| `anki` | Anki's own description of the change. For debugging; don't rely on it. |

Other messages:

```text
event: cards.answered
data: {"origin":"ui","card_id":1700000000001,"ease":3,"interval":12,"due":20512,"queue":2,"memory_state":{"stability":14.2,"difficulty":5.1},"type":"cards.answered",…}

event: sync
data: {"phase":"started","type":"sync",…}

event: decks.counts
data: {"decks":[{"id":1,"new_count":20,"learn_count":3,"review_count":41,"total_in_deck":1280}],"type":"decks.counts",…}
```

`ease` is 1 Again, 2 Hard, 3 Good, 4 Easy. `memory_state` is `null` for cards
FSRS hasn't scheduled. `sync` comes with `phase` `started`, then `finished`.
`decks.counts` lists only the decks whose counts changed.

</details>

<details>
<summary>When messages arrive, and which changes give IDs</summary>

Changes made through the API are announced immediately. Changes made in Anki
(the Browser, the editor, the Add dialog, the reviewer) are announced about
half a second after they stop; while you type, once typing pauses for two
seconds.

| Change | Message |
| --- | --- |
| Create notes through either API | `notes.created`, and `cards.created` for their cards |
| `POST /v1/notes:upsert` | `notes.created` and `notes.updated`; new cards as `cards.stale` |
| Update notes, or add or remove their tags, through either API | `notes.updated` |
| Delete notes through either API | `notes.deleted` |
| Answer, suspend, bury, flag, move, forget or reschedule cards through the API | `cards.updated` |
| Changes made in Anki | `notes.*`, `cards.*` and `reviews.created`, with IDs |
| Undo in Anki | `.stale` for what it touched (undo restores rows as they were, so they can't be found by what changed) |
| A sync | `.stale` for everything (Anki reports that anything may have changed) |
| More than 1,000 IDs from one operation | `.stale` |

An operation that changes nothing sends nothing. Changes other add-ons make
without telling Anki are reported with the next change Anki does announce.

</details>

<details>
<summary>Connection messages</summary>

- `ready`: you're connected. Sent first on every connection.
- `gap`: your connection fell behind and `discarded` messages were lost.
  Reload what you show.
- `close`: the server ended the stream. `reason` is `profile_closed` (the
  profile was closed; reconnect with a backoff until one is open again),
  `auth` (your key or permissions changed; reconnect), `shutdown`, or
  `timeout` / `max_events` if you asked for a limit.

Missed messages aren't replayed after a reconnect: load your data again on
the new `ready`. A new `session_id` means a new server session.

</details>

The [interactive reference](playground.md) lists every filter and field under
**GET /v1/events**.
