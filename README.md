<h1 align="center">Tsunagi</h1>
<p align="center"><strong>Connect apps to Anki.</strong></p>
<p align="center">
  <a href="#install">Install</a> ·
  <a href="#replace-ankiconnect">Switch from AnkiConnect</a> ·
  <a href="docs/getting_started.md">Build an integration</a> ·
  <a href="https://mcgrizzz.github.io/Tsunagi/">API reference</a> ·
  <a href="docs/README.md">Documentation</a>
</p>

Tsunagi (繋ぎ, “connection”) is an Anki desktop add-on that can take over from
AnkiConnect while giving new integrations a richer HTTP API.

### Already use AnkiConnect?

Install Tsunagi and let it take over AnkiConnect's port, key and allowed
websites. Yomitan, asbplayer and your other AnkiConnect tools generally keep
working without changes.

**[Switch from AnkiConnect →](#replace-ankiconnect)**

### Building an Anki integration?

Ask for the data you need instead of chaining narrow actions. Live change
events, undoable writes, per-app permissions, FSRS tools and a typed
TypeScript client come with it.

**[Build your first integration →](docs/getting_started.md)** ·
**[Browse the API reference](https://mcgrizzz.github.io/Tsunagi/)**

> [!NOTE]
> Experimental. Supports **Anki 26.08 and 26.09** (the current desktop release
> and the one before it); some features depend on your settings.

## Install

1. In Anki desktop, open **Tools → Add-ons → Get Add-ons**.
2. Paste the code **`666370974`** and click **OK**
   ([AnkiWeb listing](https://ankiweb.net/shared/info/666370974)).
3. Restart Anki.

Or download the `.ankiaddon` file from
[GitHub Releases](https://github.com/mcgrizzz/Tsunagi/releases) and use
**Tools → Add-ons → Install from file**, then restart Anki.

## Quick start

### Replace AnkiConnect

1. Install Tsunagi and restart Anki.
2. Review the AnkiConnect settings it offers to take over, and click **Take over**.
3. Use your tools as before. Tools that were already open may need to reconnect.

Missed the offer? Open **Tools → Tsunagi Settings → Server → Take over from
AnkiConnect…**

### Connect a tool without AnkiConnect

1. Check that the server is on in **Tools → Tsunagi Settings → Server**.
2. Set the tool's AnkiConnect address to **`http://127.0.0.1:7777`**.
3. Use the tool; **Recent requests** shows its requests.

Keep Anki open with a profile loaded. Programs on this computer need no key
by default ([app keys](config.md#apps--keys)).

### Build an integration

```sh
curl http://127.0.0.1:7777/v1/health
```

Browse the [API reference](https://mcgrizzz.github.io/Tsunagi/), or open
<http://127.0.0.1:7777/> while Anki runs to send real requests.

**[Build your first integration →](docs/getting_started.md)**

## What you gain with existing tools

- **Compatibility you can check.** All 122 AnkiConnect actions, with the known
  differences listed in the [compatibility notes](docs/ankiconnect_parity.md).
- **A key and a role for each tool.** Limit a tool to reading, adding notes,
  opening Anki's windows or more ([roles](config.md#roles)).
- **A log of every request.** See which tool asked for what, and why a request
  was refused.
- **Undo.** **Edit → Undo** reverts most changes your tools make.

![Recent requests in Tsunagi's settings: Yomitan and asbplayer's AnkiConnect requests, and two refused requests with the reason](docs/images/settings-requests.png)

## What the Tsunagi API adds

**Take a note-type picker.** With AnkiConnect, fetch `modelNames`, then call
`modelFieldNames` for each type you need. With Tsunagi, ask for both together:

```sh
curl --get 'http://127.0.0.1:7777/v1/note-types' \
  --data-urlencode 'select=id,name,fields[].name'
```

Each note type comes back with its ID, name and field names. Notes, cards,
reviews and decks are queried the same way.

Fewer requests add up: in one measured Yomitan workflow, mining ten words, the
Tsunagi API made 40 requests in 326 ms where AnkiConnect made 80 in 2,875 ms
([benchmarks](docs/benchmarks.md)).

| | |
| --- | --- |
| **Undoable writes** | **Edit → Undo** reverts most API changes. |
| **Safe retries** | A write retried with the same `Idempotency-Key` happens once. |
| **Live changes** | An [event stream](docs/events.md) of what changed in the collection. |
| **A key per app** | Separate credentials and permissions for each integration. |
| **FSRS** | Compute and evaluate parameters, and simulate study workload. |
| **OpenAPI** | Browse every operation in the [API reference](https://mcgrizzz.github.io/Tsunagi/). |

**[Build your first integration →](docs/getting_started.md)** ·
[Yomitan case study](docs/api_recipes.md): a real AnkiConnect integration,
request by request, on the Tsunagi API.

### TypeScript client

Field names and values checked as you type, and queries that stay current as
Anki changes. Install it with `npm install tsunagi-client`
([npm](https://www.npmjs.com/package/tsunagi-client)).

```ts
const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:7777" });

// Anki's states by name, checked as you type: is("suspended"), is("due")...
const suspended = await anki.cards.search("deck:Mining").is("suspended").count();

// Keep a list of the deck's notes current as Anki changes, whoever changes it.
await anki.notes.search("deck:Mining").select("id", "firstField").watch({
  added: notes => show(notes),
  updated: notes => show(notes),
  removed: ids => hide(ids),
});
```

**[Client guide →](packages/typescript/README.md)**

## Built to be checked

- **Compatibility:** every AnkiConnect action listed and checked in CI
  ([compatibility notes](docs/ankiconnect_parity.md)).
- **Benchmarks:** real clients' requests on Anki desktop, slower cases included
  ([benchmarks](docs/benchmarks.md)).
- **Security:** only your computer by default, websites refused unless allowed,
  a role per app ([security model](docs/security.md)).
- **Tests:** both supported Anki versions on every push, plus checks in a real
  (offscreen) Anki.
- **Releases:** notes for each one
  ([GitHub Releases](https://github.com/mcgrizzz/Tsunagi/releases)).

## Help

Everything is in **Tools → Tsunagi Settings**; the
[settings reference](config.md) describes each page. If a tool can't connect,
check that Anki is open and the tool uses the same port and key: **Recent
requests** shows whether its requests arrive and why any were refused.

For other problems, [open an issue](https://github.com/mcgrizzz/Tsunagi/issues)
with your Anki version, operating system, the tool or request involved, and
Tsunagi's log file from Anki's `logs/addons/` folder. Remove API keys and
private note content first.

## Learn more

| Using AnkiConnect tools | Building an integration |
| --- | --- |
| [Compatibility notes](docs/ankiconnect_parity.md) | [Build your first integration](docs/getting_started.md) |
| [Settings reference](config.md) | [API reference](https://mcgrizzz.github.io/Tsunagi/) ([in Anki](docs/playground.md)) |
| [Security model](docs/security.md) | [Creating notes](docs/creating_notes.md) · [Events](docs/events.md) |
| [Benchmarks](docs/benchmarks.md) | [Yomitan case study](docs/api_recipes.md) · [TypeScript client](packages/typescript/README.md) |

[All documentation](docs/README.md) · [Working on Tsunagi](docs/development.md)
