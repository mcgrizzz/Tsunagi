# Manual release checks

[← Documentation](README.md) · [Automated checks](development.md#tests)

Use a disposable Anki profile and record the Anki version, operating system and
Tsunagi version shown in settings. The automated suite covers API behavior; these
checks exercise installation, real windows and client connections.

## Install and configure

- [ ] Install the candidate `.ankiaddon`, restart Anki and open **Tsunagi Settings**.
- [ ] Confirm the footer shows the candidate version on every tab.
- [ ] Change a setting, cancel, and reopen to confirm it wasn't saved. Then save
  a change and confirm it persists.
- [ ] Change the port and confirm the API answers at the new address. Restore it.
- [ ] Open the interactive reference at the configured address and try a health
  check and a small collection query.

## Connect a real client

- [ ] Connect Yomitan or another AnkiConnect client using the configured port/key.
- [ ] Confirm the client's deck and note-type choices load, then add a sample note.
- [ ] Check the note's fields, tags and any attached media in Anki.
- [ ] If testing migration, import AnkiConnect settings, review **Ready to import**,
  and save. Confirm its port is adopted, existing allowed origins are retained,
  AnkiConnect is disabled, and **Last import** updates.

## Desktop behavior

- [ ] Exercise the Browser, Add Cards and note preview using sample data.
- [ ] Test covered and minimized windows separately. Record whether the window
  restores, comes forward and accepts typing in the intended field. Windows may
  flash the taskbar button when foreground activation is refused.
- [ ] Open the import picker, leave it open, then cancel. The Tsunagi API's GUI
  import returns after accepting the request to open the UI; it does not report a
  completed import.
- [ ] Close and reopen Anki; confirm the server starts and the client reconnects.

Run sync, profile switching or exit scenarios only when they are part of the test
and won't interrupt other work. Historical outcomes are in the
[archived manual log](archive/manual_test_plan.md); unchecked boxes here are a
reusable checklist, not a record of defects or a claim that this release was tested.

## Experimental editor

Anki 26.09.2's experimental Add window is not yet supported for API draft
editing. While that window is open, Tsunagi returns an explicit unsupported-editor
error for Add Cards actions, preserving its draft and avoiding a second window.
An automated offscreen check with the experimental preference enabled verified
that typed text survives rejected requests, Keep Editing retains it, and Discard
closes the window without adding a note. The legacy Add workflow also passes
its automated checks.

An isolated experimental-editor prototype also passed complete draft prefill,
field/tag updates, note-type/deck transfer, explicit Add and Undo, including a
media reference and the saved-note observer's ID. That prototype supplied all
draft options itself. The editor cannot report a draft's tags back to Tsunagi,
so the adapter is deferred until Anki exposes them; it is not enabled in the
add-on.

The Browser and Edit Current windows do work with the experimental editor. An
automated offscreen check covered opening the Browser on a note, searching,
selecting cards, and switching notes with unsaved typing. It also covered API
edits reloading an open Browser or Edit Current editor, and saving typing on
close. The AnkiConnect Shim's standalone editor still uses the legacy editor.
Two Anki issues remain, and both happen without Tsunagi. Anki's Edit Current
window logs an error when it is closed programmatically, such as on profile
switch. A Browser closed after it loads a note but before its editor page is
ready never finishes closing.

The first four items below apply to a future Add-window adapter. They are
pending checks, not a claim of current support:

- [ ] Enable Anki's experimental editor and open Add from Anki. Update fields
  through the API; confirm the existing window changes and no second window opens.
- [ ] Prefill fields, tags, media, note type and deck. Confirm the collection has
  no new note until you click **Add**. Check that append keeps the existing draft.
- [ ] Replace a draft and exercise **Keep Editing** and **Discard** separately.
  Confirm the API respects the chosen action.
- [ ] Add the note and verify the saved fields, tags, deck, media and emitted
  note ID. Confirm **Undo** removes the added note.
- [ ] Optional foreground check of the automated result: open the Browser and
  standalone edit dialog through the API. Test search, editing, preview, note
  switching and closing with unsaved changes.
