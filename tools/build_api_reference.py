"""Build the public API reference: the local reference page, read-only, over a
release's API description. The API reference workflow publishes it to GitHub
Pages; run it yourself to look at the result:

    python tools/build_api_reference.py --version 0.6.0 --out site
    python -m http.server -d site

The page is Scalar with the settings the add-on serves at http://127.0.0.1:7777/
(tsunagi/http/playground.py), except that it can't send requests: a page on
another website can't reach your Anki, and Tsunagi refuses websites you haven't
allowed. The description's introduction says so and where to send them instead.
"""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_LINKS = "[Swagger](/docs) · [ReDoc](/redoc) · [OpenAPI JSON](/openapi.json)"


def playground():
    """tsunagi/http/playground.py alone: it's plain strings, and importing the
    tsunagi package would need Anki."""
    spec = importlib.util.spec_from_file_location("playground", ROOT / "tsunagi/http/playground.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(snapshot: Path, version: str, out: Path) -> None:
    schema = json.loads(snapshot.read_text(encoding="utf-8"))
    description = schema["info"]["description"]
    if LOCAL_LINKS not in description:
        raise SystemExit("The API description's local links changed; update LOCAL_LINKS.")
    schema["info"]["version"] = version
    # The examples' address: Tsunagi's default. The local page uses its own.
    schema["servers"] = [{"url": "http://127.0.0.1:7777", "description": "Tsunagi on this computer"}]
    schema["info"]["description"] = (
        f"> **Tsunagi {version}, read-only.** To send requests, install Tsunagi and open "
        "<http://127.0.0.1:7777/> while Anki runs: the same reference, sending real requests "
        "to your collection.\n\n"
        + description.replace(LOCAL_LINKS, "[OpenAPI JSON](openapi.json) · "
                              "[Tsunagi on GitHub](https://github.com/mcgrizzz/Tsunagi)"))

    html = playground().PLAYGROUND_HTML
    replacements = {
        "url: '/openapi.json',": "url: 'openapi.json',",
        "baseServerURL: window.location.origin,": "baseServerURL: 'http://127.0.0.1:7777',\n"
                                                   "        hideTestRequestButton: true,",
        '<a href="/docs">Swagger</a> · <a href="/redoc">ReDoc</a> · <a href="/openapi.json">OpenAPI JSON</a>':
            '<a href="openapi.json">OpenAPI JSON</a>',
        "<title>Tsunagi API reference</title>": f"<title>Tsunagi {version} API reference</title>",
    }
    for old, new in replacements.items():
        if old not in html:
            raise SystemExit(f"The local reference page changed; update build_api_reference.py ({old!r}).")
        html = html.replace(old, new)

    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "openapi.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", required=True, help="the release the description is from, such as 0.6.0")
    parser.add_argument("--snapshot", type=Path, default=ROOT / "tests/snapshots/openapi.json")
    parser.add_argument("--out", type=Path, default=ROOT / "site")
    args = parser.parse_args()
    build(args.snapshot, args.version, args.out)
    print(f"Wrote {args.out}/index.html and {args.out}/openapi.json")
