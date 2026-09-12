#!/usr/bin/env python3
"""Measure real Anki task dispatch with an idle, offscreen Qt event loop.

Uses a disposable collection, real TaskManager/QueryOp/CollectionOp and progress
widgets. The minimal host has no browser/editor repaint or undo-menu cost.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import tempfile
import threading
import time
import traceback
import weakref
from importlib.metadata import version
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("/tmp/tsunagi-dispatch.json"))
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.count < 1 or args.repeats < 2:
        parser.error("count must be positive and repeats at least 2")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "lib/shared"), str(root)]
    import anki.collection
    import anki.lang
    import aqt
    from aqt.progress import ProgressManager
    from aqt.qt import QApplication, QTimer, QWidget
    from aqt.taskman import TaskManager

    anki.lang.set_lang("en_US")
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    class Host(QWidget):
        def __init__(self, col):
            super().__init__()
            self.col, self.app = col, app
            self.background_ops = 0
            self.undo_updates = 0
            self.taskman = TaskManager(self)
            self.progress = ProgressManager(self)

        def weakref(self):
            return weakref.proxy(self)

        def _increase_background_ops(self):
            self.background_ops += 1

        def _decrease_background_ops(self):
            self.background_ops -= 1

        def update_undo_actions(self):
            self.undo_updates += 1

    report = {"anki": version("anki"), "aqt": version("aqt"), "python": sys.version,
              "pyqt": version("PyQt6"),
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "mode": "real_qt_dispatch_minimal_host", "count": args.count,
              "limits": ["Idle offscreen Qt event loop; no full Anki window or other add-ons.",
                         "Real collection thread, QueryOp/CollectionOp and progress widgets.",
                         "No browser repaint, undo-menu rendering, API sockets or mutation latency."],
              "cases": [], "completed": False}
    with tempfile.TemporaryDirectory(prefix="tsunagi-dispatch-") as folder:
        col = anki.collection.Collection(str(Path(folder) / "collection.anki2"))
        host = Host(col)
        aqt.mw = host
        from tsunagi.adapters import ops

        failure = []

        def worker():
            try:
                for kind in ("query", "collection"):
                    for batched in (False, True):
                        samples = []
                        for trial in range(args.repeats + 1):
                            bodies = []

                            def body(collection, count=args.count if batched else 1,
                                     operation=kind, timings=bodies):
                                assert collection is col
                                assert threading.current_thread() is not threading.main_thread()
                                start = time.perf_counter()
                                value = None
                                for _ in range(count):
                                    value = (collection.note_count() if operation == "query"
                                             else anki.collection.OpChanges())
                                timings.append((time.perf_counter() - start) * 1000)
                                return value

                            start = time.perf_counter()
                            for _ in range(1 if batched else args.count):
                                if kind == "query":
                                    assert ops.query_op_call(body) == 0
                                else:
                                    ops.collection_op_call(body)
                            elapsed = (time.perf_counter() - start) * 1000
                            samples.append({"phase": "first" if trial == 0 else "repeated",
                                            "total_ms": elapsed, "body_ms": sum(bodies),
                                            "dispatch_and_wrapper_ms": elapsed - sum(bodies)})
                        repeated = samples[1:]
                        report["cases"].append({"kind": kind, "batched": batched,
                            "operations": 1 if batched else args.count, "samples": samples,
                            "median_ms": statistics.median(s["total_ms"] for s in repeated),
                            "median_overhead_ms": statistics.median(s["dispatch_and_wrapper_ms"] for s in repeated)})
                report["completed"] = True
            except BaseException:
                failure.append(traceback.format_exc())
            finally:
                host.taskman.run_on_main(app.quit)

        thread = threading.Thread(target=worker)
        QTimer.singleShot(0, thread.start)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda: (failure.append("Qt benchmark timed out"), app.quit()))
        watchdog.start(120000)
        app.exec()
        thread.join(timeout=20)
        host.taskman._collection_executor.shutdown(wait=True)
        host.taskman._no_collection_executor.shutdown(wait=True)
        assert host.background_ops == 0
        assert col.note_count() == 0 and col.card_count() == 0
        col.close()
        aqt.mw = None
        if failure:
            raise RuntimeError("\n".join(failure))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for case in report["cases"]:
        print(f"{case['kind']} operations={case['operations']}: {case['median_ms']:.3f} ms "
              f"({case['median_overhead_ms']:.3f} ms outside the body)")
    print(args.output)


if __name__ == "__main__":
    main()
