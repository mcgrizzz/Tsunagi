<h1 align="center">Tsunagi</h1>
<p align="center"><strong>Connect your Anki collection to the tools you use.</strong></p>
<p align="center">
  <a href="#why-use-tsunagi">Why Tsunagi?</a> ·
  <a href="#install">Install</a> ·
  <a href="#move-from-ankiconnect">Switch from AnkiConnect</a> ·
  <a href="docs/api_recipes.md">Yomitan walkthrough</a> ·
  <a href="docs/development.md">Development</a>
</p>

Tsunagi (繋ぎ, “connection”) is an Anki desktop add-on for dictionary tools,
flashcard mining apps and scripts. Use it with **existing AnkiConnect tools**, or
build apps with the **Tsunagi API** for collection queries, FSRS and change events.

> [!NOTE]
> Experimental. Supports **Anki 26.08 and 26.09** (the current desktop release
> and the one before it); some features depend on your settings. Older Anki
> keeps the last Tsunagi version that supported it.

## Why use Tsunagi?

[Don't care? Take me to setup.](#install)

### More of modern Anki

Tsunagi is a newer implementation built around modern Anki APIs. The Tsunagi API
goes beyond AnkiConnect's actions, including **access to Anki's FSRS tools**.

| Benefit | What you can do |
| --- | --- |
| **FSRS access** | Compute and evaluate FSRS parameters, and simulate study workload through the Tsunagi API. |
| **Undo in Anki** | Undo supported changes, such as note edits and card suspension, through the API or **Edit → Undo** (**Ctrl+Z** / **⌘Z**). Tsunagi uses Anki's collection operations so its windows update too. |
| **Live change events** | React when notes or cards are created, updated or deleted, with affected IDs where available. See the [event guide](docs/events.md) for coverage. |
| **Safer note creation** | Check for duplicates first, add to a note you already have instead of creating a second one, and retry after a timeout without saving twice. See [Creating notes](docs/creating_notes.md). |
| **Control what each app can do** | Give each tool its own key and decide what it may do: only read, add notes, open Anki's windows, and more. Turn a tool off without deleting it. |
| **Standard HTTP tooling** | Connect through FastAPI and Uvicorn, with validated requests, native HTTP status codes and an OpenAPI schema. Try Tsunagi API requests in the interactive reference. |

Feature availability depends on your Anki version and settings. The
[discovery endpoint](docs/capabilities.md) reports what's available, disabled or
unsupported in one place.

### Keep using your tools

The AnkiConnect Shim lets existing integrations connect to Tsunagi.
[Import your connection settings](#move-from-ankiconnect) to keep the same address.
AnkiConnect Shim requests use Tsunagi's internal routing and shared Anki adapters,
so **existing tools may also see performance benefits**, depending on the requests
and your collection ([measurements](docs/benchmarks.md#real-client-workloads)).
See the [compatibility notes](docs/ankiconnect_parity.md).

FSRS tools, queries and events are available through the Tsunagi API. An existing
AnkiConnect client keeps its current workflow until it adopts those endpoints.

### Get related data in one request

Tsunagi grew out of building [Yomine](https://github.com/mcgrizzz/Yomine), where
getting related Anki data often meant several requests and joining the results.

**Take a note-type picker.** With AnkiConnect, fetch `modelNames`, then call
`modelFieldNames` for each type you need. With Tsunagi, ask for both together:

```sh
curl --get 'http://127.0.0.1:7777/v1/models' \
  --data-urlencode 'select=id,name,fields[].name' \
  --data-urlencode 'limit=10'
```

Each model comes back with its ID, name and fields. **No follow-up field request
for those models.** Anki already stores the fields in the model record; Tsunagi
reuses that data. Asking only for `id,name` takes Anki's lightweight name/ID lookup
instead, without loading full model definitions.

`limit=10` sets the page size; follow `next_cursor` for more. Notes, cards and
reviews also accept Anki browser search syntax to narrow your results.

**[See the full workflow → Yomitan walkthrough](docs/api_recipes.md)**

## Install

**AnkiWeb add-on code:** `666370974`

1. In Anki desktop, open **Tools → Add-ons → Get Add-ons**.
2. Paste the code above and click **OK**.
3. Restart Anki, then follow [Quick start](#quick-start).

**Install from a file:** download the `.ankiaddon` file from
[GitHub Releases](https://github.com/mcgrizzz/Tsunagi/releases) and use
**Tools → Add-ons → Install from file**, then restart Anki.

## Quick start

> [!TIP]
> Already using AnkiConnect? Use [Move from AnkiConnect](#move-from-ankiconnect)
> to bring over your connection settings.

1. Open **Tools → Tsunagi Settings**.
2. On **Server**, check that **Run the Tsunagi server** is ticked, and keep the
   default host and port.
3. Open **<http://127.0.0.1:7777/>**. The interactive API reference confirms that
   Tsunagi is reachable.
4. In your tool, set the Anki connection address to **`http://127.0.0.1:7777`**.
   If it asks for a port separately, enter **`7777`**.

**Keep Anki open with your profile loaded.** Programs on this computer need no
key. To limit what a tool can do, give it its own key under **Apps & keys**. If
you change the port, use the same port in your tool.

## Move from AnkiConnect

The first time Tsunagi starts with AnkiConnect installed, it offers to take
over. **Take over** copies AnkiConnect's port and API key, **adds its allowed
websites to your list**, turns AnkiConnect off and runs Tsunagi in its place.
Your tools keep using the same address and key.

To do it later, open **Tools → Tsunagi Settings** and click **Take over from
AnkiConnect…** on the **Server** page.

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

| I want to… | Start here |
| --- | --- |
| **Build something with Tsunagi** | [Yomitan walkthrough](docs/api_recipes.md): its AnkiConnect requests and their Tsunagi API equivalents. |
| **Browse every operation** | Open the [interactive reference](http://127.0.0.1:7777/) while Anki is running. [How to use it](docs/playground.md). |
| **Check feature availability** | [API discovery](docs/capabilities.md): one report of available, disabled and unsupported operations. |
| **Create notes and media** | [Creating notes](docs/creating_notes.md): check, add, add to an existing note, upload media, retry safely. |
| **React to changes** | [Events](docs/events.md): a live stream of what changed in the collection. |
| **Use an AnkiConnect client** | [Compatibility notes](docs/ankiconnect_parity.md). |
| **Know what's protected** | [Security model](docs/security.md). |
| **Offer my add-on's actions** | [Add-on providers](docs/addon_providers.md): let apps run your add-on's actions through Tsunagi. |
| **Work on the add-on** | [Development guide](docs/development.md): build, test, sync and package releases. |
