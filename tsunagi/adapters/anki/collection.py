"""
Collection- and profile-level operations: sync, import/export, profile switching.

These act on the running application rather than on rows in the collection, so
they go through `call_on_main` rather than QueryOp/CollectionOp. Every aqt
import is function-local, so the module stays importable with no Qt present.
"""
import inspect
from typing import Any, Dict, List, Optional

from ...shared.errors import ResourceNotFoundError, ValidationError
from ..ops import as_query_op, call_on_main

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
    Switch profiles. False when there is no such profile.

    Closing a profile tears down `mw.col` underneath us, which is exactly what
    the profile_will_close hook and the 503 CollectionUnavailableError path
    exist for - requests arriving mid-switch get told to retry rather than
    touching a dead collection.
    """
    def _switch() -> bool:
        from aqt import mw
        from aqt.qt import QTimer

        if name not in mw.pm.profiles():
            return False
        if mw.pm.name == name:
            return True

        if mw.isVisible():
            mw.unloadProfileAndShowProfileManager()

            # Unloading can take a while (it may sync first), and loading the
            # next profile before that finishes corrupts the switch. Poll
            # instead of assuming, exactly as canonical does.
            def waiter() -> None:
                if mw.isVisible():
                    QTimer.singleShot(1000, waiter)
                else:
                    mw.pm.load(name)
                    mw.loadProfile()

            waiter()
        else:
            mw.pm.load(name)
            mw.loadProfile()
            mw.profileDiag.closeWithoutQuitting()
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


@as_query_op
def import_package(col: Any, path: str) -> Dict[str, Any]:
    """Import an .apkg, merging into the current collection."""
    from anki.import_export_pb2 import ImportAnkiPackageRequest

    result = col.import_anki_package(ImportAnkiPackageRequest(package_path=path))
    log = getattr(result, "log", None)
    return {
        "imported": len(getattr(log, "new", []) or []) if log else 0,
        "updated": len(getattr(log, "updated", []) or []) if log else 0,
    }
