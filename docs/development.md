# Developing Tsunagi

[← Back to the README](../README.md) · [Yomitan walkthrough](api_recipes.md)

For working on the add-on itself. To build a tool that uses Tsunagi, start
with the [Yomitan walkthrough](api_recipes.md) instead. Commands run from the
repository root.

## Set up

```sh
git clone https://github.com/mcgrizzz/Tsunagi.git
cd Tsunagi
python -m venv .venv
. .venv/bin/activate                  # Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install pytest ruff httpx anki
python tools/build_addon.py
```

- `build_addon.py` puts the dependencies from
  [tools/requirements.lock.txt](../tools/requirements.lock.txt) into
  `lib/shared` and packages the add-on into `dist/`. Anki itself is only a
  test dependency and is never bundled.
- Once the wheels are cached, `python tools/build_addon.py --offline` builds
  without downloading.
- Tsunagi supports the current Anki release and the one before it. To test
  the older one, use Python 3.10 and install `anki==26.8.1` instead of `anki`.

## Tests

```sh
ruff check .
python -m pytest -q
```

Backend tests use temporary Anki collections. The rest are optional. The Qt
checks need a second environment with Anki's GUI package, as CI makes it:

```sh
python -m venv .venv-qt
. .venv-qt/bin/activate               # Windows PowerShell: .\.venv-qt\Scripts\Activate.ps1
python -m pip install pytest httpx "aqt[qt6]"
```

On Linux, Qt also needs some system libraries; the list CI installs is in
[qt.yml](../.github/workflows/qt.yml). Run the Qt checks with this
environment active.

| Check | Needs | Run |
| --- | --- | --- |
| Qt tests and real-Anki checks | a Python with `aqt` and Qt | `tools/qt_checks.sh` (offscreen, what CI runs) |
| A single Qt check | the same | `python tools/check_add_cards.py`, etc. |
| Browser check of the API reference | Playwright and Chromium in their own environment | `TSUNAGI_BROWSER_PYTHON=/path/to/python python -m pytest -q tests/test_playground.py` |
| Media and FSRS Helper checks | a real Anki; FSRS Helper installed for the second | `python tools/check_media.py`, `python tools/check_fsrs_helper_provider.py` (by hand, not in CI) |

- Set `TSUNAGI_GUI_PYTHON` and `TSUNAGI_BROWSER_PYTHON` to include the Qt and
  browser checks in a full `pytest` run. Tests for another Anki version still
  skip.
- Set `TSUNAGI_STRICT_ANKI_NOTICES=1` to fail on any deprecation notice Anki
  prints. Notices are always listed at the end of the run.
- **API contract.** `tests/snapshots/openapi.json` records the published
  schema, so any change shows up as a diff. After an intended change,
  regenerate it with
  `TSUNAGI_UPDATE_OPENAPI=1 python -m pytest -q tests/test_openapi_snapshot.py`
  and commit it.
- **Screenshots.** After changing the settings page, regenerate the images in
  `config.md` with `python tools/settings_screenshots.py` (Qt Python; writes
  `docs/images/settings-*.png`).
- Qt checks make a temporary profile; use throwaway profiles for your own
  experiments too. Offscreen checks can't show how windows behave on Windows,
  so finish with the [manual release checks](manual_testing.md).

<details>
<summary>AnkiConnect comparisons</summary>

- To see whether upstream AnkiConnect gained or dropped actions, pull a local
  checkout of it and run `python tools/check_parity.py`. The routine tests only
  compare the [compatibility page](ankiconnect_parity.md) with Tsunagi's own
  actions.
- The broad comparison suite against upstream is archived in Git at `3c8e2dd`
  (`tests/test_upstream_*.py`, `tests/upstream_support.py`). To run it again,
  check out that revision separately and set `TSUNAGI_ANKICONNECT_CHECKOUT` to
  an upstream checkout. It isn't part of the maintained suite.
- Performance comparisons with AnkiConnect: [benchmarks](benchmarks.md).
  Profiling and past optimizations: [performance notes](performance_notes.md).

</details>

## CI

- [ci.yml](../.github/workflows/ci.yml) runs the suite on both supported
  Anki versions, the [Qt checks](../.github/workflows/qt.yml) on the newest,
  and `pip-audit` on the bundled dependencies. Advisories that don't apply are
  listed with their reason in `ci.yml`; any new one fails the build.
- The [Anki watch](../.github/workflows/anki-watch.yml) runs daily. When PyPI
  has an Anki release, beta or RC it hasn't tested, it runs the suite and Qt
  checks against it and records the result as an `anki-watch` issue (closed if
  everything passed).

## Try changes in Anki

Install a built package once, then copy your source changes into that add-on
folder:

```sh
python tools/dev_sync.py --dest /path/to/Anki2/addons21/tsunagi
```

- `--watch` keeps copying as you edit; `--full` also copies `lib/` after you
  rebuild dependencies.
- Copying doesn't reload the running add-on: restart Anki, or set
  `dev_watch_seconds` ([settings without a field](../config.md#settings-without-a-field))
  so Tsunagi reloads itself. Changes to the root `__init__.py` or to `lib/`
  always need a restart.
- Tsunagi logs to Anki's log folder for the add-on (`logs/addons/` in Anki's
  data folder), not the console.
- If another add-on has already loaded a different version of FastAPI,
  Starlette, pydantic or uvicorn, Tsunagi refuses to start and names it.
  `tools/check_vendor_clash.py` tests that in a real Anki.

## Package for AnkiWeb

Keep the version the same in `tools/version.py`, `tsunagi/shared/version.py`
and `pyproject.toml`, then run `python tools/build_addon.py`. It prints where
it put:

| File | Purpose |
| --- | --- |
| `dist/tsunagi-<version>.ankiaddon` | Upload to [AnkiWeb](https://ankiweb.net/shared/addons/). Also works with **Install from file**. |
| `dist/tsunagi-<version>.ankiaddon.sha256` | Checksum for verifying the package. |

- The package holds the add-on's code, assets, bundled dependencies, licence
  notices, `README.md` and `config.md`. It leaves out your local `meta.json`,
  bytecode, tools, tests and the `docs/` folder.
- It checks the required files, JSON and ZIP before replacing an older
  package, and never uploads anything.
- `--offline` reuses cached dependencies; `--refresh` downloads them again.
  Not both.

## GitHub releases

Commit matching versions in the three files above and push. Then either:

- open **Actions → Release → Run workflow** on `main` (it uses the declared
  version, so `0.1.0` becomes `v0.1.0`), or
- push a tag yourself: `git tag -a v0.1.0 -m "Tsunagi 0.1.0" && git push origin v0.1.0`.

The [Release workflow](../.github/workflows/release.yml):

1. checks the three versions agree (and match the tag, if you pushed one);
2. runs CI: the suite on both Anki versions, the Qt checks and the
   dependency audit;
3. builds the package;
4. creates the tag at the tested commit if a manual run needs one;
5. makes a **draft GitHub release** with generated notes, the `.ankiaddon` and
   its checksum. Review it and publish when ready.

- Uploading to AnkiWeb is a separate step with the same `.ankiaddon`. Paste the
  listing from [ankiweb.md](ankiweb.md) into the upload form, updated first if
  the release changes what it says.
- To retry, rerun the workflow or run **Release** on the existing tag
  (`gh workflow run release.yml --ref v0.1.0`). Reruns update a draft's files
  and never touch a published release.
- A tag must point at the commit that was tested. A newer `main` needs a new
  version, not the old tag.
- It uses GitHub's built-in token; no secret needed.
- The browser check isn't part of CI; run it [before tagging](#tests).

## Code organization

- `tsunagi/http/`: API routes, the AnkiConnect endpoint and the HTTP middleware.
- `tsunagi/adapters/`: everything that talks to Anki, settings, and running
  operations.
- `tsunagi/web/`: the settings page, shown in a Qt dialog by
  `adapters/settings_page.py`.
- `tsunagi/shared/`: schemas, permissions, and shared query and error
  handling.
- `tools/`: packaging, development sync, checks and benchmarks.

Prefer Anki's public APIs, and keep any direct database access in the adapter
layer. Account for the running Anki version. Use the existing operation
dispatch for threading and undo; GUI work belongs on Qt's main thread.
