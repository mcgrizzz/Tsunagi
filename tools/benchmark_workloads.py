#!/usr/bin/env python3
"""Time real client goals against a running Anki testing profile.

Each workload is one goal taken from a real AnkiConnect client, written the way
that client does it for AnkiConnect and the AnkiConnect Shim, and the natural
way for the Tsunagi API. Every trial's result is normalized and hashed, so runs
of different implementations can be checked for the same answer.

Write workloads add notes and media to a dedicated deck, tag and filename
prefix, and delete them after every trial, outside the timed section. The run
refuses to start if any of those already exist and checks at the end that the
collection's note count and the benchmark's media are back where they started.
Run one implementation at a time; restart Anki when switching between upstream
AnkiConnect and Tsunagi.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.connection_bench import Endpoint, action_request, exchange, wire_request

DECK = "Tsunagi Benchmark"
TAG = "tsunagi-benchmark"
PREFIX = "tsunagi_bench_"
MODEL = "Kiku+"
TERM_FIELD = "Expression"
BENCH_SEARCH = f'"deck:{DECK}"'
TIMEOUT = 120


class Client:
    """Sequential requests, one new connection each, counting requests and bytes."""

    def __init__(self, endpoint, api_key):
        self.endpoint, self.api_key = endpoint, api_key
        self.requests = self.response_bytes = 0

    async def _send(self, wire):
        result = await exchange(self.endpoint, wire, TIMEOUT, return_payload=True)
        self.requests += 1
        self.response_bytes += result.get("response_bytes", 0)
        if result["outcome"] != "ok":
            raise RuntimeError(f"Request failed: {({k: v for k, v in result.items() if k != 'payload'})}")
        return result["payload"]

    async def action(self, name, **params):
        return (await self._send(action_request(self.endpoint, name, params, self.api_key)))["result"]

    async def rest(self, method, path, body=None, **query):
        if query:
            path += "?" + urlencode(query)
        return await self._send(wire_request(self.endpoint, path, body, self.api_key, method))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def fields_of(note):
    """notesInfo fields ({name: {value, order}}) or Tsunagi fields ([{name, value}])."""
    if isinstance(note["fields"], dict):
        return {name: item["value"] for name, item in note["fields"].items()}
    return {item["name"]: item["value"] for item in note["fields"]}


RUN = format(time.time_ns(), "x")


def media(kind, trial, size):
    # Unique names: Anki moves deleted media to its trash, and reusing a name
    # would make later stores pay for the name collision. Same bytes every trial.
    data = hashlib.sha256(kind.encode()).digest() * (size // 32)
    return f"{PREFIX}{RUN}_{trial}_{kind}.{'mp3' if kind == 'audio' else 'jpg'}", data


def placeholders(value, names):
    """Replace this trial's generated media names so results compare across trials."""
    text = json.dumps(value, ensure_ascii=False)
    for index, name in enumerate(names):
        text = text.replace(name, f"<media {index}>")
    return json.loads(text)


# --------------------------------------------------------------------------
# Workloads. `ankiconnect` serves upstream and the Shim; `tsunagi` the /v1 API.
# Each returns a normalized result. `setup`/`cleanup` are never timed.
# --------------------------------------------------------------------------

class Workload:
    name = ""
    source = ""
    writes = False

    async def setup(self, c, ctx, trial):
        pass

    async def cleanup(self, c, ctx, trial):
        pass


class LookupDuplicates(Workload):
    name = "lookup_duplicates"
    source = ("Yomitan: duplicate check for a popup's entries (backend.js, anki-connect.js findNoteIds); "
              "default settings: same note type")
    options = {}

    def candidates(self, ctx):
        return ctx["existing_terms"] + [f"tsunagibench{i}語" for i in range(10)]

    async def ankiconnect(self, c, ctx, trial):
        words = self.candidates(ctx)
        notes = [{"deckName": "Mining", "modelName": MODEL, "fields": {TERM_FIELD: w},
                  "options": {"allowDuplicate": False, "duplicateScope": "collection",
                              **({"duplicateScopeOptions": self.options} if self.options else {})}}
                 for w in words]
        checks = await c.action("canAddNotesWithErrorDetail", notes=notes)
        dup = [w for w, r in zip(words, checks)
               if r.get("error") and "cannot create note because it is a duplicate" in r["error"]]
        ids = {w: [] for w in dup}
        if dup:
            queries = [f'"{TERM_FIELD.lower()}:{w}"' for w in dup]
            union = await c.action("findNotes", query=" or ".join(f"({q})" for q in queries))
            if union:
                found = await c.action("multi", actions=[
                    {"action": "findNotes", "params": {"query": f"nid:{','.join(map(str, union))} ({q})"}}
                    for q in queries])
                ids = {w: r["result"] if isinstance(r, dict) else r for w, r in zip(dup, found)}
        return {w: {"duplicate": w in ids, "ids": sorted(ids.get(w, []))} for w in words}

    async def tsunagi(self, c, ctx, trial):
        words = self.candidates(ctx)
        body = {"notes": [{"deckName": "Mining", "modelName": MODEL, "fields": {TERM_FIELD: w},
                           **({"duplicateScopeOptions": self.options} if self.options else {})}
                          for w in words]}
        results = (await c.rest("POST", "/v1/notes:check", body))["results"]
        return {w: {"duplicate": r["state"] == "duplicate",
                    "ids": sorted(r.get("duplicate_note_ids") or [])} for w, r in zip(words, results)}


class LookupDuplicatesAllModels(LookupDuplicates):
    name = "lookup_duplicates_all_models"
    source = ("Yomitan: the same check with 'Check for duplicates across all models' on "
              "(duplicateScopeOptions.checkAllModels)")
    options = {"deckName": None, "checkChildren": False, "checkAllModels": True}


class MineWithMedia(Workload):
    name = "mine_with_media"
    source = "Yomitan / asbplayer / Yomine: add a mined note with audio and a picture"
    writes = True

    def note(self, audio, image):
        return {"deckName": DECK, "modelName": MODEL, "tags": [TAG],
                "fields": {TERM_FIELD: "tsunagibench mined",
                           "Sentence": "benchmark sentence",
                           "ExpressionAudio": f"[sound:{audio}]",
                           "Picture": f'<img src="{image}">'}}

    async def ankiconnect(self, c, ctx, trial):
        (audio, a), (image, i) = media("audio", trial, 48 * 1024), media("image", trial, 64 * 1024)
        for name, data in ((audio, a), (image, i)):
            await c.action("storeMediaFile", filename=name, data=base64.b64encode(data).decode())
        note = self.note(audio, image)
        note["options"] = {"allowDuplicate": True}
        ctx["created"] = [await c.action("addNote", note=note)]
        ctx["media"] = [audio, image]

    async def tsunagi(self, c, ctx, trial):
        (audio, a), (image, i) = media("audio", trial, 48 * 1024), media("image", trial, 64 * 1024)
        stored = await c.rest("POST", "/v1/media", [
            {"filename": audio, "data": base64.b64encode(a).decode()},
            {"filename": image, "data": base64.b64encode(i).decode()}])
        names = [item["filename"] for item in sorted(stored["created"], key=lambda x: x["index"])]
        note = self.note(*names)
        note["allowDuplicate"] = True
        created = await c.rest("POST", "/v1/notes", note)
        ctx["created"] = [item["id"] for item in created["created"]]
        ctx["media"] = names

    async def verify(self, c, ctx, trial):
        info = (await c.action("notesInfo", notes=ctx["created"]))[0]
        stored = {name: await c.action("retrieveMediaFile", filename=name) for name in ctx["media"]}
        return placeholders({"fields": {k: v for k, v in fields_of(info).items() if v},
                             "tags": info["tags"], "model": info["modelName"],
                             "media": {name: hashlib.sha256(base64.b64decode(data)).hexdigest()
                                       for name, data in stored.items()}}, ctx["media"])

    async def cleanup(self, c, ctx, trial):
        await delete_created(c, ctx)


class UpdateLastMined(Workload):
    name = "update_last_mined"
    source = "asbplayer: attach a screenshot to the most recently added note (anki.ts _updateNoteFields)"
    writes = True

    async def setup(self, c, ctx, trial):
        ctx["created"] = [await c.action("addNote", note={
            "deckName": DECK, "modelName": MODEL, "tags": [TAG],
            "fields": {TERM_FIELD: "tsunagibench update", "Sentence": "before update"},
            "options": {"allowDuplicate": True}})]
        ctx["media"] = []

    async def ankiconnect(self, c, ctx, trial):
        ids = await c.action("findNotes", query=f"added:1 {BENCH_SEARCH}")
        note = (await c.action("notesInfo", notes=[max(ids)]))[0]
        name, data = media("shot", trial, 64 * 1024)
        stored = await c.action("storeMediaFile", filename=name, data=base64.b64encode(data).decode())
        ctx["media"] = [stored]
        await c.action("updateNoteFields", note={"id": note["noteId"], "fields": {
            "Picture": fields_of(note)["Picture"] + f'<img src="{stored}">'}})
        await c.action("addTags", notes=[note["noteId"]], tags=f"{TAG}-updated")

    async def tsunagi(self, c, ctx, trial):
        page = await c.rest("GET", "/v1/notes", search=f"added:1 {BENCH_SEARCH}", select="id,fields")
        note = max(page["items"], key=lambda n: n["id"])
        name, data = media("shot", trial, 64 * 1024)
        stored = (await c.rest("POST", "/v1/media", {"filename": name,
                                                      "data": base64.b64encode(data).decode()}))
        filename = stored["created"][0]["filename"]
        ctx["media"] = [filename]
        await c.rest("PATCH", f"/v1/notes/{note['id']}", {
            "fields": {"Picture": fields_of(note)["Picture"] + f'<img src="{filename}">'},
            "add_tags": [f"{TAG}-updated"]})

    async def verify(self, c, ctx, trial):
        info = (await c.action("notesInfo", notes=ctx["created"]))[0]
        return placeholders({"fields": {k: v for k, v in fields_of(info).items() if v},
                             "tags": sorted(info["tags"])}, ctx["media"])

    async def cleanup(self, c, ctx, trial):
        await delete_created(c, ctx)


class KnownWordsSnapshot(Workload):
    name = "known_words_snapshot"
    source = "Yomine: known-word refresh (state.rs): every note, then the first card's latest interval"

    async def ankiconnect(self, c, ctx, trial):
        ids = await c.action("findNotes", query="deck:*")
        notes = await c.action("notesInfo", notes=ids)
        firsts = [n["cards"][0] for n in notes if n["cards"]]
        intervals = dict(zip(firsts, await c.action("getIntervals", cards=firsts)))
        return {str(n["noteId"]): {"model": n["modelName"], "fields": fields_of(n),
                                   "interval": intervals.get(n["cards"][0]) if n["cards"] else None}
                for n in notes}

    async def tsunagi(self, c, ctx, trial):
        notes = (await c.rest("GET", "/v1/notes", search="deck:*",
                              select="id,model_name,fields,cards"))["items"]
        # getIntervals' meaning: 0 for a new card, else the latest review log interval.
        new = set((await c.rest("GET", "/v1/cards", search="deck:* is:new", select="id"))["items"])
        latest = {}
        for review in (await c.rest("GET", "/v1/reviews", search="deck:*",
                                    select="id,card_id,interval"))["items"]:
            if review["id"] >= latest.get(review["card_id"], (0, None))[0]:
                latest[review["card_id"]] = (review["id"], review["interval"])

        def interval(card):
            return 0 if card in new else latest[card][1]
        return {str(n["id"]): {"model": n["model_name"], "fields": fields_of(n),
                               "interval": interval(n["cards"][0]) if n["cards"] else None}
                for n in notes}


class MinedWordsCache(Workload):
    name = "mined_words_cache"
    source = ("asbplayer: first build of the mined-words cache (dictionary-db-anki.ts): notes, card "
              "details in batches, suspension and status searches; word field Expression, sentence "
              "field Sentence, deck Mining, mature cutoff 21")
    query = '("deck:Mining") ("Expression:_*" OR "Sentence:_*")'
    mature = 21

    async def statuses(self, find, card_ids):
        # asbplayer's _processAnkiCardStatuses: the first matching search wins, and
        # it stops once every card has a status. prop:s needs FSRS; else prop:ivl.
        q, grad, remaining, status = self.query, -(-self.mature // 2), set(card_ids), {}

        def assign(ids, label):
            for cid in ids:
                if cid in remaining:
                    status[cid] = label
                    remaining.discard(cid)

        assign(await find(f"is:new ({q})"), "unknown")
        if remaining:
            assign(await find(f"is:learn ({q})"), "learning")
        if remaining:
            props = ["prop:s", "prop:ivl"][0 if await find(f"prop:s>=0 ({q})") else 1:]
            for prop in props:
                for label, cond in (("graduated", f"{prop}<{grad}"),
                                    ("young", f"{prop}>={grad} {prop}<{self.mature}"),
                                    ("mature", f"{prop}>={self.mature}")):
                    assign(await find(f"-is:new -is:learn {cond} ({q})"), label)
                    if not remaining:
                        return status
        return status

    @staticmethod
    def result(notes, cards, suspended, status):
        out = {}
        for note in notes:
            fields = {k: v.strip() for k, v in note["fields"].items() if v.strip()}
            modified = max([note["mod"]] + [cards[cid]["mod"] for cid in note["cards"]])
            for cid in note["cards"]:
                out[str(cid)] = {"note": note["id"], "fields": fields, "modified": modified,
                                 "suspended": bool(suspended[cid]), "deck": cards[cid]["deck"],
                                 "model": cards[cid]["model"], "due": cards[cid]["due"],
                                 "status": status.get(cid)}
        return out

    async def ankiconnect(self, c, ctx, trial):
        note_ids = await c.action("findNotes", query=self.query)
        infos = []
        for i in range(0, len(note_ids), 100):
            infos += await c.action("notesInfo", notes=note_ids[i:i + 100])
        card_ids = [cid for n in infos for cid in n["cards"]]
        mods = {m["cardId"]: m["mod"] for m in await c.action("cardsModTime", cards=card_ids)}
        cards = {}
        for i in range(0, len(card_ids), 10):   # every card is new to an empty cache
            for info in await c.action("cardsInfo", cards=card_ids[i:i + 10]):
                cards[info["cardId"]] = {"deck": info["deckName"], "model": info["modelName"],
                                         "due": info["due"], "mod": mods[info["cardId"]]}
        suspended = dict(zip(card_ids, await c.action("areSuspended", cards=card_ids)))

        async def find(query):
            return await c.action("findCards", query=query)
        notes = [{"id": n["noteId"], "mod": n["mod"], "cards": n["cards"],
                  "fields": {k: v["value"] for k, v in n["fields"].items()}} for n in infos]
        return self.result(notes, cards, suspended, await self.statuses(find, card_ids))

    async def tsunagi(self, c, ctx, trial):
        notes = (await c.rest("GET", "/v1/notes", search=self.query, select="id,mod,cards,fields"))["items"]
        card_ids = [cid for n in notes for cid in n["cards"]]
        rows = (await c.rest("POST", "/v1/cards/query", {
            "search": "cid:" + ",".join(map(str, card_ids)),
            "select": "id,deck_name,model_name,due,mod,suspended"}))["items"]
        cards = {r["id"]: {"deck": r["deck_name"], "model": r["model_name"], "due": r["due"],
                           "mod": r["mod"]} for r in rows}

        async def find(query):
            return (await c.rest("GET", "/v1/cards", search=query, select="id"))["items"]
        notes = [{"id": n["id"], "mod": n["mod"], "cards": n["cards"],
                  "fields": {f["name"]: f["value"] for f in n["fields"]}} for n in notes]
        return self.result(notes, cards, {r["id"]: r["suspended"] for r in rows},
                           await self.statuses(find, card_ids))


class ChangePoll(Workload):
    name = "change_poll"
    source = "asbplayer: 10-second poll for edited or reviewed cards"
    query = f'(edited:1 OR rated:1) -{BENCH_SEARCH}'

    async def ankiconnect(self, c, ctx, trial):
        return sorted(await c.action("findCards", query=self.query))

    async def tsunagi(self, c, ctx, trial):
        return sorted((await c.rest("GET", "/v1/cards", search=self.query, select="id"))["items"])


class NoteTypeFields(Workload):
    name = "note_type_fields"
    source = "Obsidian_to_Anki: setup reads every note type's field names, one request each"

    async def ankiconnect(self, c, ctx, trial):
        names = await c.action("modelNames")
        return {name: await c.action("modelFieldNames", modelName=name) for name in names}

    async def tsunagi(self, c, ctx, trial):
        models = (await c.rest("GET", "/v1/models", select="name,fields[].name"))["items"]
        return {m["name"]: m["fields"] for m in models}


REVIEW_FIELDS = "id,card_id,ease,interval,last_interval,factor,time_ms,type"


def review_rows(rows):
    """Tsunagi review rows as sorted [card, id, ease, ivl, last ivl, factor, time, type]."""
    return sorted([r["card_id"], r["id"], r["ease"], r["interval"], r["last_interval"], r["factor"],
                   r["time_ms"], r["type"]] for r in rows)


class ReviewHistory(Workload):
    name = "review_history"
    source = ("anki-mcp-server: review statistics for one deck (review-stats.tool.ts), "
              "one cardReviews request; the deck's own cards, not its subdecks")
    deck = "Kaishi 1.5k"

    async def ankiconnect(self, c, ctx, trial):
        rows = await c.action("cardReviews", deck=self.deck, startID=0)
        # cardReviews tuples: id, card, usn, ease, ivl, last ivl, factor, time, type.
        return sorted([r[1], r[0], r[3], r[4], r[5], r[6], r[7], r[8]] for r in rows)

    async def tsunagi(self, c, ctx, trial):
        search = f'"deck:{self.deck}" -"deck:{self.deck}::*"'
        return review_rows((await c.rest("GET", "/v1/reviews", search=search, select=REVIEW_FIELDS))["items"])


class ReviewHistoryAll(Workload):
    name = "review_history_all"
    source = ("anki-mcp-server: review statistics for all decks (review-stats.tool.ts "
              "fetchCollectionReviews): every card, then one getReviewsOfCards")

    async def ankiconnect(self, c, ctx, trial):
        cards = await c.action("findCards", query="deck:*")
        by_card = await c.action("getReviewsOfCards", cards=cards)
        return sorted([int(cid), r["id"], r["ease"], r["ivl"], r["lastIvl"], r["factor"], r["time"], r["type"]]
                      for cid, reviews in by_card.items() for r in reviews)

    async def tsunagi(self, c, ctx, trial):
        return review_rows((await c.rest("GET", "/v1/reviews", search="deck:*", select=REVIEW_FIELDS))["items"])


WORKLOADS = [LookupDuplicates(), LookupDuplicatesAllModels(), MineWithMedia(), UpdateLastMined(), KnownWordsSnapshot(),
             MinedWordsCache(), ChangePoll(), NoteTypeFields(), ReviewHistory(), ReviewHistoryAll()]


async def delete_created(c, ctx):
    if ctx.get("created"):
        await c.action("deleteNotes", notes=ctx["created"])
    for name in ctx.get("media", []):
        await c.action("deleteMediaFile", filename=name)
    ctx["created"], ctx["media"] = [], []


async def leftovers(c):
    return {"deck_notes": len(await c.action("findNotes", query=BENCH_SEARCH)),
            "tagged_notes": len(await c.action("findNotes", query=f"tag:{TAG}*")),
            "media": await c.action("getMediaFilesNames", pattern=f"{PREFIX}*")}


async def run(args, report):
    endpoint = Endpoint.parse(args.url)
    c = Client(endpoint, os.environ.get(args.api_key_env))
    if await c.action("getActiveProfile") != args.profile:
        raise RuntimeError(f"Expected testing profile {args.profile!r}")
    before = await leftovers(c)
    if any(before.values()):
        raise RuntimeError(f"Benchmark deck, tag or media already present; clean up first: {before}")
    report["baseline_notes"] = len(await c.action("findNotes", query=""))
    if MODEL not in await c.action("modelNames"):
        raise RuntimeError(f"The testing profile needs the {MODEL!r} note type")
    # Ten real terms for the duplicate lookup: the lowest note IDs with plain text.
    ids = sorted(await c.action("findNotes", query=f'"note:{MODEL}"'))
    terms = []
    for note in await c.action("notesInfo", notes=ids[:200]):
        term = fields_of(note).get(TERM_FIELD, "")
        if term and all(ch not in term for ch in '"\\:*_()<> ') and term not in terms:
            terms.append(term)
        if len(terms) == 10:
            break
    ctx = {"existing_terms": terms}
    report["existing_terms"] = terms
    await c.action("createDeck", deck=DECK)
    selected = [w for w in WORKLOADS if not args.workloads or w.name in args.workloads]
    impl = "tsunagi" if args.implementation == "native" else "ankiconnect"
    try:
        for workload in selected:
            entry = {"workload": workload.name, "source": workload.source, "trials": []}
            report["workloads"].append(entry)
            for trial in range(args.repeats + 1):   # trial 0 is the first-use run
                await workload.setup(c, ctx, trial)
                c.requests = c.response_bytes = 0
                started = time.perf_counter()
                result = await getattr(workload, impl)(c, ctx, trial)
                elapsed = (time.perf_counter() - started) * 1000
                requests, size = c.requests, c.response_bytes
                if workload.writes:
                    result = await workload.verify(c, ctx, trial)
                    await workload.cleanup(c, ctx, trial)
                entry["trials"].append({"trial": trial, "elapsed_ms": elapsed, "requests": requests,
                                        "response_bytes": size, "result_sha256": digest(result)})
                if trial == 0:
                    entry["result_sample"] = result if len(json.dumps(result)) < 4000 else None
            timed = [t["elapsed_ms"] for t in entry["trials"][1:]]
            entry["median_ms"] = statistics.median(timed)
            entry["min_ms"], entry["max_ms"] = min(timed), max(timed)
            entry["consistent_result"] = len({t["result_sha256"] for t in entry["trials"]}) == 1
            save(args.output, report)
            print(f"{workload.name}: median {entry['median_ms']:.1f} ms, "
                  f"{entry['trials'][1]['requests']} requests, "
                  f"{entry['trials'][1]['response_bytes']:,} bytes, "
                  f"result {entry['trials'][1]['result_sha256'][:12]}"
                  f"{'' if entry['consistent_result'] else ' (VARIED)'}", flush=True)
    finally:
        await delete_created(c, ctx)
        await c.action("deleteDecks", decks=[DECK], cardsToo=True)
        after = await leftovers(c)
        report["leftovers"] = after
        report["final_notes"] = len(await c.action("findNotes", query=""))
        if any(after.values()) or report["final_notes"] != report["baseline_notes"]:
            raise RuntimeError(f"Cleanup incomplete: {after}, notes {report['final_notes']} "
                               f"vs baseline {report['baseline_notes']}")
    report["completed"] = True


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--profile", required=True, help="Exact testing profile name; checked first")
    parser.add_argument("--implementation", required=True, choices=("upstream", "shim", "native"))
    parser.add_argument("--workloads", nargs="*", choices=[w.name for w in WORKLOADS])
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--api-key-env", default="TSUNAGI_BENCH_API_KEY")
    parser.add_argument("--server-label", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("Use at least one repeat")
    if args.output.exists():
        parser.error("Output already exists; choose a new path")
    report = {"schema": 1, "started_at": datetime.now(timezone.utc).isoformat(),
              "mode": "live_anki_workloads", "python": sys.version, "platform": platform.platform(),
              "config": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()
                         if k != "api_key_env"},
              "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (Path(__file__), Path(__file__).with_name("connection_bench.py"))},
              "limits": ["One new connection per request, sequential, no pooling.",
                         "Setup, verification and cleanup are not timed.",
                         "Write workloads add and delete notes and media in a dedicated deck."],
              "workloads": [], "completed": False}
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
