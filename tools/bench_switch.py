#!/usr/bin/env python3
"""Restart Anki with only AnkiConnect or only Tsunagi enabled, for benchmarks.

    python tools/bench_switch.py ankiconnect --profile "My Test Profile"
    python tools/bench_switch.py tsunagi --profile "My Test Profile"
    python tools/bench_switch.py restore --profile "My Usual Profile"

Every other add-on is turned off too: add-ons that draw on the deck list
(Study Time Stats, Review Heatmap) redraw after each card change while Anki
has focus, and every request waits for them (0.3-0.5 s on 283,000 reviews,
2026-11-27). The first switch saves each add-on's state to
tsunagi-bench-addons.json beside addons21; `restore` puts them all back,
deletes that file and starts Anki on the profile. --keep-addons leaves the
other add-ons as they are.

Windows only. Asks the running API to close Anki (AnkiConnect's
guiExitAnki, which Tsunagi also answers; Tsunagi needs a key with the manage
permission in TSUNAGI_BENCH_API_KEY, and an AnkiConnect with a key of its own
needs it in ANKICONNECT_API_KEY). If Anki is still open a few seconds later
(AnkiConnect's guiExitAnki left it open, 2026-10-03), it asks Windows to
close Anki's window (taskkill without /f, like clicking X). It waits for Anki to exit, sets the two
add-ons' "disabled" flags in their meta.json, starts Anki on the profile and
waits until the chosen API answers. It never kills Anki: if Anki doesn't
close, it stops and says so.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ADDONS = Path(os.environ.get("APPDATA", "")) / "Anki2" / "addons21"
SNAPSHOT = ADDONS.parent / "tsunagi-bench-addons.json"
ANKI_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Anki" / "anki.exe"
ANKICONNECT = "2055492159"
TSUNAGI = "tsunagi"
PORTS = {"ankiconnect": 8765, "tsunagi": 7777}


def ask(api, action, timeout=3.0):
    """One AnkiConnect-style action to that API's port; None when nothing answers.

    Each API gets only its own key: AnkiConnect reads it from the body and
    refuses any key but its own, Tsunagi reads the X-Api-Key header.
    """
    payload = {"action": action, "version": 6}
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("ANKICONNECT_API_KEY" if api == "ankiconnect" else "TSUNAGI_BENCH_API_KEY")
    if key and api == "ankiconnect":
        payload["key"] = key
    elif key:
        headers["X-Api-Key"] = key
    request = urllib.request.Request(f"http://127.0.0.1:{PORTS[api]}",
                                     data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"null")
    except Exception:
        return None


def anki_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq anki.exe", "/NH"],
                         capture_output=True, text=True).stdout
    return "anki.exe" in out.lower()


def wait(check, seconds, what):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.5)
    sys.exit(f"Gave up after {seconds} s waiting for {what}.")


def set_disabled(folder, disabled):
    path = ADDONS / folder / "meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    if meta.get("disabled", False) != disabled:
        meta["disabled"] = disabled
        path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return "off" if disabled else "on"


def addon_states():
    """Each add-on folder with a meta.json -> whether it is disabled."""
    return {path.parent.name: bool(json.loads(path.read_text(encoding="utf-8")).get("disabled", False))
            for path in sorted(ADDONS.glob("*/meta.json"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("api", choices=sorted(PORTS) + ["restore"])
    parser.add_argument("--profile", default=os.environ.get("TSUNAGI_BENCH_PROFILE"),
                        help="Anki profile to open (or set TSUNAGI_BENCH_PROFILE)")
    parser.add_argument("--anki-exe", type=Path, default=ANKI_EXE)
    parser.add_argument("--keep-addons", action="store_true",
                        help="leave the other add-ons as they are")
    args = parser.parse_args()
    if not args.profile:
        parser.error("--profile is required (or set TSUNAGI_BENCH_PROFILE)")
    if not args.anki_exe.exists():
        parser.error(f"Anki not found at {args.anki_exe}; pass --anki-exe")
    if args.api == "restore" and not SNAPSHOT.exists():
        parser.error(f"nothing to restore: {SNAPSHOT} doesn't exist")

    if anki_running():
        print("Closing Anki...")
        # Anki can close before it answers, so judge by whether it exits.
        for api in PORTS:
            ask(api, "guiExitAnki")
        deadline = time.monotonic() + 5
        while anki_running() and time.monotonic() < deadline:
            time.sleep(0.5)
        if anki_running():
            # A normal close request, as clicking X: Anki unloads the profile itself.
            subprocess.run(["taskkill", "/IM", "anki.exe"], capture_output=True)
        wait(lambda: not anki_running(), 120,
             "Anki to close. A sync on close can take a while. Closing needs Tsunagi's key "
             "(TSUNAGI_BENCH_API_KEY, with the manage permission) or AnkiConnect's, if it has one "
             "(ANKICONNECT_API_KEY). Or close Anki yourself and rerun")

    if args.api == "restore":
        saved = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        for folder, disabled in saved.items():
            if (ADDONS / folder / "meta.json").exists():
                set_disabled(folder, disabled)
        SNAPSHOT.unlink()
        print(f"Add-ons restored ({sum(not d for d in saved.values())} on)")
        # Wait for whichever API is on now; Tsunagi first.
        args.api = next((api for api, folder in (("tsunagi", TSUNAGI), ("ankiconnect", ANKICONNECT))
                         if not saved.get(folder, True)), None)
    else:
        if not args.keep_addons:
            if not SNAPSHOT.exists():  # the state before the first switch, kept across switches
                SNAPSHOT.write_text(json.dumps(addon_states(), indent=1), encoding="utf-8")
            others = [f for f, disabled in addon_states().items()
                      if not disabled and f not in (ANKICONNECT, TSUNAGI)]
            for folder in others:
                set_disabled(folder, True)
            if others:
                print(f"{len(others)} other add-ons off until `restore`")
        print(f"AnkiConnect {set_disabled(ANKICONNECT, args.api != 'ankiconnect')}, "
              f"Tsunagi {set_disabled(TSUNAGI, args.api != 'tsunagi')}")
    # Anki writes its console output (add-on warnings, tracebacks) to the
    # console of whatever started it. Start it through a short-lived cmd with a
    # hidden console of its own, so none of it lands in this terminal and
    # Ctrl+C here doesn't reach Anki.
    subprocess.Popen(["cmd", "/c", "start", "", str(args.anki_exe), "-p", args.profile],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    if args.api is None:
        print(f"Started Anki on {args.profile!r}; neither API is on")
        return
    port = PORTS[args.api]
    print(f"Starting Anki on {args.profile!r}, waiting for {args.api} on port {port}...")
    wait(lambda: ask(args.api, "version", timeout=1.0) is not None, 120, f"{args.api} to answer on port {port}")
    print(f"Ready: {args.api} on http://127.0.0.1:{port}")


if __name__ == "__main__":
    main()
