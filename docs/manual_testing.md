# Manual release checks

[← Documentation](README.md) · [Automated checks](development.md#tests)

What the automated tests can't cover: installing, real windows, and real
tools. Use a throwaway Anki profile, and note the Anki version, operating
system and Tsunagi version (shown at the bottom of the settings window).

The boxes are a checklist to reuse for each release, not a record. Past
results are in the [archived manual log](archive/manual_test_plan.md).

## Install and settings

- [ ] Install the candidate `.ankiaddon`, restart Anki and open **Tools →
  Tsunagi Settings**.
- [ ] The bottom of the window shows the candidate version and that the server
  is running.
- [ ] Change a setting and click **Cancel**; close and reopen: it wasn't saved.
  Save a change: it's kept. Close with an unsaved change: the window asks
  first.
- [ ] Change the port: the API answers at the new address. Change it back.
- [ ] Open the API reference at that address; try a health check and a small
  notes query.
- [ ] On **Apps & keys**, add an app with the Read-only role. With its key, a
  read works and a write gets 403 naming the role. Untick **On** and Save: its
  requests get 403 saying it's turned off. Both show on **Recent requests**
  under the app's name.
- [ ] Anki's add-on log (`logs/addons/` in Anki's data folder) has Tsunagi's
  start line.

## A real tool

- [ ] Connect Yomitan or another AnkiConnect tool to the configured port (and
  key, if you set one).
- [ ] Its deck and note-type lists load; add a sample note.
- [ ] The note's fields, tags and media are right in Anki.
- [ ] *Only when testing the switch from AnkiConnect:* import its settings on
  the **AnkiConnect** page, review them and Save. Tsunagi takes over its port, your
  allowed websites are kept, AnkiConnect is turned off, and the last-import
  date updates.

## Windows and desktop

- [ ] Open the Browser, Add Cards and a note preview through the API, with
  sample data.
- [ ] Try it with Anki covered by another window, and with Anki minimized. The
  window opens and, once you switch to it, typing goes into one of the note's
  fields, not elsewhere. Windows may flash the taskbar
  button instead of bringing Anki forward; that's fine. A window that doesn't
  open, or typing that lands in the wrong field, is a release problem.
- [ ] Open the import picker through the API, leave it, then cancel. The API
  answers once the picker opens; it doesn't wait for an import.
- [ ] Close and reopen Anki: the server starts and the tool reconnects.

Test sync, profile switching or closing Anki only when that's the point of the
test and won't disturb other work.

## Anki's experimental editor

If you use Anki's experimental editor: with it turned on, open the Browser and
Edit Current through the API and edit a note; both should work. The Add
window isn't supported yet (Add Cards actions through the API answer with an
"unsupported editor" error), so there's nothing to check there.
