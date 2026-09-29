#!/usr/bin/env python3
"""Restart Anki with only AnkiConnect or only Tsunagi enabled, for benchmarks.

    python tools/bench_switch.py ankiconnect --profile "My Test Profile"
    python tools/bench_switch.py tsunagi --profile "My Test Profile"

Windows only. Asks the running API to close Anki (AnkiConnect's
guiExitAnki, which Tsunagi also answers; Tsunagi needs a key with the manage
permission in TSUNAGI_BENCH_API_KEY), waits for Anki to exit, sets the two
add-ons' "disabled" flags in their meta.json, starts Anki on the profile and
waits until the chosen API answers. It never kills Anki: if Anki doesn't
close, it stops and says so.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ADDONS = Path(os.environ.get("APPDATA", "")) / "Anki2" / "addons21"
ANKI_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Anki" / "anki.exe"
ANKICONNECT = "2055492159"
TSUNAGI = "tsunagi"
PORTS = {"ankiconnect": 8765, "tsunagi": 7777}


def ask(port, action, timeout=3.0):
    """One AnkiConnect-style action; None when nothing answers."""
    body = json.dumps({"action": action, "version": 6}).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}", data=body,
                                     headers={"Content-Type": "application/json"})
    key = os.environ.get("TSUNAGI_BENCH_API_KEY")
    if key:
        request.add_header("X-Api-Key", key)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("api", choices=sorted(PORTS))
    parser.add_argument("--profile", default=os.environ.get("TSUNAGI_BENCH_PROFILE"),
                        help="Anki profile to open (or set TSUNAGI_BENCH_PROFILE)")
    parser.add_argument("--anki-exe", type=Path, default=ANKI_EXE)
    args = parser.parse_args()
    if not args.profile:
        parser.error("--profile is required (or set TSUNAGI_BENCH_PROFILE)")
    if not args.anki_exe.exists():
        parser.error(f"Anki not found at {args.anki_exe}; pass --anki-exe")

    if anki_running():
        print("Closing Anki...")
        # Anki can close before it answers, so judge by whether it exits.
        for port in PORTS.values():
            ask(port, "guiExitAnki")
        wait(lambda: not anki_running(), 120,
             "Anki to close. A sync on close can take a while; Tsunagi also needs "
             "TSUNAGI_BENCH_API_KEY set to a key with the manage permission. Or close Anki yourself and rerun")

    print(f"AnkiConnect {set_disabled(ANKICONNECT, args.api != 'ankiconnect')}, "
          f"Tsunagi {set_disabled(TSUNAGI, args.api != 'tsunagi')}")
    # Anki's console output (add-on warnings, tracebacks) goes to a log file,
    # not this terminal, and Ctrl+C here doesn't reach Anki.
    log = Path(tempfile.gettempdir()) / "anki-bench-console.log"
    with open(log, "w", encoding="utf-8") as out:
        subprocess.Popen([str(args.anki_exe), "-p", args.profile], stdin=subprocess.DEVNULL,
                         stdout=out, stderr=subprocess.STDOUT, close_fds=True,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    print(f"Anki's console output: {log}")
    port = PORTS[args.api]
    print(f"Starting Anki on {args.profile!r}, waiting for {args.api} on port {port}...")
    wait(lambda: ask(port, "version", timeout=1.0) is not None, 120, f"{args.api} to answer on port {port}")
    print(f"Ready: {args.api} on http://127.0.0.1:{port}")


if __name__ == "__main__":
    main()
