"""
Collection- and profile-level operations: sync, import/export, profile switching.

Application actions go through `call_on_main`; collection reads and imports use
QueryOp/CollectionOp. Every aqt import is function-local, so the module stays
importable with no Qt present.
"""
import inspect
from typing import Any, Dict, List, Optional

from ...shared.errors import ResourceNotFoundError, ValidationError
from ..ops import ValueWithChanges, as_collection_op, as_query_op, call_on_main

SYNC_AUTH_MISSING = "sync: auth not configured"


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


def sync_collection() -> Dict[str, Any]:
    """
    Run a collection sync. Raises when no sync account is configured.

    DEVIATION: canonical finishes with `mw.onSync()`, which no longer exists
    (it is `on_sync_button_clicked` now, and it starts a *second* sync). The
    sync itself is done by the time this returns.
    """
    def _sync() -> Dict[str, Any]:
        from aqt import mw

        auth = mw.pm.sync_auth()
        if not auth:
            raise ValidationError(SYNC_AUTH_MISSING)
        out = mw.col.sync_collection(auth, mw.pm.media_syncing_enabled())
        accepted = (out.NO_CHANGES, out.NORMAL_SYNC)
        if out.required not in accepted:
            raise ValidationError(
                f"Sync status {out.required} not one of {list(accepted)} - the "
                "collection needs a full upload or download, which Anki must do "
                "itself. See SyncCollectionResponse.ChangesRequired."
            )
        return {"status": int(out.required),
                "server_message": getattr(out, "server_message", "")}

    return call_on_main(_sync, timeout=None)   # a sync can take a long time


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
    """Drop cached state so the next read sees what is on disk."""
    col.reset()
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
    """
    Export one deck to an .apkg.

    Anki's export_anki_package() signature CHANGED across the versions we
    support - 23.10 takes with_scheduling/with_media/legacy_support directly,
    newer builds take an ExportAnkiPackageOptions protobuf - so pick by
    signature. Canonical sidesteps this by using the deprecated
    AnkiPackageExporter, which we would rather not depend on.
    """
    from anki.collection import DeckIdLimit

    deck = col.decks.by_name(deck_name)
    if deck is None:
        raise ResourceNotFoundError("Deck", deck_name)

    limit = DeckIdLimit(int(deck["id"]))
    params = inspect.signature(col.export_anki_package).parameters
    if "options" in params:
        from anki.import_export_pb2 import ExportAnkiPackageOptions

        col.export_anki_package(
            out_path=path, limit=limit,
            options=ExportAnkiPackageOptions(
                with_scheduling=with_scheduling, with_media=with_media,
                legacy=False),
        )
    else:
        col.export_anki_package(
            out_path=path, limit=limit, with_scheduling=with_scheduling,
            with_media=with_media, legacy_support=False)
    return True


_IMPORT_UPDATE_CONDITIONS = {"if_newer": 0, "always": 1, "never": 2}
_IMPORT_OPTIONS = (
    "with_scheduling", "with_deck_configs", "merge_notetypes",
    "update_notes", "update_notetypes",
)


@as_query_op
def import_preferences(col: Any) -> Dict[str, Any]:
    """Read the same saved choices used by Anki's package import screen."""
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


@as_query_op
def collection_capabilities(col: Any) -> Dict[str, Any]:
    """Read the setting and backend support from the same collection operation."""
    from .fsrs import capabilities

    return {
        **capabilities(col._backend),
        "enabled": bool(col.get_config("fsrs", default=False)),
    }
