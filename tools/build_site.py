"""
Build the project site (website/) into a folder: its pages, plus the data they
read, written from the same sources as the docs: the tested tools'
declarations (tests/clients), the AnkiConnect parity page, each action's
permission (its registration), the extracted benchmarks
(website/data/benchmarks.json, tools/extract_benchmarks.py) and the GitHub
releases. Each action's Tsunagi API route (website/data/native.json) is
checked against the API description.

    python tools/build_site.py --out /tmp/tsunagi-site
    python -m http.server -d /tmp/tsunagi-site
"""
import argparse
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "website"
PARITY = ROOT / "docs/ankiconnect_parity.md"
VERSION = ROOT / "tsunagi/shared/version.py"
COMPAT = ROOT / "tsunagi/http/compat"
OPENAPI = ROOT / "tests/snapshots/openapi.json"
RELEASES = "https://api.github.com/repos/mcgrizzz/Tsunagi/releases?per_page=100"
REGISTER = re.compile(r'register\(\s*"(\w+)"[^)]*?permission="([^"]+)"', re.S)
# Actions the registry gates another way: multi checks each action it carries.
PERMISSION_OF = {"multi": "each action it carries", "requestPermission": "public"}
GROUP = re.compile(r"^### (.+?) Actions$")
ROW = re.compile(r"^\|\s*`([A-Za-z]+)`\s*\|\s*([A-Za-z0-9-]+)\s*\|\s*(.*?)\s*\|$")


def parity():
    """Each AnkiConnect action on the parity page: its group, status and notes."""
    actions, group = {}, None
    for line in PARITY.read_text(encoding="utf-8").splitlines():
        if heading := GROUP.match(line):
            group = heading.group(1)
        elif group and (row := ROW.match(line)):
            actions[row.group(1)] = {"group": group, "status": row.group(2), "notes": row.group(3)}
    return actions


def permissions():
    """Each AnkiConnect action's permission, from its registration."""
    found = {}
    for path in sorted(COMPAT.rglob("*.py")):
        found.update(REGISTER.findall(path.read_text(encoding="utf-8")))
    return {**found, **PERMISSION_OF}


def broken(actions):
    """The parity page's "Where AnkiConnect is broken" bullets: whether Tsunagi
    fixed or kept each, its title, its text or sub-points, and the actions it
    names."""
    text = PARITY.read_text(encoding="utf-8").split("## Where AnkiConnect is broken or mislabeled", 1)[1]
    text = text.split("\n## ", 1)[0]
    out, kept = [], None
    for block in re.split(r"\n(?=- |\*\*)", text):
        if block.startswith("**Fixed in Tsunagi"):
            kept = False
        elif block.startswith("**Kept as AnkiConnect"):
            kept = True
        elif block.startswith("- **") and kept is not None:
            title, _, body = block[4:].partition("**")
            lead, *points = re.split(r"\n\s+- ", body)
            # "They are marked below" points at the parity page's own table.
            lead = " ".join(lead.split()).replace(" They are marked below.", "")
            out.append({"kept": kept, "title": title.rstrip(".:"), "text": lead,
                        "points": [" ".join(point.split()) for point in points],
                        "actions": sorted({a for a in re.findall(r"`([a-z][A-Za-z]+)`", title + body)
                                           if a in actions})})
    return out


def native(actions):
    """website/data/native.json, each route checked against the API description."""
    routes = {f"{m.upper()} {p}" for p, ops in json.loads(OPENAPI.read_text(encoding="utf-8"))["paths"].items()
              for m in ops}
    mapping = {k: v for k, v in json.loads((SITE / "data/native.json").read_text(encoding="utf-8")).items()
               if not k.startswith("_")}
    if set(mapping) != set(actions):
        raise SystemExit(f"native.json and the parity page differ: {sorted(set(mapping) ^ set(actions))}")
    unknown = [r for r, _ in mapping.values() if r and r not in routes]
    if unknown:
        raise SystemExit(f"native.json names routes the API doesn't have: {unknown}")
    return mapping


def releases():
    """Published releases, newest first: tag, date, the summary paragraph and
    each section's bullets (title and text), as the release notes write them."""
    with urllib.request.urlopen(RELEASES, timeout=30) as response:
        rows = json.load(response)
    out = []
    for r in rows:
        if r["draft"] or not r["tag_name"].startswith("v"):
            continue
        body = r["body"].replace("\r\n", "\n").split("**Full Changelog**")[0]
        summary, *sections = re.split(r"\n## ", "\n" + body)
        # The summary's own words: no title heading, no quote markers.
        summary = "\n".join(re.sub(r"^>\s?", "", line) for line in summary.splitlines() if not line.startswith("#"))
        parts = []
        for section in sections:
            name, _, rest = section.partition("\n")
            items = []
            for bullet in re.split(r"\n(?=- )", rest.strip()):
                if bullet.startswith("- **"):
                    title, _, text = bullet[4:].partition("**")
                    items.append({"title": title.rstrip("."), "text": " ".join(text.split())})
            parts.append({"name": name.strip(), "items": items})
        out.append({"tag": r["tag_name"], "date": r["published_at"][:10], "url": r["html_url"],
                    "summary": " ".join(summary.split()), "sections": parts})
    return out


def code_link(c, sites, action):
    """The first place in the tool's declared files that sends the action."""
    for site in sites.get(action, []):
        path, _, line = site["at"].rpartition(":")
        if path in c["files"]:
            return f"{c['repo']}/blob/{c['commit']}/{path}#L{line}"
    return None


def tools(groups):
    sys.path[:0] = [str(ROOT / "tests")]
    from clients.support import clients

    out = []
    for folder, module in sorted(clients().items(), key=lambda m: m[1].CLIENT["name"].lower()):
        c = module.CLIENT
        sites = json.loads((ROOT / "tests/clients" / folder / "sites.json").read_text(encoding="utf-8"))["sites"]
        out.append({
            "id": folder, "name": c["name"], "about": c["about"], "repo": c["repo"],
            "commit": c["commit"], "read": c["read"], "note": c.get("note", ""),
            "needs": c.get("needs"), "details": c.get("notes", ""), "envelope": module.ENVELOPE,
            "actions": [{"name": name, "requests": len(shapes), "group": groups.get(name, {}).get("group", "Other"),
                         "code": code_link(c, sites, name)}
                        for name, (shapes, _reads) in sorted(module.SENDS.items())],
        })
    return out


def summary(groups, tool_rows, release_rows):
    version = re.search(r'ADDON_VERSION = "(.+)"', VERSION.read_text(encoding="utf-8")).group(1)
    statuses = [a["status"] for a in groups.values()]
    bench = json.loads((SITE / "data/benchmarks.json").read_text(encoding="utf-8"))
    session = next(w for w in bench["runs"][0]["workloads"] if w["name"] == "mine_session")   # the newest run
    return {
        "version": version,
        "released": release_rows[0]["date"] if release_rows else None,
        "releases": len(release_rows),
        "parity": {"actions": len(statuses), "implemented": statuses.count("implemented")},
        "tools": {"count": len(tool_rows), "requests": sum(a["requests"] for t in tool_rows for a in t["actions"]),
                  "newest": max(t["read"] for t in tool_rows)},
        "mine_session": {impl: {"median_ms": r["median_ms"], "requests": r["requests"]}
                         for impl, r in session["results"].items()},
    }


def build(out: Path):
    groups = parity()
    tool_rows = tools(groups)
    perms, routes, release_rows = permissions(), native(groups), releases()
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(SITE, out)
    data = out / "data"
    (data / "native.json").unlink()   # folded into parity.json

    def write(name, value):
        (data / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")

    write("tools", {"tools": tool_rows, "groups": list(dict.fromkeys(g["group"] for g in groups.values()))})
    used = {}
    for t in tool_rows:
        for a in t["actions"]:
            used.setdefault(a["name"], []).append(t["id"])
    write("parity", {"actions": [{"name": name, **g, "tested": "hand" if "Checked by hand only" in g["notes"] else "suite", "permission": perms[name], "route": routes[name][0],
                                  "how": routes[name][1], "tools": used.get(name, [])}
                                 for name, g in groups.items()],
                     "broken": broken(groups)})
    write("releases", release_rows)
    write("summary", summary(groups, tool_rows, release_rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out)
