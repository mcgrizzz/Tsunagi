#!/usr/bin/env python3
"""Time the ways a client can create a batch of mined notes with media.

Yomine's question: which request shape should it use to add a batch of mined
notes through the Tsunagi API? Each note is shaped like Yomine's real notes in
the testing profile: a `Kiku` note with Yomitan's fields (the text of a real
Yomine note), tags yomine and yomine::auto, word audio (~26 KB mp3, repeated
for ~10% of notes, same name and bytes), 0-2 dictionary images (~1 KB svg), a
sentence clip (~51 KB mp3) and a screenshot (~192 KB jpg). Every file has
random bytes, so nothing deduplicates by accident.

Variants, per batch size:
  A  the current Yomine sequence through the AnkiConnect Shim, per note
  B  one POST /v1/notes?include=cards per note, files attached
  C  one POST /v1/media array, then one POST /v1/notes array
  D  one POST /v1/notes array, each note's files attached
  C5/C10/C25, D5/D10/D25  C and D in chunks of that many notes

After the timings, `--checks` runs the behaviour checks (main-window
responsiveness, a bad attachment, repeated audio, a retry after 503, undo, a
duplicate). Notes go to a dedicated deck and files use a dedicated prefix;
both are removed after every trial, outside the timed section, and the run
checks at the end that the collection is back where it started. Deleted media
goes to Anki's media trash (Tools > Check Media > Empty Trash). Run on the
machine and disk where the testing profile lives.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import itertools
import json
import os
import platform
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.benchmark_workloads import save
from tools.connection_bench import Endpoint

DECK = "Tsunagi Benchmark"
MODEL = "Kiku"
TAGS = ["yomine", "yomine::auto"]
PREFIX = "tsunagi_bench_"
RUN = format(time.time_ns(), "x")[-8:]
# Every batch gets new names: deleted media sits in Anki's trash, and reusing
# a name there could make Anki rename the new file.
BATCH_IDS = itertools.count(1)
TIMEOUT = 300
SIZES = {"word_audio": 26 * 1024, "svg": 1024, "clip": 51 * 1024, "shot": 192 * 1024}
BATCHES = (1, 10, 25, 50, 100)
CHUNKS = (5, 10, 25)


class Http:
    """One new connection per request, like the other benchmarks; keeps every
    request's time and body size, and the status and headers of errors."""

    def __init__(self, endpoint, api_key, idempotency=False):
        self.endpoint, self.api_key, self.idempotency = endpoint, api_key, idempotency
        self.log = []   # (label, ms, request_bytes, status)
        self.keys = itertools.count(1)
        self.connect_retries = 0

    async def send(self, method, path, body=None, headers=None, label=""):
        data = b"" if body is None else json.dumps(body).encode()
        lines = [f"{method} {path} HTTP/1.1", f"Host: {self.endpoint.authority}", "Connection: close",
                 "Content-Type: application/json", f"Content-Length: {len(data)}"]
        if self.api_key:
            lines.append(f"X-API-Key: {self.api_key}")
        lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
        started = time.perf_counter()
        for attempt in range(4):
            # A connection that never opened sent nothing, so trying again is
            # safe; each retry is counted in the report.
            try:
                reader, writer = await asyncio.open_connection(self.endpoint.host, self.endpoint.port,
                                                               limit=2 ** 24)
                break
            except OSError:
                if attempt == 3:
                    raise
                self.connect_retries += 1
        try:
            writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + data)
            await writer.drain()
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), TIMEOUT)
            status_line, *rest = head[:-4].decode("latin-1").split("\r\n")
            status = int(status_line.split()[1])
            response_headers = {k.strip().lower(): v.strip() for k, v in (line.split(":", 1) for line in rest)}
            payload = json.loads(await reader.readexactly(int(response_headers["content-length"])))
        finally:
            writer.close()
        ms = (time.perf_counter() - started) * 1000
        self.log.append((label or f"{method} {path.split('?')[0]}", ms, len(data), status))
        return status, response_headers, payload, ms

    async def action(self, name, **params):
        status, _, payload, _ = await self.send("POST", "/", {"action": name, "version": 6, "params": params},
                                                label=name)
        if status != 200 or payload.get("error") is not None:
            raise RuntimeError(f"{name}: {status} {payload}")
        return payload["result"]

    async def rest(self, method, path, body=None, headers=None, **query):
        if query:
            path += "?" + urlencode(query)
        if self.idempotency and method == "POST" and path.split("?")[0] in ("/v1/notes", "/v1/media"):
            # What a client does with a big write: a key, and the same request
            # again after a 503 until the finished write's result comes back.
            headers = {**(headers or {}), "Idempotency-Key": f"bench-{RUN}-{next(self.keys)}"}
        status, _, payload, _ = await self.send(method, path, body, headers)
        while status == 503 and headers and "Idempotency-Key" in headers:
            status, _, payload, _ = await self.send(method, path, body, headers)
        if status >= 300:
            raise RuntimeError(f"{method} {path}: {status} {str(payload)[:300]}")
        return payload


# --------------------------------------------------------------------------
# The mined notes
# --------------------------------------------------------------------------

def b64(data):
    return base64.b64encode(data).decode()


def make_batch(template, size, seed):
    """`size` notes as Yomine would send them. Each has `files`: (role, name,
    bytes) with role word_audio, svg, clip or shot."""
    rnd = random.Random(seed)
    trial = next(BATCH_IDS)
    notes = []
    for i in range(size):
        word = f"tsunagibench{RUN}t{trial}n{i}語"
        files = []
        if notes and rnd.random() < 0.10:
            files.append(next(f for f in notes[rnd.randrange(len(notes))]["files"] if f[0] == "word_audio"))
        else:
            files.append(("word_audio", f"{PREFIX}yomitan_audio_{RUN}_{trial}_{i}.mp3",
                          os.urandom(SIZES["word_audio"])))
        for k in range(rnd.choice((0, 1, 1, 2))):
            files.append(("svg", f"{PREFIX}yomitan_dictionary_media_{RUN}_{trial}_{i}_{k}.svg",
                          os.urandom(SIZES["svg"])))
        for role, ext in (("clip", "mp3"), ("shot", "jpg")):
            files.append((role, f"{PREFIX}yomine-{RUN}{trial}-{i}.{ext}", os.urandom(SIZES[role])))
        fields = dict(template)
        fields["Expression"] = word
        # Dictionary images sit inside the glossary Yomitan builds.
        fields["Glossary"] = fields.get("Glossary", "") + "".join(
            f'<img src="{name}">' for role, name, _ in files if role == "svg")
        notes.append({"word": word, "fields": fields, "files": files})
    return notes


FIELD_OF = {"word_audio": "ExpressionAudio", "clip": "SentenceAudio", "shot": "Picture"}
MARKUP = {"word_audio": "[sound:{}]", "clip": "[sound:{}]", "shot": '<img src="{}">'}


def with_refs(note, roles, names=None):
    """Fields with references to the note's files of these roles (names: requested -> stored)."""
    fields = dict(note["fields"])
    for role, name, _ in note["files"]:
        if role in roles and role in FIELD_OF:
            fields[FIELD_OF[role]] = MARKUP[role].format((names or {}).get(name, name))
    return fields


def native_note(fields):
    return {"deckName": DECK, "modelName": MODEL, "fields": fields, "tags": TAGS, "allowDuplicate": False}


def attached(note):
    """A native note carrying its own files; references go where Yomine puts them."""
    body = native_note(dict(note["fields"]))
    for role, name, data in note["files"]:
        kind = "audio" if role in ("word_audio", "clip") else "picture"
        body.setdefault(kind, []).append({"filename": name, "data": b64(data),
                                          "fields": [FIELD_OF[role]] if role in FIELD_OF else []})
    return body


def unique_files(notes):
    seen, out = set(), []
    for note in notes:
        for f in note["files"]:
            if f[1] not in seen:
                seen.add(f[1])
                out.append(f)
    return out


# --------------------------------------------------------------------------
# Variants: each returns the created note IDs; `first` records when the
# first note existed (ms since the start).
# --------------------------------------------------------------------------

async def variant_a(h, notes, t0, first):
    ids = []
    for note in notes:
        for role, name, data in note["files"]:
            if role in ("word_audio", "svg"):
                await h.action("storeMediaFile", filename=name, data=b64(data))
        nid = await h.action("addNote", note={
            "deckName": DECK, "modelName": MODEL, "tags": TAGS,
            "fields": with_refs(note, {"word_audio"}),
            "options": {"allowDuplicate": False}})
        first.setdefault("ms", (time.perf_counter() - t0) * 1000)
        ids.append(nid)
        await h.action("getActiveProfile")
        await h.action("notesInfo", notes=[nid])
        # Today's Yomine names the clip and screenshot after the note ID.
        refs = {}
        for role, _name, data in note["files"]:
            if role in ("clip", "shot"):
                stored = await h.action("storeMediaFile", filename=f"{PREFIX}yomine-{nid}.{'mp3' if role == 'clip' else 'jpg'}",
                                        data=b64(data))
                refs[FIELD_OF[role]] = MARKUP[role].format(stored)
        await h.action("updateNoteFields", note={"id": nid, "fields": refs})
    return ids


async def variant_b(h, notes, t0, first):
    ids = []
    for note in notes:
        answer = await h.rest("POST", "/v1/notes", attached(note), include="cards")
        if answer["failed"]:
            raise RuntimeError(f"B failed: {answer['failed']}")
        first.setdefault("ms", (time.perf_counter() - t0) * 1000)
        ids += [c["id"] for c in answer["created"]]
    return ids


async def chunked(h, notes, t0, first, chunk, separate_media):
    ids = []
    for start in range(0, len(notes), chunk):
        part = notes[start:start + chunk]
        if separate_media:
            files = unique_files(part)
            stored = await h.rest("POST", "/v1/media", [{"filename": n, "data": b64(d)} for _, n, d in files])
            if stored["failed"]:
                raise RuntimeError(f"media failed: {stored['failed']}")
            names = {files[c["index"]][1]: c["filename"] for c in stored["created"]}
            body = [native_note(with_refs(n, {"word_audio", "clip", "shot"}, names)) for n in part]
        else:
            body = [attached(n) for n in part]
        answer = await h.rest("POST", "/v1/notes", body)
        if answer["failed"]:
            raise RuntimeError(f"notes failed: {answer['failed']}")
        first.setdefault("ms", (time.perf_counter() - t0) * 1000)
        ids += [c["id"] for c in answer["created"]]
    return ids


def variants(batches=BATCHES, chunks=CHUNKS):
    out = {"A": (variant_a, batches), "B": (variant_b, batches)}
    for label, media in (("C", True), ("D", False)):
        out[label] = (lambda h, n, t0, f, m=media: chunked(h, n, t0, f, len(n), m), batches)
        for chunk in chunks:
            out[f"{label}{chunk}"] = (lambda h, n, t0, f, c=chunk, m=media: chunked(h, n, t0, f, c, m),
                                     tuple(b for b in batches if b > chunk))
    return out


# --------------------------------------------------------------------------
# Setup, cleanup
# --------------------------------------------------------------------------

async def cleanup(h):
    ids = await h.action("findNotes", query=f'"deck:{DECK}"')
    if ids:
        await h.action("deleteNotes", notes=ids)
    for name in await h.action("getMediaFilesNames", pattern=f"{PREFIX}*"):
        await h.action("deleteMediaFile", filename=name)


async def leftovers(h):
    return {"deck_notes": len(await h.action("findNotes", query=f'"deck:{DECK}"')),
            "media": len(await h.action("getMediaFilesNames", pattern=f"{PREFIX}*"))}


async def template_fields(h):
    """The text of the most recent real Yomine note, without its media references."""
    ids = await h.action("findNotes", query=f'tag:yomine "note:{MODEL}"')
    note = (await h.action("notesInfo", notes=[max(ids)]))[0]
    fields = {k: v["value"] for k, v in note["fields"].items()}
    for k in ("ExpressionAudio", "SentenceAudio", "Picture"):
        fields[k] = ""
    return fields


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, round(p / 100 * (len(values) - 1)))]


# --------------------------------------------------------------------------
# Behaviour checks
# --------------------------------------------------------------------------

async def probe_main_thread(h, stop, samples):
    """GET /v1/profiles runs on Anki's main (Qt) thread; GET /v1/decks is a collection read."""
    while not stop.is_set():
        for path, key in (("/v1/profiles", "main"), ("/v1/decks?select=id", "read")):
            _, _, _, ms = await h.send("GET", path, label="probe")
            samples[key].append(ms)
        await asyncio.sleep(0.1)


async def check_responsive(h, template, report):
    out = {}
    for label, separate in (("D100", False), ("C100", True)):
        notes = make_batch(template, 100, 900 + separate)
        idle = {"main": [], "read": []}
        stop = asyncio.Event()
        task = asyncio.create_task(probe_main_thread(Http(h.endpoint, h.api_key), stop, idle))
        await asyncio.sleep(2)
        stop.set()
        await task
        busy = {"main": [], "read": []}
        stop = asyncio.Event()
        task = asyncio.create_task(probe_main_thread(Http(h.endpoint, h.api_key), stop, busy))
        started = time.perf_counter()
        await chunked(h, notes, started, {}, 100, separate)
        request_ms = (time.perf_counter() - started) * 1000
        stop.set()
        await task
        out[label] = {"request_ms": request_ms,
                      **{f"{k}_idle_max_ms": max(v) for k, v in idle.items()},
                      **{f"{k}_busy_{s}_ms": f(busy[k]) for k in busy
                         for s, f in (("p50", statistics.median), ("max", max))},
                      "probes_during": len(busy["main"])}
        await cleanup(h)
    report["checks"]["main_window_responsive"] = out


async def check_bad_attachment(h, template, report):
    notes = make_batch(template, 5, 910)
    body = [attached(n) for n in notes]
    body[2]["audio"][0]["data"] = "!!! not base64 !!!"
    answer = await h.rest("POST", "/v1/notes", body)
    stored = set(await h.action("getMediaFilesNames", pattern=f"{PREFIX}*"))
    others = [f[1] for i, n in enumerate(notes) if i != 2 for f in n["files"]]
    bad_note = [f[1] for f in notes[2]["files"]]
    report["checks"]["bad_attachment"] = {
        "failed": answer["failed"], "created_indexes": [c["index"] for c in answer["created"]],
        "other_notes_files_stored": all(n in stored for n in others),
        "bad_notes_files_stored": [n for n in bad_note if n in stored]}
    await cleanup(h)


async def check_repeated_audio(h, template, report):
    shared = make_batch(template, 1, 920)[0]["files"][0]
    media = await h.rest("POST", "/v1/media", [{"filename": shared[1], "data": b64(shared[2])}] * 3)
    copies = await h.action("getMediaFilesNames", pattern=shared[1].rsplit(".", 1)[0] + "*")
    await cleanup(h)
    notes = make_batch(template, 3, 921)
    shared = notes[0]["files"][0]
    notes[1]["files"][0] = notes[2]["files"][0] = shared
    answer = await h.rest("POST", "/v1/notes", [attached(n) for n in notes])
    info = await h.action("notesInfo", notes=[c["id"] for c in answer["created"]])
    report["checks"]["repeated_word_audio"] = {
        "media_array": [{k: c[k] for k in ("index", "filename", "renamed")} for c in media["created"]],
        "media_array_files_after": copies,
        "notes_array_created": len(answer["created"]), "notes_array_failed": answer["failed"],
        "notes_array_audio_refs": [n["fields"]["ExpressionAudio"]["value"] for n in info],
        "notes_array_files_after": await h.action("getMediaFilesNames",
                                                  pattern=shared[1].rsplit(".", 1)[0] + "*")}
    await cleanup(h)


async def check_retry_after_503(h, template, report, size):
    # Notes without files: the note writes are what take the time, and a
    # request this large with every file attached would be hundreds of MB.
    notes = make_batch(template, size, 930)
    body = [native_note(with_refs(n, {"word_audio", "clip", "shot"})) for n in notes]
    key = f"bench-{RUN}-{size}"
    first_status, first_headers, first_payload, first_ms = await h.send(
        "POST", "/v1/notes", body, {"Idempotency-Key": key}, label="retry-first")
    attempts = []
    status, headers, payload = first_status, first_headers, first_payload
    while status == 503 and len(attempts) < 20:
        status, headers, payload, ms = await h.send("POST", "/v1/notes", body, {"Idempotency-Key": key},
                                                    label="retry")
        attempts.append({"status": status, "ms": ms, "replayed": headers.get("idempotent-replayed")})
    in_deck = len(await h.action("findNotes", query=f'"deck:{DECK}"'))
    report["checks"]["retry_after_503"] = {
        "notes": size, "first": {"status": first_status, "ms": first_ms,
                                 "error": first_payload.get("error") if first_status != 200 else None},
        "retries": attempts,
        "final_created": len(payload.get("created", [])) if status == 200 else None,
        "final_failed": payload.get("failed") if status == 200 else None,
        "notes_in_deck": in_deck}
    await cleanup(h)


async def check_undo(h, template, report):
    notes = make_batch(template, 10, 940)
    answer = await h.rest("POST", "/v1/notes", [attached(n) for n in notes])
    names = [f[1] for n in notes for f in n["files"]]
    before = len(await h.action("findNotes", query=f'"deck:{DECK}"'))
    await h.rest("POST", "/v1/gui:undo")
    await asyncio.sleep(1)
    after = len(await h.action("findNotes", query=f'"deck:{DECK}"'))
    stored = set(await h.action("getMediaFilesNames", pattern=f"{PREFIX}*"))
    report["checks"]["undo"] = {"created": len(answer["created"]), "notes_before_undo": before,
                                "notes_after_one_undo": after,
                                "media_kept_after_undo": sum(n in stored for n in set(names)),
                                "media_total": len(set(names))}
    await cleanup(h)


async def check_duplicate(h, template, report):
    notes = make_batch(template, 4, 950)
    existing = (await h.action("notesInfo", notes=[max(await h.action("findNotes", query=f'tag:yomine "note:{MODEL}"'))]))[0]
    notes[1]["fields"]["Expression"] = existing["fields"]["Expression"]["value"]   # an existing note
    notes[3]["fields"]["Expression"] = notes[0]["fields"]["Expression"]           # earlier in this request
    answer = await h.rest("POST", "/v1/notes", [attached(n) for n in notes])
    stored = set(await h.action("getMediaFilesNames", pattern=f"{PREFIX}*"))
    report["checks"]["duplicate"] = {
        "failed": answer["failed"], "created_indexes": [c["index"] for c in answer["created"]],
        "existing_note_id": existing["noteId"],
        "duplicate_files_stored": {i: [f[1] for f in notes[i]["files"] if f[1] in stored] for i in (1, 3)}}
    await cleanup(h)


# --------------------------------------------------------------------------

async def run(args, report):
    h = Http(Endpoint.parse(args.url), os.environ.get(args.api_key_env), args.idempotency_keys)
    if await h.action("getActiveProfile") != args.profile:
        raise RuntimeError(f"Expected testing profile {args.profile!r}")
    if any((await leftovers(h)).values()):
        raise RuntimeError("Benchmark deck or media already present; clean up first")
    report["baseline_notes"] = len(await h.action("findNotes", query=""))
    template = await template_fields(h)
    report["template_field_bytes"] = sum(len(v.encode()) for v in template.values())
    await h.action("createDeck", deck=DECK)
    selected = {} if args.only_checks else variants(tuple(args.batches or BATCHES), tuple(args.chunks))
    if args.variants:
        selected = {k: v for k, v in selected.items() if k in args.variants}
    try:
        # One untimed warm-up of each code path.
        for label in ("A", "B", "C", "D"):
            if label in selected:
                await selected[label][0](h, make_batch(template, 2, 0), time.perf_counter(), {})
                await cleanup(h)
        # Interleaved: each round runs every configuration once, in a new
        # random order, so anything that drifts during the run (Anki's own
        # background work, the media folder growing) spreads over all of them.
        configs = [(label, size) for label, (_fn, batches) in selected.items() for size in batches]
        trials = {c: [] for c in configs}
        for trial in range(1, args.repeats + 1 if configs else 1):
            random.Random(trial).shuffle(configs)
            for label, size in configs:
                notes = make_batch(template, size, trial)
                h.log, h.connect_retries = [], 0
                first = {}
                t0 = time.perf_counter()
                ids = await selected[label][0](h, notes, t0, first)
                total = (time.perf_counter() - t0) * 1000
                log = list(h.log)
                if len(ids) != size or len(set(ids)) != size:
                    raise RuntimeError(f"{label} {size}: created {len(ids)} notes")
                await cleanup(h)
                trials[(label, size)].append({
                    "round": trial, "total_ms": total, "first_note_ms": first.get("ms"),
                    "requests": len(log), "request_ms": [e[1] for e in log],
                    "request_bytes": [e[2] for e in log], "request_labels": [e[0] for e in log],
                    "statuses": sorted({e[3] for e in log}), "timeouts_503": sum(e[3] == 503 for e in log),
                    "connect_retries": h.connect_retries})
            report["trials_by_config"] = {f"{k[0]}:{k[1]}": v for k, v in trials.items()}
            save(args.output, report)
            print(f"round {trial} of {args.repeats} done", flush=True)
        for label, (_fn, batches) in selected.items():
            for size in batches:
                ts = trials[(label, size)]
                all_ms = [ms for t in ts for ms in t["request_ms"]]
                entry = {"variant": label, "notes": size, "trials": ts,
                         "total_ms_median": statistics.median(t["total_ms"] for t in ts),
                         "first_note_ms_median": statistics.median(t["first_note_ms"] for t in ts),
                         "requests": ts[0]["requests"],
                         "request_p50_ms": pct(all_ms, 50), "request_p95_ms": pct(all_ms, 95),
                         "request_max_ms": max(all_ms),
                         "peak_request_bytes": max(b for t in ts for b in t["request_bytes"]),
                         "near_timeout": max(all_ms) > 10_000,
                         "timeouts_503": sum(t["timeouts_503"] for t in ts),
                         "connect_retries": sum(t["connect_retries"] for t in ts)}
                report["results"].append(entry)
                print(f"{label:>4} {size:>4} notes: total {entry['total_ms_median']:8.0f} ms, first "
                      f"{entry['first_note_ms_median']:7.0f} ms, {entry['requests']:4} requests, p50 "
                      f"{entry['request_p50_ms']:6.0f} p95 {entry['request_p95_ms']:6.0f} max "
                      f"{entry['request_max_ms']:6.0f} ms, peak body {entry['peak_request_bytes'] / 1e6:5.1f} MB"
                      f"{', 503s ' + str(entry['timeouts_503']) if entry['timeouts_503'] else ''}"
                      f"{', connect retries ' + str(entry['connect_retries']) if entry['connect_retries'] else ''}",
                      flush=True)
        save(args.output, report)
        if args.checks:
            for check in (check_responsive, check_bad_attachment, check_repeated_audio, check_undo,
                          check_duplicate):
                await check(h, template, report)
                save(args.output, report)
                print(check.__name__, json.dumps(report["checks"][list(report["checks"])[-1]])[:600], flush=True)
        if args.retry_notes:
            await check_retry_after_503(h, template, report, args.retry_notes)
            save(args.output, report)
            print("retry_after_503", json.dumps(report["checks"]["retry_after_503"])[:800], flush=True)
    finally:
        await cleanup(h)
        await h.action("deleteDecks", decks=[DECK], cardsToo=True)
        report["leftovers"] = await leftovers(h)
        report["final_notes"] = len(await h.action("findNotes", query=""))
        if any(report["leftovers"].values()) or report["final_notes"] != report["baseline_notes"]:
            raise RuntimeError(f"Cleanup incomplete: {report['leftovers']}, notes {report['final_notes']} "
                               f"vs baseline {report['baseline_notes']}")
    report["completed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True)
    parser.add_argument("--profile", required=True, help="Exact testing profile name; checked first")
    parser.add_argument("--variants", nargs="*", help="A, B, C, D, or C/D with a chunk size (C25, D100)")
    parser.add_argument("--batches", nargs="*", type=int, help=f"Notes per batch (default {BATCHES})")
    parser.add_argument("--chunks", nargs="*", type=int, default=list(CHUNKS),
                        help=f"Chunk sizes for the chunked C and D variants (default {CHUNKS})")
    parser.add_argument("--idempotency-keys", action="store_true",
                        help="Send an Idempotency-Key with native writes and retry them after a 503")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--checks", action="store_true", help="Run the behaviour checks after the timings")
    parser.add_argument("--only-checks", action="store_true",
                        help="Skip the timings: run only --checks and/or --retry-notes")
    parser.add_argument("--retry-notes", type=int, default=0,
                        help="Also send one notes array this large (no files) with an Idempotency-Key "
                             "and retry it after any 503; pick a size that takes over op_timeout_seconds")
    parser.add_argument("--api-key-env", default="TSUNAGI_BENCH_API_KEY")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new path")
    report = {"schema": 1, "started_at": datetime.now(timezone.utc).isoformat(),
              "mode": "mining_batches", "python": sys.version, "platform": platform.platform(),
              "config": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()
                         if k != "api_key_env"},
              "file_sizes": SIZES, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "results": [], "checks": {}, "completed": False}
    try:
        asyncio.run(run(args, report))
    except (Exception, KeyboardInterrupt) as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(args.output, report)


if __name__ == "__main__":
    main()
