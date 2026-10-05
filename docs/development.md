# Developing Tsunagi

[← Back to the README](../README.md) · [Documentation](README.md)

For working on the add-on itself. To build a tool that uses Tsunagi, start
with the [Yomitan walkthrough](api_recipes.md) instead. Commands run from the
repository root.

## Set up

```sh
git clone https://github.com/mcgrizzz/Tsunagi.git
cd Tsunagi
python -m venv .venv
. .venv/bin/activate                  # Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install pytest ruff httpx anki "kiso-anki @ git+https://github.com/mcgrizzz/Kiso.git"
kiso vendor
```

- [Kiso](https://github.com/mcgrizzz/Kiso) is the plumbing Tsunagi shares with
  other add-ons: the wiring with Anki, config migration, the dev reload, the
  bundled libraries, and the `kiso` command. It's copied into `tsunagi/_kiso/`
  (not in Git) by pytest, `kiso build` and `kiso sync`. With a Kiso checkout
  next to this one, install it with `pip install -e ../kiso` instead.
- `kiso vendor` puts the web stack pinned in
  [tools/requirements.lock.txt](../tools/requirements.lock.txt) into
  `lib/shared`, from pure-Python wheels only (pytest does it too when
  `lib/shared` isn't current). Anki itself is only a test dependency and is
  never bundled. Once the wheels are cached in `.wheelhouse/`, `--offline`
  works without downloading.
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
python -m pip install pytest httpx "aqt[qt]" "kiso-anki @ git+https://github.com/mcgrizzz/Kiso.git"
```

On Linux, Qt also needs some system libraries; the list CI installs is in
[Kiso's setup action](https://github.com/mcgrizzz/Kiso/blob/main/action.yml). Run the
Qt checks with this environment active.

| Check | Needs | Run |
| --- | --- | --- |
| Qt tests and real-Anki checks | a Python with `aqt` and Qt | `tools/qt_checks.sh` (offscreen, what CI runs) |
| A single Qt check | the same | `python tools/check_add_cards.py`, etc. |
| Browser check of the API reference | Playwright and Chromium in their own environment | `TSUNAGI_BROWSER_PYTHON=/path/to/python python -m pytest -q tests/test_playground.py` |
| TypeScript client | Node 22 | `npm ci && npm test` in `packages/typescript`; then `python -m pytest -q tests/test_typescript_client.py` runs the built client against the server (skipped until it's built) |
| Media and FSRS Helper checks | the same; for the second, a copy of FSRS Helper | `python tools/check_media.py`, `FSRS_HELPER_DIR=/path/to/addons21/759844606 python tools/check_fsrs_helper_provider.py` (by hand, not in CI) |

- The real-Anki checks run on Kiso's harness (`tools/qt_smoke.py`): Anki starts
  offscreen in a throwaway profile with Tsunagi installed through its root
  `__init__.py`, server and all. `--screenshots DIR` keeps the images of the
  checks that take them.
- Set `TSUNAGI_GUI_PYTHON` and `TSUNAGI_BROWSER_PYTHON` to include the Qt
  tests and the browser check in a full `pytest` run. Tests for another Anki
  version still skip.
- Set `KISO_STRICT_ANKI_NOTICES=1` to fail on a deprecation notice Anki prints
  for Tsunagi's own call (CI does). Notices are always listed at the end of
  the run.
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
  checkout of it and run `python tools/check_parity.py`, adding `--clone DIR`
  if it isn't in `~/refs/anki-connect` (the weekly checks also do this). The
  routine tests only compare the [compatibility page](ankiconnect_parity.md)
  with Tsunagi's own actions.
- The broad comparison suite against upstream is archived in Git at `3c8e2dd`
  (`tests/test_upstream_*.py`, `tests/upstream_support.py`). To run it again,
  check out that revision separately and set `TSUNAGI_ANKICONNECT_CHECKOUT` to
  an upstream checkout. It isn't part of the maintained suite.
- Performance comparisons with AnkiConnect: [benchmarks](benchmarks.md).
  Profiling and past optimizations: [performance notes](performance_notes.md).

</details>

## CI

- [ci.yml](../.github/workflows/ci.yml) runs Kiso's add-on CI: ruff and the
  suite on both supported Anki versions, the Qt checks (`tools/qt_checks.sh`)
  on the newest, the build, and `pip-audit` on the bundled dependencies.
  Advisories that don't apply are listed with their reason in
  `pyproject.toml` (`audit_ignore`); any other one fails CI. So does a
  deprecation notice for Tsunagi's own call to an old Anki API (one raised
  inside Anki's own code is only listed).
- The same workflow tests the TypeScript client (`packages/typescript`): its
  own tests, including the shared conformance cases (`packages/spec/cases`,
  which every client runs; `packages/spec/behavior.md` says what a client does),
  then the built client against the real server (`tests/test_typescript_client.py`).
  The client's generated code (`src/generated.ts`: types and tables from
  `tests/snapshots/openapi.json` and `packages/spec/names.json`) and the
  cases' JSON (from `packages/spec/cases/source`) aren't in git: `npm run build`
  and `npm test` make them. An API change that breaks the client fails CI in
  the same push.
- The [Anki watch](../.github/workflows/anki-watch.yml) runs daily. When PyPI
  has an Anki release, beta or RC it hasn't tested, it runs the suite and Qt
  checks against it and records the result as an `anki-watch` issue (closed if
  everything passed).
- The [weekly checks](../.github/workflows/scheduled.yml) run `ci.yml` without
  a push, and compare upstream AnkiConnect's actions with the compatibility
  page. A failure or a change upstream opens a `weekly` issue, or comments on
  the one still open.

## Try changes in Anki

Copy the add-on into Anki's add-ons folder, then restart Anki once:

```sh
kiso sync --watch     # or KISO_ADDON_DIR=/path/to/Anki2/addons21/tsunagi kiso sync --watch
```

- `kiso sync` finds Anki's add-ons folder, copies the add-on, names it
  "Tsunagi (dev)" in Anki's list, and leaves a `DEV_WATCH` file there. A
  running Anki notices each copy and reloads Tsunagi within a second or two,
  waiting for requests in progress to finish first. `--watch` keeps copying
  as you edit.
- To reload by hand, run `import tsunagi; tsunagi.reload_addon()` in Anki's
  debug console (Ctrl+Shift+;).
- Changes to the root `__init__.py` or to `lib/` need an Anki restart.
  `--watch` doesn't copy `lib/` as you edit; run `kiso sync` again to copy it.
- Tsunagi logs to the console and to its file in Anki's log folder
  (`logs/addons/tsunagi/` in Anki's data folder).
- If another add-on has already loaded a different version of FastAPI,
  Starlette, pydantic or uvicorn, Tsunagi refuses to start and names it.
  `tools/check_vendor_clash.py` tests that in a real Anki.

## Package for AnkiWeb

Keep the version the same in `pyproject.toml` and `tsunagi/shared/version.py`,
and the client's major.minor (`packages/typescript/package.json` and
`package-lock.json`) the same as theirs (a test checks both), then run
`kiso build`. It writes:

| File | Purpose |
| --- | --- |
| `dist/tsunagi-<version>.ankiaddon` | Upload to [AnkiWeb](https://ankiweb.net/shared/addons/). Also works with **Install from file**. |
| `dist/tsunagi-<version>.ankiaddon.sha256` | Checksum for verifying the package. |

- The package holds the add-on's code, assets, bundled dependencies (vendored
  afresh from the lockfile), their licence notices, `README.md`, `LICENSE` and
  `config.md`. It leaves out your local `meta.json`, bytecode, tools, tests
  and the `docs/` folder.
- It checks the required files, JSON, ZIP and that nothing compiled slipped
  in before replacing an older package, and never uploads anything.
- `kiso build --offline` vendors from cached wheels.

## GitHub releases

Commit matching versions in the files above and push. Then either:

- open **Actions → Release → Run workflow** on `main` (it uses the declared
  version, so `0.1.0` becomes `v0.1.0`), or
- push a tag yourself: `git tag -a v0.1.0 -m "Tsunagi 0.1.0" && git push origin v0.1.0`.

The [Release workflow](../.github/workflows/release.yml):

1. runs CI: the suite on both Anki versions, the Qt checks, the
   dependency audit, the client's tests, and the test that the versions agree;
2. checks the tag matches `pyproject.toml`'s version (Kiso's `addon-release`);
3. builds the package with `kiso build`;
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
- Publishing a release also publishes its API reference to GitHub Pages
  (<https://mcgrizzz.github.io/Tsunagi/>), through the
  [API reference workflow](../.github/workflows/api-reference.yml): the local
  reference page, read-only, over that release's API description. Run the
  workflow by hand with a tag to publish an earlier release's. To see it
  locally: `python tools/build_api_reference.py --version 0.6.0`, then
  `python -m http.server -d site`. It needs **Settings → Pages → Source:
  GitHub Actions** once.
- Publishing a release also stages the TypeScript client on npm as
  `tsunagi-client`, through the
  [client publish workflow](../.github/workflows/client-publish.yml): the client
  at the release's tag, which must share its major.minor, tested first, with
  provenance. Approve the staged version on npmjs.com (2FA) to publish it.
  npm trusts that workflow file (trusted publishing, staged only), so it needs
  no token. A version npm already has is skipped, so bump the client when it
  changed.
- **A client-only release** ships client changes without an add-on release:
  bump the client's patch (`npm version 0.6.1 --no-git-tag-version` in
  `packages/typescript`), commit, push, then
  `git tag client-v0.6.1 && git push origin client-v0.6.1`. The same workflow
  stages it, but only if the API description at the tag matches the newest
  add-on release of the same major.minor apart from wording
  (`tools/client_api_matches.py`): a client that needs an API change waits for
  an add-on release.
- The browser check isn't part of CI; run it [before tagging](#tests).

## Code organization

- `tsunagi/http/`: API routes, the AnkiConnect endpoint and the HTTP middleware.
- `tsunagi/adapters/`: everything that talks to Anki, settings, and running
  operations.
- `tsunagi/web/`: the settings page, shown in a Qt dialog by
  `adapters/settings_page.py`.
- `tsunagi/shared/`: schemas, permissions, and shared query and error
  handling.
- `tools/`: the real-Anki checks, benchmarks, the settings screenshots and
  the lockfile of bundled libraries.

Prefer Anki's public APIs, and keep any direct database access in the adapter
layer. Account for the running Anki version. Use the existing operation
dispatch for threading and undo; GUI work belongs on Qt's main thread.
