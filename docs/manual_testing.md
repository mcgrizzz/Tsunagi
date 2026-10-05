# Manual release checks

[← Documentation](README.md) · [Automated checks](development.md#tests)

What the automated tests can't cover: installing, real windows, and real
tools. Use a throwaway Anki profile, and note the Anki version, operating
system and Tsunagi version (shown at the bottom of the settings window).

The boxes are a checklist to reuse for each release, not a record. Past
results are in the [archived manual log](archive/manual_test_plan.md).

## Install and settings

- [ ] Install the candidate `.ankiaddon` (from `kiso build` or the draft
  release), restart Anki and open **Tools → Tsunagi Settings...**.
- [ ] The bottom of the window shows the candidate version and that the server
  is running.
- [ ] Change a setting: the bottom of the window says there are unsaved
  changes. Click **Cancel**: the change is undone. Save a change, close and
  reopen: it's kept. Close with an unsaved change: the window asks first and
  names the pages with changes.
- [ ] Change the port: the API answers at the new address. Change it back.
- [ ] Open the API reference at that address; try a health check and a small
  notes query.
- [ ] On **Apps & keys**, add an app with the Read-only role. With its key, a
  read works and a write gets 403 naming the role. Untick **On** and Save: its
  requests get 403 saying it's turned off. Both show on **Recent requests**
  under the app's name.
- [ ] Anki's add-on log (`logs/addons/` in Anki's data folder) has Tsunagi's
  start line.
- [ ] Turn Tsunagi off in **Tools → Add-ons**: Anki asks whether to stop the
  server. **Stop the server now**: the API stops answering and a tooltip says
  so. Turn Tsunagi back on: the API answers again and a tooltip says the
  server is running.

## A real tool

- [ ] Connect Yomitan or another AnkiConnect tool to the configured port (and
  key, if you set one).
- [ ] Its deck and note-type lists load; add a sample note.
- [ ] The note's fields, tags and media are right in Anki.
- [ ] *Only when testing the switch from AnkiConnect:* on the **Server** page,
  click **Take over from AnkiConnect…**, check what the dialog lists and click
  **Take over**. Tsunagi moves to AnkiConnect's port, AnkiConnect's key and
  allowed websites carry over, AnkiConnect is turned off, and the Server page
  says when Tsunagi took over. (When AnkiConnect is installed, Tsunagi's first
  start offers this by itself.)

## Windows and desktop

- [ ] Open the Browser, Add Cards and the note editor (`guiEditNote`) through
  the API, with sample data. In the note editor, open **Preview**.
- [ ] Try it with Anki covered by another window, and with Anki minimized. The
  window opens and, once you switch to it, typing goes into one of the note's
  fields (Add Cards, the note editor), not elsewhere. The Browser on a search
  focuses its search bar, as Anki's own does. Windows may flash the taskbar
  button instead of bringing Anki forward; that's fine. A window that doesn't
  open, or typing that lands in the wrong field, is a release problem.
- [ ] Open the import picker with `POST /v1/gui:import-file`, leave it, then
  cancel. The API answers as soon as Anki accepts the request; it doesn't wait
  for an import.
- [ ] Close and reopen Anki: the server starts and the tool reconnects.

Test sync, profile switching or closing Anki only when that's the point of the
test and won't disturb other work.

## Anki's experimental editor

If you use Anki's experimental editor, turn it on and:

- [ ] Open the Browser through the API and edit a note in it.
- [ ] With the Browser or Edit Current showing a note, change that note
  through the API: the editor shows the change.
- [ ] With Anki's experimental Add window open, an Add Cards action through
  the API answers with an error asking you to close that window, and what you
  typed there stays.
