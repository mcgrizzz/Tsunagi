# Tsunagi TypeScript client — working draft

This is a **private, unpublished prototype** for trying the client experience
while Tsunagi's API design rules are changing. Names, signatures, and wire
mappings can change. It has no runtime dependencies and uses standard Fetch,
AbortSignal, and Web Crypto APIs for browsers and Node.js.

Its version is Tsunagi's: each release of the add-on ships the client it was
tested against, and Tsunagi's CI runs this package's tests and a live run
against the real server (`tests/test_typescript_client.py`) on every push.

## Try the draft

From this directory:

```sh
npm install
npm test
```

`npm test` builds ESM/declarations, checks examples and expected TypeScript
errors, and runs the runtime tests. Development was checked on Node 22.14.0.
The runtime tests include real HTTP against a local fixture, not a running Anki
collection. Browser and live-Anki verification remain follow-up work.

After building, an application can import the local package's `dist/index.js`:

```ts
import { Tsunagi } from "./dist/index.js";

const anki = new Tsunagi({
  baseUrl: "https://your-tsunagi-server.example/",
  apiKey: () => settings.apiKey,
});

const cards = await anki.cards
  .search("is:due")
  .where("interval", "gte", 30)
  .select("id", "question")
  .take(20);

// cards contains only id and question. question can be null.
```

The browser example at [examples/browser.html](examples/browser.html) makes only
reads and lets you enter the server URL and key. Serve this package directory
over HTTP, open that page, and allow its origin in Tsunagi. The key stays in
memory. `examples/workflow.ts` provides a typed create/update/query/sync example;
it is a function to call explicitly, and it performs writes.

## Identity, roles, and permissions

The entry point is now `new Tsunagi(options)`. Construction does no I/O. The
earlier factory name was removed from this private draft; examples and tests
use the constructor.

`apiKey` is optional. With no key, Tsunagi applies the configured **No key,
this computer** or **No key, other devices** role, based on how the server sees
the request. A No key role with no access produces 401. An unrecognized key
can also resolve to the No key caller; supplying a string is not proof that
Tsunagi recognized the intended app. Inspect the reported caller.

```ts
const anki = new Tsunagi({ baseUrl }); // optional apiKey or key provider
const access = await anki.access();   // one GET /v1/capabilities

console.log(access.caller.name, access.caller.role);
const canCreate = access.can(anki.notes.create); // pass the method, don't call it

const creation = access.check(anki.notes.create);
if (!creation.allowed) {
  showMessage(creation.reason);
  console.log(creation.permission); // e.g. "write:notes", when reported
}
```

Checks use effective operation availability, not role-name comparisons. A role
is a display name and may be custom. `check()` distinguishes `available`,
`disabled`, `unsupported`, and `unknown` (not reported by this server).
`can(target)` is shorthand for `check(target).allowed`: it returns true only
for `available`. `check(target)` retains the status and explanation. Both are
synchronous, local checks against that snapshot.

Pass a query or a supported method reference; the client owns the endpoint
mapping. Method references include `notes.create`, `notes.createMany`,
`notes.update`, `collection.sync`, and `collection.startSync`. Existing string
aliases remain accepted for draft compatibility but are deprecated.

```ts
const due = anki.cards.search("is:due").select("id", "question");
const decision = await due.checkAccess(); // fresh discovery; doesn't run due

// Alternatively, reuse the snapshot already fetched above:
access.check(due);
access.can(due);

const screen = access.checkMany({
  dueCards: due,
  addNote: anki.notes.create,
  sync: anki.collection.sync,
});

console.log(screen.allowed);              // every check is available
console.log(screen.checks.addNote.reason); // each result stays available
```

`checkMany` performs no network calls or writes. Fetching one snapshot with
`anki.access()` supplies all checks; no server bulk endpoint is necessary.
Result keys are your own UI labels, inferred by TypeScript. An empty group has
no requirements and reports `allowed: true`. A snapshot accepts targets only
from the client that fetched it, preventing accidental checks against another
server or credential configuration. Changing credentials on that client still
requires a fresh snapshot.

Checks report advertised operation availability, not validation of a complete
request or every conditional option. A query carries its resource's list
operation through `search`, `select`, `where`, and the other builder methods;
GET and POST query forms share the API's read permission. Actual requests still
receive server authorization and validation. Ordinary calls do not add hidden
preflight requests.

For operations outside the typed client, use server path templates and, when
needed, a restricted option name:

```ts
access.operation("PATCH /v1/notes/{id}");
access.operation("POST /v1/media", "path"); // separate local_files permission
```

Unreported options return `unknown`; discovery lists restricted options rather
than every accepted input. An unavailable parent operation always takes
precedence over an available option. The server's `setting` is preserved;
`permission` is populated only for a `permissions.*` setting.

Each `access()` call fetches a fresh, immutable snapshot. An old snapshot does
not refresh itself, and it cannot guarantee the next call will succeed.
Ordinary operations do no automatic permission preflight or permission retry.
Handle the actual HTTP error as well:

```ts
import { AuthenticationError, PermissionError } from "./dist/index.js";

try {
  await anki.notes.update(noteId, { addTags: ["checked"] });
} catch (error) {
  if (error instanceof AuthenticationError || error instanceof PermissionError) {
    showMessage(error.detail ?? error.message);
  } else {
    throw error;
  }
}
```

`AuthenticationError` is HTTP 401; `PermissionError` is HTTP 403. Both extend
`HttpError`, which exposes `status`, `body`, `detail`, `reason`, and `errors`
(unknown validation entries, when supplied). Default error messages do not
copy potentially private server text; apps explicitly choose when to show
`detail`. Per-item write failures still follow the note result contract.

`capabilities()` now returns a typed report with `caller`, `versions`,
`operations`, and `features`; raw access retains the whole response, including
stats. Discovery reports the current caller and effective operations, not a
directory of roles or a complete list of grants. Role changes happen in
Tsunagi's settings. The client does not invent a permission-request endpoint.
The compiled [permissions example](examples/permissions.ts) shows discovery
and request-time handling together.

## Implemented surface

- `cards` and `notes`: immutable `search`, `where`, `select`, `values`,
  `orderBy`, `distinctOn` queries; bounded `take`, `page`, and lazy `iterate`.
- `notes.create`, `createMany`, and `update`.
- `collection.sync`, which waits for completion, and `startSync`, which returns
  a handle for a progress screen or resumable observation.
- `access` with role/operation checks, typed `capabilities`, and `health`/raw
  JSON requests with unknown result types.
- Header authentication, request timeouts, cancellation, automatically generated
  write keys, and errors that distinguish partial or uncertain writes.

The typed resource fields and supported sorts are deliberately a subset. Default
card queries select `id`, `note_id`, `deck_id`, `interval`, and `due`; default note
queries select `id`, `model_name`, `first_field`, and `tags`. Expensive rendered
fields such as `question` are requested explicitly through `select`.

## Reading without cursor bookkeeping

```ts
const due = anki.cards.search("is:due").select("id", "note_id");

const first = await due.page(); // 50 rows by default
const second = await first.next(); // page or null

for await (const card of due.iterate({ size: 100, signal })) {
  useCard(card);
  // Breaking the loop stops fetching; there is no page prefetch.
}

const ids: number[] = await anki.cards.values("id").take(20);
```

`take(20)` executes one query with `limit=20` and returns its items array.
`take(0)` returns an empty array without contacting Anki. `page` and `iterate`
require positive sizes. A page's `next(options)` retains its query, size, and
cursor; pass a signal again if needed. Iterators preserve their signal across
pages. Collection changes can affect pagination; this is not a snapshot.

Filters use `eq`, `ne`, numeric `gt/gte/lt/lte`, and string `contains`.
String values are quoted/escaped for the API. Multiple `where` calls mean AND;
`search`, `orderBy`, and `select` replace their previous setting. Queries can be
reused without mutations leaking between views. `distinctOn` checks the current
server restriction to column fields/filters. Long queries automatically switch
to the equivalent POST query endpoint.

## Creating and editing notes

```ts
const note = await anki.notes.create({
  deck: "Japanese", // or { id: deckId }
  noteType: "Basic", // or { id: modelId }
  fields: { Front: "食べる", Back: "to eat" },
  tags: ["verbs"],
});

await anki.notes.update(note.id, {
  fields: { Back: "to eat; to consume" },
  addTags: ["updated"],
});
```

`create()` returns `{ id }` without re-fetching the note. An item failure inside
an HTTP success rejects with `ItemRejectedError`, including server details.
`update()` resolves to `void` when PATCH finishes, and also avoids an extra read.
Omitted patch properties are omitted on the wire; empty strings clear field
contents. This subset does not expose nullable patch properties or attachments.

`createMany()` returns receipts in input order only if all succeed. Otherwise
`PartialWriteError.report` preserves all known outcomes, including successful
writes. It does not imply rollback. To inspect per-item outcomes explicitly:

```ts
const report = await anki.notes.createMany(inputs, { onError: "collect" });
for (const item of report.items) {
  if (item.ok) useCreatedId(item.value.id);
  else showFailure(item.index, item.error.code, item.error.message);
}
```

Do not repeat a partially successful batch as a new write. This draft does not
automatically chunk writes or change their undo grouping.

## Sync and cancellation

```ts
const result = await anki.collection.sync({
  signal,
  timeoutMs: 30_000,     // initial request timeout
  waitTimeoutMs: 120_000, // subsequent job-wait deadline
});

const operation = await anki.collection.startSync();
console.log(operation.id, operation.abortable); // sync is not abortable
const sameResultShape = await operation.wait({ signal });
```

Fast and queued syncs return `{ status, server_message }`. Polling uses bounded
backoff and never re-submits the sync. `JobWaitTimeoutError.operation` retains a
handle so waiting can resume. Holding a handle explicitly is useful if an app
wants to recover from a dropped polling connection or a user leaving a screen.
Cancellation of a wait stops observation, not the server job. Media completion
and asynchronous add-on work follow the server's contract.

Note creation, updates, and sync submissions get a random `Idempotency-Key`; callers can override
it with `idempotencyKey` for the same persisted operation. Independent calls get
different keys. The request body is serialized before any asynchronous
credential lookup. Replay identity includes the app, method, path, query and
body; retaining only the key is not sufficient.

The current server rules cover job submission too: a keyed retry can recover
the same accepted job. `sync()` and `startSync()` accept a saved
`idempotencyKey`. Once the job ID is known, waiting polls it without resubmitting.
A failed job can start again on a keyed retry, so a retry is a deliberate
decision; the client never turns an observed job failure into another submission.

**There are no automatic retries in this draft.** A lost, cancelled, malformed,
or 5xx write response raises `WriteOutcomeUnknownError`, preserving the
underlying cause and the key when one was sent. Its `idempotencyKey` is
`undefined` for an unkeyed raw submission. A 503 does not cancel a write.
The current server rules cover all writes, including jobs, but do not promise
durable replay across server restarts. Automatic recovery and durable
request storage remain unimplemented.

HTTP errors retain status and body; server detail is not interpolated into
default messages because it can contain private note data. A 409 stays a general
conflict; the client does not infer its cause by matching English text.

## Where API rule changes land

The owner's local [API design rules](../../docs/api_design.md) guide this draft;
that document is intentionally outside git. The client simplifies calls while
preserving those rules:

| Rule | Client consequence |
| --- | --- |
| One shared query contract | The same builder vocabulary across resources; GET and POST query forms remain equivalent. |
| Anki owns search | Pass `search` through; encode `where` values with JSON. No client-side name lookups or search emulation. |
| Extras use `include` | Add totals and write extras through the same mechanism. Do not count or fetch related objects by default. |
| One request is one undo step | Keep a batch in one request; no automatic splitting or hidden follow-up writes. |
| Explicit changes and conflicts | Preserve omitted fields; allow null only where the schema permits it. Surface conflicts and actual stored filenames. |
| Replay follows the current server contract | Generate keys for note writes and sync submissions; poll jobs and never automatically resubmit them. |
| Errors have a shared shape | Preserve status and body; expose `detail`, `reason` and validation `errors`, with distinct HTTP 401/403 classes. |
| No collection cache between requests yet | Each query executes afresh; watch/caching work must respect the R18 freshness decision. |

The current builder is a subset: `include`, totals (including `limit=0` with
`include=total`), prefix/suffix and membership filters, and the complete sort
metadata still need typed support. Use raw requests for those today. A future
total must be absent when unrequested, rather than fabricated as null or zero.
Capabilities can be queried without additional operation permissions; the
client must not turn discovery into a gate before every request.

| File | Responsibility |
| --- | --- |
| `src/protocol.ts` | Paths, request names, filter syntax, query encoding, response decoders, current field/sort metadata |
| `src/types.ts` | Small public input/result types; intentionally provisional |
| `src/query.ts` | Lazy, immutable query behavior; selection inference; pagination |
| `src/client.ts` | Helpful note results, batch policies, sync waiting |
| `src/access.ts` | Caller identity and effective operation checks from explicit discovery snapshots |
| `src/access-target.ts` | Internal identity metadata linking queries and method references to their client and operation |
| `src/transport.ts` | Fetch, headers, deadlines, frozen write bodies |
| `test/client.test.mjs` | Explicit wire examples and behavior tests |
| `test/types.ts` | Compile-time usability checks |

The client does not change server routes, the server's OpenAPI snapshot, or the
in-progress API rules. For now the small supported contract is handwritten and
checked at the response boundary. Generate wire types from a reviewed schema
once that reduces work rather than causing churn. Keep behavioral tests when
wire names change; update explicit contract expectations alongside the adapter.

`anki.raw.request(method, path, options)` provides an escape hatch for GET/POST/
PATCH/DELETE JSON endpoints and returns `{ status, headers, data, idempotencyKey }`.
`data` is unknown until checked. Paths stay under the configured `/v1/` prefix,
redirects are refused, and key lookup happens for each request. Raw access is
also provisional, and currently treats every non-GET request as a write for
uncertain-completion reporting. It generates no idempotency key: a raw caller
may pass an explicit key after verifying that route's replay coverage. Sending
a key does not establish that the route supports replay.

## Still proposed, not implemented

Watch/reconnect helpers, raw SSE, attachments, upsert, more resource wrappers,
typed provider actions, field bindings, generated schema coverage, automatic
read retries, replay/recovery handles, profile/session binding, browser runtime
tests, and live-Anki smoke tests. In particular, the draft cannot ensure that a
multi-request workflow stays on the same profile if Anki switches profiles.

`anki.watchAccess({ signal })` keeps access current. It watches
`GET /v1/events?types=access.changed` (open to any accepted app) and fetches
the capabilities report after each connection and each `access.changed` or
`gap`; notifications during a fetch collapse into one more fetch. It yields
`loading`, `refreshing`, `ready` (with an `AccessSnapshot`) and `reconnecting`
states, latest first for a slow loop; reconnects with backoff after a drop,
three missed heartbeats or `close`; and ends on abort, or with
`AuthenticationError` when the key is refused.

```ts
for await (const state of anki.watchAccess({ signal })) {
  if (state.status === "ready") render(state.access);
  else if (state.status === "reconnecting") showOffline(state.access); // last known, or null
}
```

It opens its own stream; when data watching lands, the two should share one.

This package is for reviewing and revising the client experience, not publishing a
stable SDK while the HTTP API rules are still being decided.
