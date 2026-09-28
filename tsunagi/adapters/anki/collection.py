"""
Collection- and profile-level operations: sync, import/export, profile switching.

Application actions go through `call_on_main`; collection reads and imports use
QueryOp/CollectionOp. Every aqt import is function-local, so the module stays
importable with no Qt present.
"""
import threading
from typing import Any, Callable, Dict, List, Optional

from ...shared.errors import (
    AnkiBusyError,
    CollectionUnavailableError,
    ResourceNotFoundError,
    SyncConflictError,
    SyncFailedError,
    ValidationError,
)
from ..ops import (
    ValueWithChanges,
    as_collection_op,
    as_query_op,
    call_on_main,
    query_op_call,
)

SYNC_AUTH_MISSING = "sync: auth not configured"

# Set by the sync_will_start/sync_did_finish hooks in the add-on root.
syncing = False


def collection_state(probe_timeout: float = 1.0) -> str:
    """
    ready, syncing, closed or busy. Reads the flags off the main thread, then
    probes with a trivial query, which waits on both the main thread and the
    backend's collection lock. A modal dialog blocks neither (checked live on
    26.09 with the Import file picker open).
    """
    from aqt import mw
    if syncing:
        return "syncing"
    col = mw.col
    if col is None or col.db is None:  # a full sync closes the db
        return "closed"
    try:
        query_op_call(lambda c: c.db.scalar("select 1"), timeout=probe_timeout)
    except AnkiBusyError:
        return "busy"
    except CollectionUnavailableError:
        return "closed"
    return "ready"


def list_profiles() -> List[str]:
    def _read() -> List[str]:
        from aqt import mw
        return list(mw.pm.profiles())
    return call_on_main(_read)


def active_profile() -> Optional[str]:
    def _read() -> Optional[str]:
        from aqt import mw
        return mw.pm.name
    return call_on_main(_read)


def load_profile(name: str) -> bool:
    """
    Schedule a profile switch. False when there is no such profile.

    Release the main-thread caller before unloading: profile_will_close stops
    the HTTP server and waits for its in-flight requests, including this one.
    The caller can then finish while shutdown drains the old server. Clients
    should reconnect and check the active profile after the switch.
    """
    def _switch() -> bool:
        from aqt import mw
        from aqt.qt import QTimer

        if name not in mw.pm.profiles():
            return False
        if mw.pm.name == name:
            return True

        def load_target() -> None:
            mw.pm.load(name)
            mw.loadProfile()
            mw.profileDiag.closeWithoutQuitting()

        def begin_switch() -> None:
            if mw.isVisible():
                mw.unloadProfileAndShowProfileManager()

                # Unloading may sync first. Do not load the target until
                # the old profile has finished closing.
                def waiter() -> None:
                    if mw.isVisible():
                        QTimer.singleShot(1000, waiter)
                    else:
                        load_target()

                waiter()
            else:
                load_target()

        QTimer.singleShot(0, begin_switch)
        return True

    return call_on_main(_switch)


FULL_SYNC_REQUIRED = ("The collection needs a full sync (upload or download), which Anki "
                      "asks you about. Click Sync in Anki to choose.")


def redraw_main_screen(mw: Any) -> None:
    """
    Redraw the current screen now, as after Anki's own Sync button. When Anki
    is not the focused window (a sync or add-on action came from another
    program), mw.reset() only dims the page (fade_out_webview) and waits for
    focus to redraw it. Ordinary API writes keep Anki's behaviour.
    """
    screen = {"review": mw.reviewer, "overview": mw.overview,
              "deckBrowser": mw.deckBrowser}.get(mw.state)
    if screen is not None:
        screen.refresh_if_needed()
    mw.fade_in_webview()


def start_sync(on_done: Callable[[Optional[Dict[str, Any]], Optional[Exception]], None]) -> None:
    """
    Anki's own sync path (mw._sync_collection_and_media) without its dialogs
    (backlog 10.1, R17): sync_will_start and sync_did_finish fire, so add-ons
    such as FSRS Helper react as to the Sync button; media syncs; the window
    refreshes; the network work runs in the background, not on the main
    thread. Where Anki would ask the user (a full sync) or show a warning,
    this reports to `on_done(None, error)` instead. Main thread. Raises
    at once when no sync account is set up.
    """
    from aqt import gui_hooks, mw

    auth = mw.pm.sync_auth()
    if not auth:
        raise ValidationError(SYNC_AUTH_MISSING)

    def run() -> Any:
        # Pre-flight: never start a sync that would end in Anki's full-sync prompt.
        status = mw.col.sync_status(auth)
        if status.required == status.FULL_SYNC:
            raise SyncConflictError(FULL_SYNC_REQUIRED)
        return mw.col.sync_collection(auth, mw.pm.media_syncing_enabled())

    def finished(fut: Any) -> None:
        result, error = None, None
        try:
            mw.col._load_scheduler()  # the scheduler version may have changed
            out = fut.result()
            mw.pm.set_host_number(out.host_number)
            if out.new_endpoint:
                mw.pm.set_current_sync_url(out.new_endpoint)
            if out.required not in (out.NO_CHANGES, out.NORMAL_SYNC):
                raise SyncConflictError(FULL_SYNC_REQUIRED)
            result = {"status": int(out.required), "server_message": out.server_message}
        except SyncConflictError as exc:
            error = exc
        except Exception as exc:
            if getattr(getattr(exc, "kind", None), "name", "") == "AUTH":
                mw.pm.clear_sync_auth()  # as Anki does: the login is no longer valid
            error = SyncFailedError(f"Sync failed: {exc}")
        mw.col.models._clear_cache()
        gui_hooks.sync_did_finish()
        mw.reset()
        redraw_main_screen(mw)
        if error is None:
            mw.media_syncer.start_monitoring()
        on_done(result, error)

    gui_hooks.sync_will_start()
    mw.taskman.run_in_background(run, finished)


def sync_collection() -> Dict[str, Any]:
    """Sync and wait for the result, however long it takes (AnkiConnect's
    `sync`). Raises what start_sync reports."""
    done = threading.Event()
    box: Dict[str, Any] = {}

    def on_done(result: Optional[Dict[str, Any]], error: Optional[Exception]) -> None:
        box.update(result=result, error=error)
        done.set()

    call_on_main(start_sync, on_done)
    done.wait()
    if box["error"] is not None:
        raise box["error"]
    return box["result"]


@as_query_op
def collection_meta(col: Any) -> Dict[str, Any]:
    """
    Collection-wide facts. The FSRS flag is the rslib BoolKey::Fsrs config
    entry (stored under "fsrs", absent = disabled) - the deck-options UI
    hosts the toggle, but it switches the scheduler for the whole collection.
    """
    from anki.buildinfo import version as anki_version

    return {
        "fsrs": bool(col.get_config("fsrs", default=False)),
        "anki_version": anki_version,
    }


@as_query_op
def reload_collection(col: Any) -> bool:
    """Retain the legacy no-op while still requiring an open collection.

    Collection.reset() is already a no-op in our oldest supported Anki. Do not
    replace it with cache clearing or reopening: that would discard live state.
    """
    return True


def check_database() -> bool:
    def _check() -> bool:
        from aqt import mw
        mw.onCheckDB()
        return True
    return call_on_main(_check)


@as_query_op
def export_package(col: Any, deck_name: str, path: str,
                   with_scheduling: bool = False, with_media: bool = True) -> bool:
    """Export one deck in Anki's current package format."""
    deck = col.decks.by_name(deck_name)
    if deck is None:
        raise ResourceNotFoundError("Deck", deck_name)

    _export_package(col, int(deck["id"]), path,
                    with_scheduling=with_scheduling, with_media=with_media)
    return True


def _export_package(col: Any, deck_id: int, path: str, *,
                    with_scheduling: bool, with_media: bool,
                    legacy: bool = False,
                    with_deck_configs: Optional[bool] = None) -> None:
    """One package export for native and compatibility calls."""
    from anki.collection import DeckIdLimit
    from anki.import_export_pb2 import ExportAnkiPackageOptions

    options = ExportAnkiPackageOptions(
        with_scheduling=with_scheduling, with_media=with_media, legacy=legacy)
    if with_deck_configs is not None:
        options.with_deck_configs = with_deck_configs
    col.export_anki_package(out_path=path, limit=DeckIdLimit(deck_id), options=options)


_IMPORT_UPDATE_CONDITIONS = {"if_newer": 0, "always": 1, "never": 2}
_IMPORT_OPTIONS = (
    "with_scheduling", "with_deck_configs", "merge_notetypes",
    "update_notes", "update_notetypes",
)


@as_query_op
def import_preferences(col: Any) -> Dict[str, Any]:
    """Read the same saved choices used by Anki's package import screen."""
    return _read_import_preferences(col)


def _read_import_preferences(col: Any) -> Dict[str, Any]:
    options = col._backend.get_import_anki_package_presets()
    supported = options.DESCRIPTOR.fields_by_name
    conditions = {value: name for name, value in _IMPORT_UPDATE_CONDITIONS.items()}
    values = {}
    for name in _IMPORT_OPTIONS:
        if name in supported:
            value = getattr(options, name)
            values[name] = conditions[value] if name.startswith("update_") else value
    return {
        "options": values,
        "unsupported_options": [name for name in _IMPORT_OPTIONS if name not in supported],
    }


@as_collection_op
def import_package(col: Any, path: str, *,
                   with_scheduling: Optional[bool] = None,
                   with_deck_configs: Optional[bool] = None,
                   merge_notetypes: Optional[bool] = None,
                   update_notes: Optional[str] = None,
                   update_notetypes: Optional[str] = None) -> ValueWithChanges:
    """Apply explicit overrides to saved choices and publish import changes."""
    from anki.import_export_pb2 import ImportAnkiPackageRequest

    options = col._backend.get_import_anki_package_presets()
    overrides = {
        "with_scheduling": with_scheduling,
        "with_deck_configs": with_deck_configs,
        "merge_notetypes": merge_notetypes,
        "update_notes": update_notes,
        "update_notetypes": update_notetypes,
    }
    for name, value in overrides.items():
        if value is None:
            continue
        if name not in options.DESCRIPTOR.fields_by_name:
            raise ValidationError(f"Import option '{name}' is not supported by this Anki version")
        if name.startswith("update_"):
            value = _IMPORT_UPDATE_CONDITIONS[value]
        setattr(options, name, value)

    result = col.import_anki_package(ImportAnkiPackageRequest(package_path=path, options=options))
    log = getattr(result, "log", None)
    return ValueWithChanges({
        "imported": len(getattr(log, "new", []) or []) if log else 0,
        "updated": len(getattr(log, "updated", []) or []) if log else 0,
    }, result.changes)

def submit_import_package(path, *, on_started, on_success, on_failure, **options):
    """Submit exactly one import through the same write/notification path."""
    from ..ops import collection_op_run_async

    def run(col):
        on_started()
        return import_package.__wrapped__(col, path, **options)

    collection_op_run_async(run, on_success=on_success, on_failure=on_failure)



@as_query_op
def collection_capabilities(col: Any) -> Dict[str, Any]:
    """Read native support and collection settings without running mutations or jobs."""
    from .fsrs import capabilities

    import_available = hasattr(col._backend, "get_import_anki_package_presets")
    import_options = (_read_import_preferences(col)["unsupported_options"]
                      if import_available else list(_IMPORT_OPTIONS))
    return {
        "fsrs": {**capabilities(col._backend), "enabled": bool(col.get_config("fsrs", default=False))},
        # Present on every supported Anki; kept in the report for clients.
        "card_decay": True,
        "deck_desired_retention": True,
        "import_available": import_available,
        "unsupported_import_options": import_options,
    }
