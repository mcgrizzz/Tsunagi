<h1 align="center">Tsunagi</h1>
<p align="center"><strong>An AnkiConnect-compatible bridge for the tools you already use,<br>
and a modern API for building new Anki integrations.</strong></p>
<p align="center">
  <a href="#install">Install</a> ·
  <a href="#replace-ankiconnect">Switch from AnkiConnect</a> ·
  <a href="docs/getting_started.md">Build an integration</a> ·
  <a href="https://mcgrizzz.github.io/Tsunagi/">API reference</a> ·
  <a href="docs/README.md">Documentation</a>
</p>

Tsunagi (繋ぎ, “connection”) is an Anki desktop add-on. It makes your
collection available over HTTP on your computer, to dictionary tools, mining
apps and scripts.

> [!NOTE]
> Experimental. Supports **Anki 26.08 and 26.09** (the current desktop release
> and the one before it); some features depend on your settings. Older Anki
> keeps the last Tsunagi version that supported it.

### Already use AnkiConnect?

Install Tsunagi and let it take over: it copies AnkiConnect's port, key and
allowed websites, then turns AnkiConnect off. Yomitan, asbplayer and your other
AnkiConnect tools keep the same connection, and generally need no changes.
You also get a key and limits for each tool, a log of what each one asked for,
and **Edit → Undo** for their changes.

**[Switch from AnkiConnect →](#replace-ankiconnect)**

### Building an Anki integration?

The Tsunagi API lets you ask for what you need instead of chaining narrow
actions: notes with only the fields you show, note types with their fields,
each card's latest review, in one request each. Writes can be undone in Anki
and retried safely, change events keep your app current, and it comes with
FSRS tools, a key and permissions for each app, an OpenAPI description and a
typed TypeScript client.

**[Build your first integration →](docs/getting_started.md)** ·
**[Browse the API reference](https://mcgrizzz.github.io/Tsunagi/)**

## Install

1. In Anki desktop, open **Tools → Add-ons → Get Add-ons**.
2. Paste the code **`666370974`** and click **OK**
   ([AnkiWeb listing](https://ankiweb.net/shared/info/666370974)).
3. Restart Anki.

Or download the `.ankiaddon` file from
[GitHub Releases](https://github.com/mcgrizzz/Tsunagi/releases) and use
**Tools → Add-ons → Install from file**, then restart Anki. Each release has
notes on what changed.

## Quick start

### Replace AnkiConnect

When AnkiConnect is installed, Tsunagi's first start opens its settings with
an offer to take over.

1. Check what it lists: the port, the key and the websites it adds. Click
   **Take over**. Anki doesn't need another restart.
2. Use your tools as before. They reach Tsunagi at AnkiConnect's address with
   the same key. A tool that was already open may need to reconnect.

Closed the offer? Open **Tools → Tsunagi Settings** and click **Take over from
AnkiConnect…** on the **Server** page. The
[compatibility notes](docs/ankiconnect_parity.md) list the few things that
work differently.

### Connect a tool without AnkiConnect

1. Open **Tools → Tsunagi Settings**. On **Server**, check that **Run the
   Tsunagi server** is ticked; the default port is 7777.
2. In your tool, set the AnkiConnect address to **`http://127.0.0.1:7777`**
   (or the port to **`7777`**).
3. Use the tool once and open **Recent requests**: its requests are listed,
   and a refused one says why.

**Keep Anki open with your profile loaded.** Programs on this computer need no
key. To limit what a tool can do, give it its own key under **Apps & keys**.

### Build an integration

With Anki open:

```sh
curl http://127.0.0.1:7777/v1/health
```

Then open **<http://127.0.0.1:7777/>**: the interactive API reference, where
you can send real requests. [Build your first integration](docs/getting_started.md)
takes you through a query, a note added and undone, and an app key.

## For the tools you already use

- **They keep working.** Tsunagi implements all 122 AnkiConnect actions
  (AnkiConnect's source as of 2025-12-03), and CI checks the list against the
  actions Tsunagi answers. A complete list isn't proof that every edge case
  matches: the
  [compatibility notes](docs/ankiconnect_parity.md) list the known differences,
  such as reading files on your computer needing a permission.
- **You decide what each tool may do.** Give a tool its own key and a role:
  read only, add notes, open Anki's windows, and more. A tool without a key
  gets the Default role: what AnkiConnect allows, except reading files on your
  computer.
- **You can see what they do.** **Recent requests** lists each tool's
  requests, the AnkiConnect action, the website it came from, and why anything
  was refused.
- **Undo works.** Note edits, card suspension and other changes go through
  Anki's own operations, so **Edit → Undo** reverts them and Anki's windows
  update.
- **Often faster, with the same requests.** Replaying ten goals from real
  AnkiConnect clients on Anki desktop, Tsunagi answered the same requests
  faster than AnkiConnect for seven and slower for two
  ([benchmarks](docs/benchmarks.md#real-client-workloads)).

![Recent requests in Tsunagi's settings: Yomitan and asbplayer's AnkiConnect requests, and two refused requests with the reason](docs/images/settings-requests.png)

## What the Tsunagi API adds

**Take a note-type picker.** With AnkiConnect, fetch `modelNames`, then call
`modelFieldNames` for each type you need. With Tsunagi, ask for both together:

```sh
curl --get 'http://127.0.0.1:7777/v1/models' \
  --data-urlencode 'select=id,name,fields[].name'
```

Each note type comes back with its ID, name and field names, and nothing else.
`select`, `where` and `order` work the same on every list, and notes, cards
and reviews also take Anki's search syntax.

Fewer requests add up. Mining ten words in Yomitan, measured on Anki desktop,
took 40 requests and 326 ms through the Tsunagi API against 80 requests and
2,875 ms through AnkiConnect. It isn't faster everywhere: two large reads of
review history were slower
([benchmarks](docs/benchmarks.md)).

| | |
| --- | --- |
| **Undoable writes** | Most API changes are Anki operations: **Edit → Undo** reverts them, or `POST /v1/gui:undo`. |
| **Safe retries** | Send an `Idempotency-Key` with a write, and a retry after a timeout returns the first result instead of writing twice. |
| **Safer note creation** | Check for duplicates and get their IDs, add to the note you already have, and get the new cards' IDs with the note. [Creating notes](docs/creating_notes.md) |
| **Live changes** | An event stream says which notes, cards and decks changed, as they change. [Events](docs/events.md) |
| **FSRS** | Compute and evaluate FSRS parameters, and simulate study workload. |
| **A key per app** | Each app gets its own key and role, and [one report](docs/capabilities.md) of what it may do. |
| **Standard HTTP** | Real status codes, an OpenAPI description and an [interactive reference](https://mcgrizzz.github.io/Tsunagi/). |

**[Build your first integration →](docs/getting_started.md)** ·
[Yomitan case study](docs/api_recipes.md): a real AnkiConnect integration,
request by request, and what the Tsunagi API changes.

### Build with the TypeScript client

[`packages/typescript`](packages/typescript) is a typed client for the Tsunagi
API. It isn't on npm yet; you build it from this repository. Your editor
checks field names and values as you type:

```ts
const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:7777" });

// Mine 食べる, or add the sentence to the note you already have for it.
await anki.notes.upsert({
  deck: "Mining", noteType: "Mining",
  fields: { Expression: "食べる", Sentence: "もう食べた。" },
  matchField: "Expression",
  fieldRules: { Sentence: "append", "*": "keep" },
});

// Named values, not Anki's codes: a suspended card's queue is "suspended", not -1.
const suspended = await anki.cards.search("deck:Mining").where("queue", "eq", "suspended").count();

// Keep a list of the deck's notes current as Anki changes, whoever changes it.
await anki.notes.search("deck:Mining").select("id", "firstField").watch({
  added: notes => show(notes),
  updated: notes => show(notes),
  removed: ids => hide(ids),
});
```

`watch` loads the list, then sends only the notes whose selected fields
changed. It reconnects and catches up by itself after Anki restarts or a
connection drops.

## Built to be checked

- **Compatibility** is a list of every AnkiConnect action, checked against the
  code in CI, with its [known differences](docs/ankiconnect_parity.md).
- **Benchmarks** replay real clients' requests on Anki desktop, and report
  where Tsunagi is slower too ([benchmarks](docs/benchmarks.md)).
- **Security** is written down: what's exposed, to whom, what stops it and the
  known gaps ([security model](docs/security.md)). By default Tsunagi listens
  only on your computer, and websites you haven't allowed are refused.
- **Tests** run on every push against both supported Anki versions, with
  checks in a real (offscreen) Anki; the TypeScript client is tested against
  the server.
- **Releases** come with notes on what changed
  ([GitHub Releases](https://github.com/mcgrizzz/Tsunagi/releases)).

## Settings and help

Open **Tools → Tsunagi Settings** to change:

| Page | Settings |
| --- | --- |
| **Server** | Server on/off, port, who can connect (host), limits, timeouts and logging. Taking over from AnkiConnect. |
| **Apps & keys** | Each tool's key and role, and a switch to turn it off. |
| **Requests without a key** | The role for keyless requests from this computer and from other devices. |
| **Websites & Anki pages** | Allowed website origins, and whether card templates and add-on pages may use the API. |
| **Add-ons** | Which actions other add-ons offer that apps may run. |
| **Roles** | What each role allows, and who uses it. |
| **Recent requests** | Requests since Anki started, per client (app, website or no key), with totals and filters, so you can see who is calling and what failed. Memory only; no keys or contents. |

If a tool can't connect, check that Anki is open and the tool uses the same port
and key. **Recent requests** shows whether its requests arrive and why any were
refused.

See the [configuration reference](config.md) for details. For unresolved problems,
[open an issue](https://github.com/mcgrizzz/Tsunagi/issues) with your Anki version,
operating system, the tool or request involved, and Tsunagi's log file from
Anki's `logs/addons/` folder. Remove API keys and private
note content from examples.

## Learn more

**Using AnkiConnect tools**

| I want to… | Start here |
| --- | --- |
| **Check a tool's actions** | [Compatibility notes](docs/ankiconnect_parity.md): every AnkiConnect action, and what works differently. |
| **Change a setting** | [Settings reference](config.md): every page of the settings window. |
| **Know what's protected** | [Security model](docs/security.md): who can reach Anki through Tsunagi, and what stops them. |

**Building an integration**

| I want to… | Start here |
| --- | --- |
| **Make my first requests** | [Build your first integration](docs/getting_started.md): health, a query, a note added and undone, an app key. |
| **Browse every operation** | The [API reference](https://mcgrizzz.github.io/Tsunagi/), or the [interactive one in Anki](docs/playground.md) that sends real requests. |
| **Create notes and media** | [Creating notes](docs/creating_notes.md): check, add, add to an existing note, upload media, retry safely. |
| **React to changes** | [Events](docs/events.md): a live stream of what changed in the collection. |
| **Check what my app may do** | [API discovery](docs/capabilities.md): one report of available, disabled and unsupported operations. |
| **See a real integration** | [Yomitan case study](docs/api_recipes.md): its AnkiConnect requests and what the Tsunagi API changes. |
| **Use TypeScript** | [Client README](packages/typescript/README.md): queries, writes, watching and access checks. |
| **Offer my add-on's actions** | [Add-on providers](docs/addon_providers.md): let apps run your add-on's actions through Tsunagi. |

**Working on Tsunagi:** the [development guide](docs/development.md) covers
building, testing and releases; [all documentation](docs/README.md).
