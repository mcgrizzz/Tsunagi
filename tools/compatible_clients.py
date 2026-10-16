"""
Write docs/compatible_clients.md, the tested AnkiConnect tools (6.136), from
their declarations (tests/clients/<name>/client.py). tests/test_clients.py
fails when the page is out of date.

    python tools/compatible_clients.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/compatible_clients.md"
ISSUES = "https://github.com/mcgrizzz/Tsunagi/issues"

INTRO = """\
# Tested AnkiConnect tools

Every AnkiConnect action has its own tests; the few that need Anki's windows
are checked by hand ([compatibility notes](ankiconnect_parity.md)). The tools
below are extra insurance, in case a tool sends something those tests don't
expect.

These tools were checked request by request against Tsunagi. For each one,
we read its source at the commit shown and listed the requests it sends to
Anki. On every change, Tsunagi's tests check that each of those requests gets
the answer AnkiConnect gave before its October 2026 rewrite (`de6e6e1`, the
last version before it), including for cards that are new, learning, in
review, relearning, suspended, buried or in a filtered deck.

The tools' own code isn't run, so what a tool does with Anki's windows, such
as opening the Browser, isn't covered.
"""


def render() -> str:
    sys.path[:0] = [str(ROOT / "tests")]
    from clients.support import clients

    rows = []
    for module in sorted(clients().values(), key=lambda m: m.CLIENT["name"].lower()):
        c = module.CLIENT
        requests = sum(len(shapes) for shapes, _reads in module.SENDS.values())
        needs = c.get("needs")
        notes = [f"Needs Tsunagi {needs[0]} or newer {needs[1]}" if needs else "", c.get("note", "")]
        note = ". ".join(n for n in notes if n)
        rows.append(f"| [{c['name']}]({c['repo']}) | {c['about']} | "
                    f"[`{c['commit']}`]({c['repo']}/tree/{c['commit']}), {c['read']} | {requests} | {note} |")
    table = "\n".join(["| Tool | What it is | Checked | Requests checked | Notes |",
                       "| --- | --- | --- | --- | --- |", *rows])
    return (f"{INTRO}\n{table}\n\n"
            f"Using another AnkiConnect tool? Try it, and [open an issue]({ISSUES}) to say how it went.\n\n"
            "<!-- Written by tools/compatible_clients.py from tests/clients; edit those, not this page. -->\n")


if __name__ == "__main__":
    PAGE.write_text(render(), encoding="utf-8")
    print(f"wrote {PAGE.relative_to(ROOT)}")
