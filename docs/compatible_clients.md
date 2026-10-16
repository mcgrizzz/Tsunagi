# Tested AnkiConnect tools

These tools were checked request by request against Tsunagi. For each one,
we read its source at the commit shown and listed the requests it sends to
Anki. On every change, Tsunagi's tests check that each of those requests gets
the answer AnkiConnect gave before its October 2026 rewrite (`de6e6e1`, the
last version before it), including for cards that are new, learning, in
review, relearning, suspended, buried or in a filtered deck.

The tools' own code isn't run, so what a tool does with Anki's windows, such
as opening the Browser, isn't covered.

| Tool | What it is | Checked | Requests checked | Notes |
| --- | --- | --- | --- | --- |
| [anki-mcp-server](https://github.com/ankimcp/anki-mcp-server) | Gives AI assistants tools to read and edit Anki (MCP) | [`e0e347f`](https://github.com/ankimcp/anki-mcp-server/tree/e0e347f), 2026-10-15 | 49 |  |
| [asbplayer](https://github.com/asbplayer/asbplayer) | Subtitle player; mines sentence cards | [`62c4d6e`](https://github.com/asbplayer/asbplayer/tree/62c4d6e), 2026-10-15 | 20 |  |
| [Game Sentence Miner](https://github.com/bpwhelan/GameSentenceMiner) | Adds audio, screenshots and sentences to mined notes | [`c3499a0`](https://github.com/bpwhelan/GameSentenceMiner/tree/c3499a0), 2026-10-15 | 15 | Needs Tsunagi 0.7.5 or newer for media files named with a folder |
| [Jiten](https://github.com/Sirush/Jiten) | Imports known words and review history (jiten.moe) | [`fe383fc`](https://github.com/Sirush/Jiten/tree/fe383fc), 2026-10-15 | 9 |  |
| [JL](https://github.com/rampaa/JL) | Pop-up dictionary for Windows; mines words | [`8995ac5`](https://github.com/rampaa/JL/tree/8995ac5), 2026-10-15 | 9 |  |
| [logseq-anki-sync](https://github.com/debanjandhar12/logseq-anki-sync) | Syncs Logseq blocks to Anki notes | [`0d881e3`](https://github.com/debanjandhar12/logseq-anki-sync/tree/0d881e3), 2026-10-15 | 34 |  |
| [LunaTranslator](https://github.com/HIllya51/LunaTranslator) | Visual novel translator; adds looked-up words | [`0ee08c6`](https://github.com/HIllya51/LunaTranslator/tree/0ee08c6), 2026-10-15 | 8 | Needs Tsunagi 0.7.5 or newer for all of its requests (it sends them as GET) |
| [Memento](https://github.com/ripose-jp/Memento) | Video player for learning Japanese; mines words | [`e45a792`](https://github.com/ripose-jp/Memento/tree/e45a792), 2026-10-15 | 12 |  |
| [mokuro-reader](https://github.com/Gnathonic/mokuro-reader) | Manga reader; makes cards from page crops | [`bfaeb48`](https://github.com/Gnathonic/mokuro-reader/tree/bfaeb48), 2026-10-15 | 14 |  |
| [Obsidian_to_Anki](https://github.com/ObsidianToAnki/Obsidian_to_Anki) | Syncs Obsidian notes to Anki (plugin and script) | [`feb3db2`](https://github.com/ObsidianToAnki/Obsidian_to_Anki/tree/feb3db2), 2026-10-15 | 34 |  |
| [Saladict](https://github.com/crimx/ext-saladict) | Pop-up dictionary extension; syncs its notebook | [`7d93a65`](https://github.com/crimx/ext-saladict/tree/7d93a65), 2026-10-15 | 10 |  |
| [simple-anki-sync](https://github.com/russluber/simple-anki-sync) | Syncs Markdown tables in Obsidian to Anki | [`36ddadd`](https://github.com/russluber/simple-anki-sync/tree/36ddadd), 2026-10-15 | 13 |  |
| [Tabbi](https://github.com/ethanwchen/tabbi) | macOS notch app showing due counts and streaks | [`60fef5f`](https://github.com/ethanwchen/tabbi/tree/60fef5f), 2026-10-15 | 8 |  |
| [Yanki](https://github.com/kitschpatrol/yanki) | Syncs Markdown to Anki (command line and Obsidian) | [`60603b4`](https://github.com/kitschpatrol/yanki/tree/60603b4), 2026-10-15 | 21 | Needs Tsunagi 0.7.5 or newer to delete a deck and its subdecks in one sync |
| [Yomine](https://github.com/mcgrizzz/Yomine) | Japanese immersion miner | [`7044efc`](https://github.com/mcgrizzz/Yomine/tree/7044efc), 2026-10-15 | 13 | Works with AnkiConnect or with Tsunagi's own API; this checks its AnkiConnect mode |
| [Yomitan](https://github.com/yomidevs/yomitan) | Pop-up dictionary extension; mines words | [`e7334a9`](https://github.com/yomidevs/yomitan/tree/e7334a9), 2026-10-15 | 22 |  |

Using another AnkiConnect tool? Try it, and [open an issue](https://github.com/mcgrizzz/Tsunagi/issues) to say how it went.

<!-- Written by tools/compatible_clients.py from tests/clients; edit those, not this page. -->
