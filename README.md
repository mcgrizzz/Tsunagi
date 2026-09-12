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
flashcard mining apps and scripts. Connect existing **AnkiConnect integrations**,
or build with a **native API** that lets you choose, filter and page through Anki data.

> [!NOTE]
> Experimental. Supports **Anki desktop 23.10 and newer**; some features depend on
> your Anki version and settings.

## Why use Tsunagi?

[Don't care? Take me to setup.](#install)

### Keep using your tools

The AnkiConnect compatibility API lets you keep existing integrations. Import
AnkiConnect's connection settings to switch over without changing each tool's
address. See the [compatibility notes](docs/ankiconnect_parity.md) for coverage
and known differences.

Compatibility requests also use Tsunagi's internal routing and shared Anki
adapters, so **existing tools may see performance benefits**. Any speedup depends
on the requests and your collection.

### Build with fewer steps

Tsunagi grew out of work on [Yomine](https://github.com/mcgrizzz/Yomine), where apps
needed related Anki data together. For example, a note-type picker needs both type
names and their fields. Tsunagi can return those in one query.

| With the native API, you can… | For example… |
| --- | --- |
| **Choose the data you receive** | Get note-type names and fields together, leaving out templates and other details. |
| **Search and page through results** | Find notes with Anki browser syntax and load a large result set a page at a time. |
| **Follow collection activity** | Refresh your app when events arrive, instead of repeatedly checking for changes. |
| **Try requests before coding** | Explore your collection through the interactive API reference. |

**[See it in practice → Yomitan walkthrough](docs/api_recipes.md)**

Apps need to use the native API to gain these features. Existing AnkiConnect
clients keep their current workflow; both APIs can be used together.

## Install

**AnkiWeb add-on code:** `666370974`

1. In Anki desktop, open **Tools → Add-ons → Get Add-ons**.
2. Paste the code above and click **OK**.
3. Restart Anki, then follow the quick start below.

You can also download the `.ankiaddon` file from
[GitHub Releases](https://github.com/mcgrizzz/Tsunagi/releases) and use
**Tools → Add-ons → Install from file**. To build it yourself, see the
[development guide](docs/development.md#environment-and-build).

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

Existing integrations don't require you to write requests. If you're building
something, start with the [Yomitan walkthrough](docs/api_recipes.md).

## Move from AnkiConnect

1. Open **Tools → Tsunagi Settings → Connection**.
2. Click **Import AnkiConnect settings**.
3. Review the values under **Ready to import**, then click **Save**.

The importer copies the port and any configured API key, and **adds website origins
to your existing list**. On Save, it disables AnkiConnect and stops its server before
Tsunagi takes over the port. **Cancel** leaves your setup unchanged.

After saving, **Last import** shows when settings were copied. Your tools can keep
using the imported address; if you change the port or key, update them too.

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
