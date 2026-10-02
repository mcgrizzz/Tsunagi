"""
Tsunagi's running part, as Kiso's Addon builds it (the root __init__.py): the
server, and the Anki hooks feeding its event stream. A reload tears it down
and builds it from the new code, so changes here need no Anki restart.

Every hook goes through Kiso's Subscriptions, which guards it: Anki removes a
subscriber that raises, so one bad publish would otherwise silence the event
stream for the session.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ._kiso.hooks import Subscriptions
from .log import log


class Feature:
    def __init__(self, mw: Any, addon_module: str, vendor_refusal: Callable[[], Optional[str]]):
        """`vendor_refusal()` says why the server must not start (another add-on
        loaded a different web stack), or None."""
        from aqt import gui_hooks

        self.mw = mw
        self.addon_module = addon_module
        self.vendor_refusal = vendor_refusal
        self.subs = Subscriptions(log)
        add = self.subs.add
        # Start once a profile (and its collection) is open; stop before it
        # closes so the port is free for a restart or profile switch.
        add(gui_hooks.profile_did_open, self._profile_open, "Profile open")
        add(gui_hooks.profile_will_close, self._profile_close, "Profile close")
        # A hook this Anki lacks costs a feature, not the boot.
        add(getattr(gui_hooks, "operation_did_execute", None), self._op_executed, "Event: operation")
        add(getattr(gui_hooks, "reviewer_did_answer_card", None), self._card_answered, "Event: review")
        add(getattr(gui_hooks, "sync_will_start", None), self._sync_start, "Event: sync start")
        add(getattr(gui_hooks, "sync_did_finish", None), self._sync_finish, "Event: sync finish")
        add(getattr(gui_hooks, "day_did_change", None), self._day_change, "Event: day change")
        if mw.col is not None:
            self._start_server()   # a reload, with a profile already open

    def teardown(self) -> Callable[[], bool]:
        """Unhook and stop the server without waiting: its last requests may need
        Anki's main thread. Returns whether it has stopped (the port is free)."""
        from .app import begin_stop

        self.subs.remove_all()
        return begin_stop()

    # ---------- profile ----------

    def _profile_open(self) -> None:
        from ._kiso.logs import attach_to_anki
        from .log import set_level

        try:  # first, so a refused or failed start is in Anki's add-on log too
            attach_to_anki(self.addon_module, logging.getLogger(self.addon_module), also=("uvicorn",))
            set_level((self.mw.addonManager.getConfig(self.addon_module) or {}).get("log_level", "warning"))
        except Exception:
            log.exception("Could not attach Anki's add-on log")
        if self._start_server():
            from .adapters.dialogs import offer_ankiconnect_import
            offer_ankiconnect_import()   # one-time; no-op if AnkiConnect absent

    def _profile_close(self) -> None:
        from .app import stop_server
        stop_server("profile_closed")

    def _start_server(self) -> bool:
        """Start the server unless another add-on's web stack would break it."""
        message = self.vendor_refusal()
        if message:
            log.error(message)
            from aqt.utils import tooltip
            tooltip(message, period=15000)
            return False
        from .app import start_server
        start_server(self.mw)
        return True

    # ---------- event-stream feeders ----------

    def _op_executed(self, changes, handler=None) -> None:
        from .adapters.events import ApiOp, broker, dispatch_op
        if not broker.has_subscribers():
            return
        # OpChanges carries flags but no identity; for Tsunagi's own writes
        # the undo label ("Suspend", "Update Note", ...) names the op that
        # just completed. Anki-side changes go to the change scanner.
        label = None
        try:
            if isinstance(handler, ApiOp) and self.mw.col is not None:
                label = self.mw.col.undo_status().undo or None
        except Exception:
            label = None
        dispatch_op(changes, handler, label=label)

    def _card_answered(self, reviewer, card, ease) -> None:
        from .adapters.events import publish_review
        publish_review(card, ease)

    def _sync_start(self) -> None:
        from .adapters.anki import collection
        from .adapters.events import publish_sync
        collection.syncing = True
        publish_sync("started")

    def _sync_finish(self) -> None:
        from .adapters.anki import collection
        from .adapters.events import publish_sync
        collection.syncing = False
        publish_sync("finished")

    def _day_change(self) -> None:
        from .adapters.events import broker
        if broker.scanner is not None:
            broker.scanner.mark_counts()
