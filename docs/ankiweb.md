# AnkiWeb listing

The text of Tsunagi's [AnkiWeb page](https://ankiweb.net/shared/info/666370974),
one section per field of AnkiWeb's upload form. Update it here, then paste each
section into the form when uploading a release.

## Title

A one-line description, under 80 characters. The same name as `manifest.json`,
which Anki shows in its add-on list.

```text
Tsunagi - Modern API access to Anki
```

## Tags

Optional, space-separated. AnkiWeb keeps only the first 80 characters,
spaces included.

```text
ankiconnect api automation developer-tools mining yomitan language-learning
```

## Support page

Optional; must start with `http`.

```text
https://github.com/mcgrizzz/Tsunagi
```

## Branches

For the final branch's maximum, a `-` prefix (e.g. `-2.1.66`) blocks downloads
on newer Anki. Keep the minimum in step with `min_point_version` in
`manifest.json`.

```text
Branch 1
Supports: [ 26.08.0 ] - [ 26.09.0 ]
```

## Description

Markdown and basic HTML. AnkiWeb joins lines into one paragraph, so separate
the links with blank lines.

```markdown
Tsunagi (繋ぎ, “connection”) connects Anki Desktop to dictionary tools, mining apps and scripts. Existing **AnkiConnect** tools work as they are, and the **Tsunagi API** gives new apps more to work with.

### Features

* Works with AnkiConnect tools; imports your AnkiConnect port, key and allowed websites
* A key for each app, with a choice of what it may do; turn an app off without deleting it
* Ask for just the notes, cards and fields you need, using Anki's search
* Hear about changes to notes, cards and reviews instead of asking again and again
* Undo changes made through the API with **Edit → Undo**
* Try every request in the interactive API reference

After installing, restart Anki and open **Tools → Tsunagi Settings**. Coming from AnkiConnect? Open the **AnkiConnect** page there and click **Import AnkiConnect settings**.

> **Experimental.** Supports Anki 26.08 and 26.09. The Tsunagi API still changes quickly; the AnkiConnect side stays stable.

[Documentation and source code](https://github.com/mcgrizzz/Tsunagi)

[AnkiConnect compatibility](https://github.com/mcgrizzz/Tsunagi/blob/main/docs/ankiconnect_parity.md)

[Report a problem](https://github.com/mcgrizzz/Tsunagi/issues)
```
