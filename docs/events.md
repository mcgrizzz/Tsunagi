# Event stream

[← Documentation](README.md)

When a note is saved through Tsunagi’s native API, a subscriber can receive the
saved note in the event itself. Put it into your interface’s data store—there is
no need to fetch that note again.

When a complete record isn’t available, the event gives you IDs to fetch. A
broader refresh is the fallback when Anki doesn’t identify the affected records.

## Subscribe to what you use

Anki must be running. Use your configured port if different:

```sh
curl -N 'http://127.0.0.1:7777/v1/events?resources=notes'
```

| I want… | Query | Notifications |
| --- | --- | --- |
| Note changes | `resources=notes` | `change`, plus `refresh` when needed |
| Note and card changes | `resources=notes,cards` | Same, scoped to those resources |
| Reviewer answers | `types=review` | `review`, with `card_id` and `ease` |
| Sync progress | `types=sync` | `sync`, with `phase: started/finished` |

Filtering happens before your queue: unrelated traffic cannot fill it.

## Apply a saved note directly

A `change` event separates the work your client can do:

| Field | What to do |
| --- | --- |
| `changes.notes.upsert` | Insert or replace these complete note records. They use the native API’s note response shape. |
| `changes.notes.fetch` | Fetch these IDs; the event doesn’t contain their records. |
| `changes.notes.remove` | Remove these IDs from your data store; they are now absent. |
| `refresh` | Reload your displayed query for these resources. Their affected records weren’t fully identified. |

Cards use the same keys under `changes.cards`. For a native note save, the note
is in `upsert` and `refresh` does **not** include `notes`.

This JavaScript illustrates the handling; the data-store and fetch helpers belong
to your app:

```js
const events = new EventSource("http://127.0.0.1:7777/v1/events?resources=notes");

events.addEventListener("change", ({data}) => {
    const event = JSON.parse(data);
    const notes = event.changes.notes;
    if (notes) {
        for (const note of notes.upsert) notesById.set(note.id, note);
        for (const id of notes.remove) notesById.delete(id);
        if (notes.fetch.length) fetchNotesById(notes.fetch);
    }
    if (event.refresh.includes("notes")) reloadDisplayedNotes();
    renderNotes();
});

events.addEventListener("refresh", () => reloadDisplayedNotes());
```

`refresh` also supplies the initial load and recovery after a reconnect. It asks
for your app’s current view, not the whole collection. Ordinary saved-editor
notifications keep the typing debounce: 300 ms of quiet, at most one second
while typing continues. API writes arrive without that debounce.

<details>
<summary>Which operations supply records or IDs?</summary>

| Operation | Useful event data |
| --- | --- |
| Native note creation or patch | Full note in `upsert`, reused from the save response |
| Native note creation | Generated card IDs in `changes.cards.fetch` |
| AnkiConnect-compatible note creation or field update | Saved note ID in `fetch` |
| Note deletion, native or compatibility API | Note IDs in `remove` |
| Suspend, unsuspend, bury, unbury | Card IDs in `fetch` |
| Supported editor/Add-dialog saves | Saved note IDs in `fetch`, after any typing debounce |
| Other operations, general UI activity, undo, sync | Scoped refresh where precise coverage is unavailable |

A `fetch` list can include an unchanged or missing ID. Read the listed records,
and remove IDs no longer found. For example, query `/v1/notes` with
`where=id in [123,456]` and follow pagination. `remove` means the ID is absent
after successful removal; it doesn’t claim every ID existed beforehand.

Related resources can still need refreshing: deleting notes doesn’t give us all
of their deleted card IDs; patching a note can change its generated cards. These
remain explicit in `refresh` for subscribers interested in cards.

Native saves read the persisted note once, including Anki’s normalized tags and
metadata. Events reuse that result; they add no per-subscriber reads or card
rendering. Result details are copied once before the
operation’s success callback and shared across subscribers. Snapshots over the
64 KiB result-detail budget become ID fetches; sets over 1,000 IDs per resource
fall back to refresh. No cross-request collection cache is involved.

</details>

<details>
<summary>Queries, loading, and event ordering</summary>

A full record describes that operation’s result. Apply live events in stream
order. An HTTP fetch may finish after a newer event: don’t let its older response
overwrite that event. While loading, mark the view dirty if another change
arrives, then re-read after the load before treating the view as current. On
connection loss, discard outstanding loads and start again at the next initial
refresh. The short example above omits this application-specific coordination.

Updating a record store is different from maintaining a filtered or paginated
query. A changed note can enter or leave an Anki search, and `notes` records do
not contain every dependency of that search. If your client cannot evaluate
membership, sorting or counts itself, rerun its displayed query. An empty
`refresh` means the event covered the affected records for that resource; it
doesn’t guarantee your query’s membership or page boundaries stayed the same.

Live events contain `session_id`, `seq`, and `ts` (Unix milliseconds). Their SSE
ID is `<session_id>:<seq>`. Subscription registration and the initial refresh’s
`after_seq` boundary are captured together; subsequent notifications have larger
sequence numbers. Filtering naturally leaves gaps in sequence numbers.
Resources and record details are scoped to each subscriber.

</details>

<details>
<summary>Other filters, recovery, and coverage</summary>

**Filters.** `resources` accepts `notes`, `cards`, `models`, `decks`, `tags`,
`reviews`, `scheduler`, and `config`. Combine note changes with reviewer answers
using `?types=change,review&resources=notes`. With no filters, receive all activity.
`types=refresh` explicitly selects the older invalidation-only presentation,
without records. If selecting both `change` and `refresh`, changes are delivered
once, in the richer form. Empty, unknown or incompatible filters return HTTP 422.

**Refresh boundaries.** A data subscription starts with reason `initial`.
Broad Anki invalidations use `collection`. If the bounded queue overflows, the
incomplete backlog is discarded: a `gap` notice reports `reason: lagged` and its
`discarded` count, followed by `refresh` reason `recovery`. No acknowledgement is
required. Initial/recovery refreshes and gaps use `after_seq`, not an SSE ID.

**Reconnects.** Delivery is live-only and best-effort. `Last-Event-ID` doesn’t
replay missed events. Reconnects get a fresh initial refresh; profile switches
and server restarts also change the session ID. Reviewer-only and sync-only
subscriptions receive no refreshes. If counting reviewer answers, treat a gap
or disconnect as incomplete delivery.

**Closing.** `close` gives the reason: `shutdown`, `auth` (API key changed),
`timeout`, or `max_events`. Heartbeat comments keep idle connections alive.
Initial refreshes and gap notices don’t count toward `max_events`; recovery
refreshes do. No active collection session returns HTTP 503.

**Diagnostics.** `origin` is `api`, `ui`, or null. `action` and raw `anki` flags
can help debugging; don’t parse localized labels for application logic.
`targets` retains input/context hints for uncovered operations. Unlike `changes`,
these hints don’t establish complete coverage and must not imply deletion.

**Limits.** General and detailed editor notifications can overlap. Event counts
are not mutation counts. Media/import coverage is incomplete; another add-on’s
direct database edits may bypass hooks. Browser EventSource can supply a
configured key through the `api_key` query parameter.

</details>

See the [interactive reference](playground.md) for full endpoint details.
