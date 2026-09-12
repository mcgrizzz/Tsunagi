# Developing Tsunagi

[← Back to the README](../README.md) · [Yomitan walkthrough](api_recipes.md)

Commands below run from the repository root. To build a client that uses Tsunagi,
start with the API recipes instead.

## Environment and build

Clone the repository with Git and enter its directory:

```sh
git clone https://github.com/mcgrizzz/Tsunagi.git
cd Tsunagi
```

Use a virtual environment from the repository root. This follows the CI setup:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install pytest ruff "httpx<0.28" anki
python tools/build_addon.py
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell. On Python
3.9, install `anki==23.10` in place of `anki`; newer Anki packages need a newer
Python. The repository’s [CI configuration](../.github/workflows/ci.yml) records its
version matrix.

The build vendors dependencies from [tools/requirements.lock.txt](../tools/requirements.lock.txt)
into `lib/shared`, then packages the add-on into `dist`. It rebuilds `lib/` and
replaces the archive for the current version after validation. Anki itself is a test
dependency and is never bundled. After the wheel cache is populated,
`python tools/build_addon.py --offline` builds using cached wheels.

## Tests

Build first so the tests can import the vendored runtime dependencies, then run:

```sh
ruff check .
python -m pytest -q
```

Backend tests use temporary Anki collections. Optional Qt checks need a separate
interpreter with `aqt` and its Qt dependencies. For example, point the settings
check at that interpreter:

```sh
TSUNAGI_GUI_PYTHON=/path/to/qt-env/bin/python \
  python -m pytest -q tests/test_settings_dialog_qt.py
```

The Scalar browser check needs a separate environment with Playwright and Chromium:

```sh
python -m pip install playwright
python -m playwright install chromium
```

Set `TSUNAGI_BROWSER_PYTHON` to that environment's Python executable. Set both
`TSUNAGI_GUI_PYTHON` and `TSUNAGI_BROWSER_PYTHON` when running the full suite to
include the optional Qt and browser checks. Tests for behavior specific to another
Anki version will still skip.

`tools/check_browser_startup.py`, `tools/check_add_cards.py` and other targeted
Qt checks can also run with the Qt interpreter. The shared Qt smoke harness creates
a temporary profile. Use disposable profiles for development and GUI experiments.
Offscreen checks do not establish Windows foreground-window behavior. Finish with
the [manual release checks](manual_testing.md) for the desktop and real clients.

<details>
<summary>Archived AnkiConnect parity checks</summary>

The broad AnkiConnect comparison suite is archived in Git at `eea649e`:
`tests/test_upstream_differential.py`, `tests/test_upstream_decks.py`,
`tests/test_upstream_permissions.py` and `tests/upstream_support.py`. It established
compatibility against pinned upstream code; routine tests retain focused Tsunagi
regressions and action-inventory checks. For a specific renewed comparison, recover
that revision in a separate checkout and set `TSUNAGI_ANKICONNECT_CHECKOUT` to the
upstream checkout. The broad audit is not part of the maintained test suite.

</details>

## Sync to a development installation

Install a built package first. To copy source changes into a chosen development
add-on folder:

```sh
python tools/dev_sync.py --dest /path/to/Anki2/addons21/tsunagi
```

Add `--watch` to keep copying source edits, or `--full` after rebuilding dependencies
to copy `lib/` too. Copying files and reloading the running add-on are separate steps:
restart Anki, or use the development reload options documented in [config.md](../config.md).
Changes to the root `__init__.py` or bundled dependencies require a full restart.

## Package for AnkiWeb

Keep the release version in `tools/version.py`, `tsunagi/shared/version.py` and
`pyproject.toml` aligned, then run from the repository root:

```sh
python tools/build_addon.py
```

The script prints the upload path and creates two files:

| File | Purpose |
| --- | --- |
| `dist/tsunagi-<version>.ankiaddon` | Upload this file to [AnkiWeb](https://ankiweb.net/shared/addons/). It also works with **Install from file**. |
| `dist/tsunagi-<version>.ankiaddon.sha256` | SHA-256 checksum for verifying the package. |

The package includes runtime code, assets, bundled dependencies and license notices.
It excludes local `meta.json`, bytecode, development tools, tests and handoff docs.
The script checks required files, JSON and ZIP integrity before replacing a previous
package. It does not upload anything. Use `--offline` to reuse cached dependencies
or `--refresh` to download them again; these options cannot be combined.

## GitHub releases

To prepare a release on GitHub, commit matching versions in `tools/version.py`,
`tsunagi/shared/version.py` and `pyproject.toml`, then push your changes. Open
**Actions → Release → Run workflow**, select **main**, and run it. The workflow
uses the declared version (for example, `0.1.0` becomes `v0.1.0`).

You can also start the [Release workflow](../.github/workflows/release.yml) by
pushing a version tag yourself:

```sh
git tag -a v0.1.0 -m "Tsunagi 0.1.0"
git push origin v0.1.0
```

The workflow checks all three version declarations, runs the existing CI matrix
on Anki 23.10 and current Anki, then builds the package. A tag-triggered run also
checks that the tag matches the declared version. After validation, a manual run
creates the version tag at the exact commit it tested, if the tag doesn't exist. It
creates a **draft GitHub release** with generated release notes, the `.ankiaddon`
and its checksum attached. Review the draft and publish it when ready. AnkiWeb
upload remains a separate step using the same `.ankiaddon` file.

To retry the same release, rerun its workflow or manually run **Release** against the existing tag
(for example, `gh workflow run release.yml --ref v0.1.0`). Reruns update assets on
an existing draft; published releases are left intact. An existing tag must point
to the tested commit: running from a newer `main` commit requires a new version,
not reusing the old tag. The workflow uses GitHub's
built-in token, so no additional release secret is needed. Optional Qt/browser
checks remain separate from the CI matrix; run them [before tagging](#tests).

## Code organization

- `tsunagi/http/` contains native routes, the AnkiConnect shim and HTTP middleware.
- `tsunagi/adapters/` integrates with Anki, including settings and operation dispatch.
- `tsunagi/shared/` contains schemas and shared query/error handling.
- `tools/` contains packaging, development sync and targeted checks.

Prefer Anki’s public APIs. Keep unavoidable database access in the adapter layer,
and account for the running Anki version. Use existing operation dispatch for
threading and undo behavior; GUI work belongs on the Qt main thread.
