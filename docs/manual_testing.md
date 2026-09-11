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
- [ ] Open the import picker, leave it open, then cancel. Native GUI import returns
  after accepting the request to open the UI; it does not report a completed import.
- [ ] Close and reopen Anki; confirm the server starts and the client reconnects.

Run sync, profile switching or exit scenarios only when they are part of the test
and won't interrupt other work. Historical outcomes are in the
[archived manual log](archive/manual_test_plan.md); unchecked boxes here are a
reusable checklist, not a record of defects or a claim that this release was tested.
