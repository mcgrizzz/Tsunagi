# Event stream

[← Documentation](README.md)

Events tell your app when its Anki data may have changed, so it can refresh
without repeatedly checking. Your app chooses what it wants to hear about.

## Choose what you receive

Connect to `http://127.0.0.1:7777/v1/events` with one of these queries.
Anki must be running; use your configured port if different.

| I want to… | Add to the URL | Listen for |
| --- | --- | --- |
| Keep notes up to date | `?resources=notes` | `refresh` |
| Keep notes and note types up to date | `?resources=notes,models` | `refresh` |
| React when a card is answered | `?types=review` | `review` |
| Follow sync progress | `?types=sync` | `sync` |

## Example: keep a note list up to date

Try the subscription in a terminal:

```sh
curl -N 'http://127.0.0.1:7777/v1/events?resources=notes'
```

Or listen in your browser app:

```javascript
const stream = new EventSource("http://127.0.0.1:7777/v1/events?resources=notes");
stream.addEventListener("refresh", () => requestNotesRefresh());
```

**The first `refresh` tells you to load your notes. Later ones tell you to update
them.** The same handler works after reconnecting or syncing. Refresh the data
your interface displays; you don't need to download the entire collection.

`requestNotesRefresh()` is your app's reload function. It should:

- Run one read at a time. If a notification arrives during a read, read again afterward.
- Discard unfinished reads when the connection fails or closes. Start again on the next connection's initial `refresh`.

Tsunagi groups ordinary typing notifications: after **300 ms of quiet**, or at
most **1 second** during continuous editing, plus delivery delay. Anki still saves
normally, and your reads return current data.

If you use an API key, add `api_key=YOUR_KEY` to the browser connection URL.
Other clients can send `X-API-Key` or a Bearer token.

## Using reviewer or sync events

A `review` event gives you `card_id` and `ease` (1 = Again, 2 = Hard, 3 = Good,
4 = Easy). A `sync` event gives you `phase`: `started` or `finished`.
These subscriptions don't receive note-refresh requests.

Delivery is best-effort. If your app counts reviewer answers, a `gap` means some
notifications were lost; mark the count incomplete. Missed events aren't replayed
on reconnect. A refresh subscription recovers by requesting current data through
its normal handler.

<details>
<summary>More subscription options and event fields</summary>

**Filters.** `resources` accepts `notes`, `cards`, `models`, `decks`, `tags`,
`reviews`, `scheduler`, and `config`. `types` accepts `refresh`, `review`, and
`sync`. Separate values with commas. To combine note refreshes with answers, use
`?types=refresh,review&resources=notes`.

Supplying `resources` alone selects refresh events. If you also supply `types`,
it must include `refresh`. Omit both filters to receive everything. Empty,
unknown, or incompatible filter values return HTTP **422**.

Filtering happens before notifications enter your queue. Related changes count:
a deck rename can affect a note query using `deck:...`. Broad or unknown changes
refresh your subscribed views.

**Refresh fields.** The relevant part of a note update can look like this:

```json
{
  "type": "refresh",
  "reason": "change",
  "resources": ["notes"],
  "targets": {"notes": [1789162609990]}
}
```

`resources` lists subscribed views that may need refreshing. `reason` is `initial`,
`change`, `collection` (broad Anki invalidation), or `recovery` (after a delivery
gap). All four can use the same handler.

`targets` contains known IDs within those views, or an empty object. These are
hints, not a complete change set: an edit can also affect related records or
which results match a query. Selected Tsunagi mutations and supported editor/Add
saves supply IDs; other UI actions, undo and sync may not. API note creation
returns its ID in the HTTP response, but its general event doesn't yet include it.

Optional `origin`, `action`, and `anki` fields describe the mutation. Actions are
`notes.created`, `notes.updated`, or `collection.changed`; origin is `api`, `ui`,
or null when unknown. Anki flags and localized labels are for diagnostics, not
required for refreshing data.

</details>

<details>
<summary>Connection and delivery details</summary>

**Queue overflow.** `gap` reports a lost backlog with reason `lagged` and a
`discarded` notification count. Refresh subscribers immediately receive a scoped
recovery refresh. Review/sync-only clients receive the delivery notice without a
refresh request. No message needs acknowledgement.

**Closing.** `close` gives the reason: `shutdown`, `auth`, `timeout`, or
`max_events`. For `auth`, reconnect with the current API key. Heartbeat comments
keep idle connections alive. `max_events` counts delivered notifications,
including recovery refreshes; initial refresh and gap notices don't count.

**Ordering.** The initial refresh marks when your subscription started. Changes
arriving before you receive it are already queued. Live notifications carry
`session_id`, `seq`, and `ts` (Unix milliseconds), with SSE ID `<session_id>:<seq>`.
Initial/recovery refreshes and gaps instead have `after_seq`, with no SSE ID;
subsequent live events have greater sequence numbers. Filtering can leave normal
gaps in those numbers. Event IDs are shared across subscribers, while resources
and target hints are scoped to each subscription.

**Reconnecting.** Server restarts and profile switches create a new session ID
and close old streams. A reconnect to the same running session still starts
fresh. `Last-Event-ID` doesn't replay missed events, and `gap` doesn't detect every
network loss. Separate HTTP reads aren't an atomic collection snapshot.

**Timing and coverage.** API writes, reviews, undo, known creation/deletion and
broader changes bypass typing debounce. Other activity and new subscriptions
flush pending edits first. General and detailed editor notifications can overlap;
notification counts aren't mutation counts. Media/import coverage is incomplete,
and another add-on's direct database edits may bypass hooks. No active session
returns HTTP **503**.

Earlier development versions used public `ready`, `change`, and `reset` events.
These are now `refresh`; its `resources` field replaces the old `refresh` field.

</details>

See the [interactive reference](playground.md) for the full endpoint description.
