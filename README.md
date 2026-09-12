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
build apps with a **native API** for collection queries, FSRS and change events.

> [!NOTE]
> Experimental. Supports **Anki desktop 23.10 and newer**; some features depend on
> your Anki version and settings.

## Why use Tsunagi?

[Don't care? Take me to setup.](#install)

### More of modern Anki

Tsunagi is a newer implementation built around modern Anki APIs. Its native API
goes beyond AnkiConnect's actions, including **access to Anki's FSRS tools**.

| Benefit | What you can do |
| --- | --- |
| **FSRS access** | Compute and evaluate FSRS parameters, and simulate study workload through the native API. |
| **Undo in Anki** | Undo supported changes, such as note edits and card suspension, through the API or **Edit → Undo** (**Ctrl+Z** / **⌘Z**). Tsunagi uses Anki's collection operations so its windows update too. |
| **Live change events** | Let your app refresh when collection changes arrive, with known IDs where available. See the [event guide](docs/events.md) for coverage. |
| **Standard HTTP tooling** | Connect through FastAPI and Uvicorn, with validated requests, native HTTP status codes and an OpenAPI schema. Try native requests in the interactive reference. |

Feature availability depends on your Anki version and settings. The
[discovery endpoint](docs/capabilities.md) reports what's available, disabled or
unsupported in one place.

### Keep using your tools

The AnkiConnect compatibility API lets existing integrations connect to Tsunagi.
[Import your connection settings](#move-from-ankiconnect) to keep the same address.
Compatibility requests use Tsunagi's internal routing and shared Anki adapters,
so **existing tools may also see performance benefits**, depending on the requests
and your collection. See the [compatibility notes](docs/ankiconnect_parity.md).

FSRS tools, queries and events are available through the native API. An existing
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
2. On **Connection**, leave **Enable Tsunagi server** checked and keep the default
   host and preferred port. Click **Save**.
3. Open **<http://127.0.0.1:7777/>**. The interactive API reference confirms that
   Tsunagi is reachable.
4. In your tool, set the Anki connection address to **`http://127.0.0.1:7777`**.
   If it asks for a port separately, enter **`7777`**.

**Keep Anki open with your profile loaded.** If you change the port or set an
API key under **Access**, use the same values in your tool.

## Move from AnkiConnect

1. Open **Tools → Tsunagi Settings → Connection**.
2. Click **Import AnkiConnect settings**.
3. Review the values under **Ready to import**, then click **Save**.

The importer copies the port and API key, and **adds allowed websites to your
existing list**. Saving disables AnkiConnect and stops its server before Tsunagi
takes over the port. Your tools can keep using the imported address and key.

## Settings and help

Open **Tools → Tsunagi Settings** to change:

| Tab | Settings |
| --- | --- |
| **Connection** | Server, address, port and AnkiConnect import. |
| **Access** | API key, allowed websites and optional permissions. |
| **Advanced** | Media limits, timeouts and logging. |

If a tool can't connect, check that Anki is open and both use the same port and
API key. For a website access error, add its origin under **Access**, including
`http://` or `https://` and any port, without a page path.

See the [configuration reference](config.md) for details. For unresolved problems,
[open an issue](https://github.com/mcgrizzz/Tsunagi/issues) with your Anki version,
operating system and the tool or request involved. Remove API keys and private
note content from examples.

## Learn more

| I want to… | Start here |
| --- | --- |
| **Build something with Tsunagi** | [Yomitan walkthrough](docs/api_recipes.md): its AnkiConnect requests and their native equivalents. |
| **Browse every operation** | Open the [interactive reference](http://127.0.0.1:7777/) while Anki is running. [How to use it](docs/playground.md). |
| **Check feature availability** | [Native discovery](docs/capabilities.md): one report of available, disabled and unsupported operations. |
| **Use an AnkiConnect client** | [Compatibility notes](docs/ankiconnect_parity.md). |
| **Work on the add-on** | [Development guide](docs/development.md): build, test, sync and package releases. |
