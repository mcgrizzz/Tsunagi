"""Real Anki backend; the same fake Qt operations used by the test suite."""
from __future__ import annotations

import cProfile
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

try:
    import resource
except ImportError:  # Windows has no stdlib getrusage().
    resource = None

ROOT = Path(__file__).resolve().parents[2]


def bootstrap():
    if not (ROOT / "lib/shared/fastapi").is_dir():
        raise RuntimeError("build vendored dependencies first: python3 tools/build_addon.py --offline")
    for path in (ROOT / "lib/shared", ROOT, ROOT / "tests"):
        sys.path.insert(0, str(path))
    import anki.collection  # noqa: F401 (initialize before Anki's circular imports)
    import anki.lang
    anki.lang.set_lang("en_US")
    from fakes.anki_stubs import install
    install()


@contextmanager
def collection(path):
    from anki.collection import Collection
    from fakes.anki_stubs import mw
    col = Collection(str(path))
    mw.col = col
    try:
        yield col
    finally:
        col.close()
        mw.col = None
        os.chdir(ROOT)


@contextmanager
def endpoint(implementation, checkout):
    if implementation == "upstream":
        from tools.upstream_reference import load_reference
        reference = load_reference(checkout)
        yield lambda method, path, body, params: reference.http_raw_request(body, method=method)
    else:
        from fastapi.testclient import TestClient

        from tsunagi.adapters.config import DEFAULTS
        from tsunagi.adapters.settings import settings
        from tsunagi.app import app
        settings.configure(dict(DEFAULTS), persist=None)
        with TestClient(app) as client:
            yield lambda method, path, body, params: client.request(
                method, path, content=body, params=params, headers={"Content-Type": "application/json"})


class Requests:
    def __init__(self, send):
        self.send = send
        self.actions = []

    def __call__(self, action, params):
        start = time.perf_counter()
        response = self.send("POST", "/", json.dumps({"action": action, "version": 6, "params": params}).encode(), None)
        value = response.json()
        self.actions.append({"action": action, "milliseconds": (time.perf_counter() - start) * 1000,
                             "response_bytes": len(response.content)})
        if response.status_code != 200 or value.get("error"):
            raise RuntimeError(f"{action}: HTTP {response.status_code}: {value.get('error')}")
        return value["result"]

    def native(self, method, path, payload):
        start = time.perf_counter()
        body = json.dumps(payload).encode() if method != "GET" else None
        response = self.send(method, path, body, payload if method == "GET" else None)
        value = response.json()
        self.actions.append({"action": f"{method} {path}",
                             "milliseconds": (time.perf_counter() - start) * 1000,
                             "response_bytes": len(response.content)})
        if response.status_code not in (200, 201):
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {value}")
        return value


def profile_counts(profiler):
    backend, dispatch = Counter(), Counter()
    functions = []
    for entry in profiler.getstats():
        code = entry.code
        if isinstance(code, str):
            continue
        filename = code.co_filename.replace("\\", "/")
        functions.append({"function": f"{filename}:{code.co_firstlineno}:{code.co_name}",
                          "calls": entry.callcount, "self_ms": entry.inlinetime * 1000,
                          "cumulative_ms": entry.totaltime * 1000})
        if "/anki/" in filename and Path(filename).name.startswith("_backend"):
            backend[code.co_name] += entry.callcount
        if filename.endswith("/fakes/anki_stubs.py") and code.co_name == "run_in_background":
            dispatch[code.co_qualname] += entry.callcount
    return {"backend": dict(sorted(backend.items())), "fake_qt_dispatch": dict(dispatch),
            "top_self": sorted(functions, key=lambda row: row["self_ms"], reverse=True)[:30],
            "top_cumulative": sorted(functions, key=lambda row: row["cumulative_ms"], reverse=True)[:30]}


def run_worker(config):
    from .workloads import Workload
    bootstrap()
    workload = Workload(config["case"], config["implementation"])
    samples = []
    fingerprints = set()
    with endpoint(config["implementation"], config["checkout"]) as send:
        for trial in range(config["repeats"] + 2):
            with tempfile.TemporaryDirectory(prefix="trial-", dir=config["scratch"]) as scratch:
                target = Path(scratch) / "profile"
                shutil.copytree(config["seed"], target)
                with collection(target / "collection.anki2") as col:
                    request = Requests(send)
                    if trial == config["repeats"] + 1:
                        # Counters run separately so profiling does not distort samples.
                        profiler = cProfile.Profile()
                        result = profiler.runcall(workload.run, request)
                        counts = profile_counts(profiler)
                    else:
                        start = time.perf_counter()
                        result = workload.run(request)
                        samples.append({"phase": "first" if trial == 0 else "repeated",
                                        "milliseconds": (time.perf_counter() - start) * 1000,
                                        "actions": request.actions})
                    fingerprints.add(workload.verify(col, result))
                    del result
                    # Keep verified progress if the outer process limit expires.
                    Path(config["output"] + ".progress").write_text(json.dumps({
                        "samples": samples, "verified_trials": trial + 1,
                        "fingerprints": sorted(fingerprints), "completed": False,
                    }))
    assert len(fingerprints) == 1, "results changed between equivalent restored trials"
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else None
    return {"implementation": config["implementation"], "samples": samples,
            "fingerprint": fingerprints.pop(), "profile_calls": counts,
            "worker_peak_rss_mib": (peak / (1024 ** 2 if sys.platform == "darwin" else 1024)
                                    if peak is not None else None),
            "verified": True}
