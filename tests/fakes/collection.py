"""
In-memory FakeCollection implementing exactly the slice of Anki's Collection
API that tsunagi's adapters call (col.models / col.decks). Dicts follow the
schema11 wire shapes the adapters parse with pydantic.

Managers hand out deepcopies (like Anki's backend returns fresh dicts) and
persist on add/update_dict/save.
"""
import copy
import hashlib
import os
import re
import tempfile
from types import SimpleNamespace


def _basic_model(mid, name, fields, templates, mtype=0):
    return {
        "id": mid, "name": name, "type": mtype, "mod": 0, "usn": 0,
        "sortf": 0, "did": None, "css": "",
        "flds": [{"name": f, "ord": i} for i, f in enumerate(fields)],
        "tmpls": [{"name": t, "ord": i, "qfmt": "{{%s}}" % fields[0], "afmt": ""}
                  for i, t in enumerate(templates)],
    }


def _deck(did, name, **overrides):
    d = {
        "id": did, "name": name, "mod": 0, "usn": 0, "desc": "",
        "dyn": 0, "conf": 1, "collapsed": False, "browserCollapsed": False,
        "lrnToday": [0, 0], "revToday": [0, 0], "newToday": [0, 0],
        "timeToday": [0, 0], "extendNew": 0, "extendRev": 0,
    }
    d.update(overrides)
    return d


class FakeModelManager:
    def __init__(self, seed=True):
        self._store = {}
        self._next_id = 1000
        if seed:
            self._store[1001] = _basic_model(1001, "Basic", ["Front", "Back"], ["Card 1"])
            self._store[1002] = _basic_model(1002, "Cloze", ["Text", "Back Extra"], ["Cloze"], mtype=1)
            self._next_id = 2000

    # --- reads ---
    def all(self):
        return [copy.deepcopy(m) for m in self._store.values()]

    def get(self, mid):
        m = self._store.get(mid)
        return copy.deepcopy(m) if m is not None else None

    def all_names_and_ids(self):
        return [SimpleNamespace(id=m["id"], name=m["name"])
                for m in sorted(self._store.values(), key=lambda x: x["name"])]

    def by_name(self, name):
        for m in self._store.values():
            if m["name"] == name:
                return copy.deepcopy(m)
        return None

    # --- construction ---
    def new(self, name):
        return {"name": name, "type": 0, "mod": 0, "usn": 0, "sortf": 0,
                "did": None, "css": "", "flds": [], "tmpls": []}

    def new_field(self, name):
        return {"name": name, "ord": 0}

    def new_template(self, name):
        return {"name": name, "ord": 0, "qfmt": "", "afmt": ""}

    def add_field(self, m, field):
        field["ord"] = len(m["flds"])
        m["flds"].append(field)

    def add_template(self, m, template):
        template["ord"] = len(m["tmpls"])
        m["tmpls"].append(template)

    # --- persistence ---
    def add(self, m):
        self._next_id += 1
        m["id"] = self._next_id
        self._store[m["id"]] = copy.deepcopy(m)

    def update_dict(self, m):
        self._store[m["id"]] = copy.deepcopy(m)

    def remove(self, mid):
        self._store.pop(mid, None)

    # --- subresource mutations (operate on the caller's working copy) ---
    def rename_field(self, m, field, new_name):
        field["name"] = new_name

    def remove_field(self, m, field):
        m["flds"].remove(field)
        for i, f in enumerate(m["flds"]):
            f["ord"] = i

    def reposition_field(self, m, field, idx):
        m["flds"].remove(field)
        m["flds"].insert(idx, field)
        for i, f in enumerate(m["flds"]):
            f["ord"] = i

    def remove_template(self, m, template):
        m["tmpls"].remove(template)
        for i, t in enumerate(m["tmpls"]):
            t["ord"] = i

    def reposition_template(self, m, template, idx):
        m["tmpls"].remove(template)
        m["tmpls"].insert(idx, template)
        for i, t in enumerate(m["tmpls"]):
            t["ord"] = i


class FakeDeckManager:
    def __init__(self, seed=True):
        self._store = {}
        self._next_id = 5000
        if seed:
            self._store[1] = _deck(1, "Default")

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    # --- reads ---
    def all(self):
        return [copy.deepcopy(d) for d in self._store.values()]

    def all_names_and_ids(self, skip_empty_default=False, include_filtered=True):
        return [SimpleNamespace(id=d["id"], name=d["name"])
                for d in sorted(self._store.values(), key=lambda x: x["name"])]

    def get(self, did, default=True):
        # Faithful to Anki's DeckManager.get: missing id falls back to the
        # DEFAULT deck unless default=False. Adapters must pass default=False.
        d = self._store.get(did)
        if d is not None:
            return copy.deepcopy(d)
        return copy.deepcopy(self._store[1]) if default else None

    def by_name(self, name):
        for d in self._store.values():
            if d["name"] == name:
                return copy.deepcopy(d)
        return None

    # --- creation (both create "::" parents, like Anki) ---
    def _create_with_parents(self, name):
        parts = name.split("::")
        did = None
        for i in range(1, len(parts) + 1):
            prefix = "::".join(parts[:i])
            existing = self.by_name(prefix)
            if existing is not None:
                did = existing["id"]
                continue
            did = self._new_id()
            self._store[did] = _deck(did, prefix)
        return did

    def id(self, name):
        return self._create_with_parents(name)

    def add_normal_deck_with_name(self, name):
        return SimpleNamespace(id=self._create_with_parents(name))

    # --- mutations ---
    def remove(self, dids):
        count = 0
        for did in list(dids):
            d = self._store.pop(did, None)
            if d is None:
                continue
            count += 1
            prefix = d["name"] + "::"
            children = [k for k, v in self._store.items() if v["name"].startswith(prefix)]
            for k in children:
                self._store.pop(k)
                count += 1
        return SimpleNamespace(count=count)

    def rename(self, deck, new_name):
        old_name = self._store[deck["id"]]["name"]
        deck["name"] = new_name  # Anki mutates the passed dict too
        self._store[deck["id"]]["name"] = new_name
        prefix = old_name + "::"
        for d in self._store.values():
            if d["name"].startswith(prefix):
                d["name"] = new_name + "::" + d["name"][len(prefix):]

    def save(self, deck):
        self._store[deck["id"]] = copy.deepcopy(deck)

    def children(self, did):
        """(name, id) of descendants, EXCLUDING did itself (like Anki)."""
        parent = self._store.get(did)
        if parent is None:
            return []
        prefix = parent["name"] + "::"
        return [(d["name"], d["id"]) for d in self._store.values()
                if d["name"].startswith(prefix)]


class FakeMediaManager:
    """
    Backed by a real temp directory - os.scandir, FileResponse, realpath and
    symlink containment are filesystem behavior that an in-memory fake would
    not exercise. Tests must rmtree dir() on teardown.
    """

    def __init__(self):
        self._dir = tempfile.mkdtemp(prefix="tsunagi-media-")

    def dir(self):
        return self._dir

    def have(self, fname):
        return os.path.exists(os.path.join(self._dir, fname))

    def write_data(self, desired_fname, data):
        """
        Replicates Anki's rename-on-collision: same name + different bytes
        gets a suffix. The suffix format is arbitrary - assert that the
        returned name differs, never its exact spelling.
        """
        name = os.path.basename(desired_fname)
        path = os.path.join(self._dir, name)
        if os.path.exists(path):
            with open(path, "rb") as fh:
                if fh.read() == data:
                    return name  # identical content: no rename
            stem, ext = os.path.splitext(name)
            name = f"{stem}-{hashlib.sha1(data).hexdigest()[:8]}{ext}"
            path = os.path.join(self._dir, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return name

    def add_file(self, path):
        with open(path, "rb") as fh:
            return self.write_data(os.path.basename(path), fh.read())

    def trash_files(self, fnames):
        for fname in fnames:
            try:
                os.unlink(os.path.join(self._dir, os.path.basename(fname)))
            except OSError:
                pass


class FakeNote:
    """
    Faithful to anki.notes.Note: .fields is POSITIONAL, name access goes
    through the notetype's field map, and unknown names raise KeyError (a
    permissive fake would green-light code that 500s against real Anki).
    """

    def __init__(self, col, notetype, nid=0):
        self._col = col
        self._nt = notetype
        self.id = nid
        self.mid = int(notetype["id"]) if notetype.get("id") else 0
        self.guid = ""
        self.mod = 0
        self.usn = 0
        self.tags = []
        self.fields = [""] * len(notetype["flds"])
        self._fmap = {f["name"]: i for i, f in enumerate(notetype["flds"])}

    def keys(self):
        return [f["name"] for f in self._nt["flds"]]

    def items(self):
        return list(zip(self.keys(), self.fields))

    def __contains__(self, name):
        return name in self._fmap

    def __getitem__(self, name):
        return self.fields[self._fmap[name]]

    def __setitem__(self, name, value):
        self.fields[self._fmap[name]] = value

    def note_type(self):
        return self._nt

    def fields_check(self):
        from fakes.anki_stubs import strip_html_media

        first = self.fields[0] if self.fields else ""
        stripped = strip_html_media(first).strip()
        if not stripped:
            return 1  # EMPTY
        if int(self._nt.get("type", 0)) == 1 and "{{c" not in "".join(self.fields):
            return 3  # MISSING_CLOZE
        for other in self._col._notes.values():
            if other.id == self.id or other.mid != self.mid:
                continue
            other_first = other.fields[0] if other.fields else ""
            if strip_html_media(other_first).strip() == stripped:
                return 2  # DUPLICATE
        return 0  # NORMAL


class FakeTagManager:
    def __init__(self, col):
        self._col = col

    def all(self):
        seen = []
        for note in self._col._notes.values():
            for tag in note.tags:
                if tag not in seen:
                    seen.append(tag)
        return sorted(seen)

    def bulk_add(self, note_ids, tags):
        wanted = [t for t in tags.split() if t]
        count = 0
        for nid in note_ids:
            note = self._col._notes.get(int(nid))
            if note is None:
                continue
            added = [t for t in wanted if t not in note.tags]
            if added:
                note.tags = list(note.tags) + added
                count += 1
        return SimpleNamespace(count=count)

    def bulk_remove(self, note_ids, tags):
        drop = {t for t in tags.split() if t}
        count = 0
        for nid in note_ids:
            note = self._col._notes.get(int(nid))
            if note is None:
                continue
            kept = [t for t in note.tags if t not in drop]
            if kept != note.tags:
                note.tags = kept
                count += 1
        return SimpleNamespace(count=count)


class FakeDb:
    """
    Shim for the handful of raw SQL statements AnkiConnect's scoped
    duplicate check issues. Dispatches on the exact statement text: an
    unrecognized query raises rather than silently returning nothing.
    """

    def __init__(self, col):
        self._col = col

    def list(self, sql, *args):
        from fakes.anki_stubs import field_checksum

        norm = " ".join(sql.split())
        if norm.startswith("select id from notes where csum = ?"):
            csum = args[0]
            rest = list(args[1:])
            exclude_id = rest.pop(0) if " and id != ?" in norm else None
            mid = rest.pop(0) if " and mid = ?" in norm else None
            out = []
            for note in self._col._notes.values():
                first = note.fields[0] if note.fields else ""
                if field_checksum(first) != csum:
                    continue
                if exclude_id is not None and note.id == exclude_id:
                    continue
                if mid is not None and note.mid != mid:
                    continue
                out.append(note.id)
            return sorted(out)
        if norm == "select did from cards where nid = ?":
            return [c["did"] for c in self._col._cards.values() if c["nid"] == args[0]]
        raise AssertionError(f"FakeDb: unhandled SQL {norm!r}")


class FakeCollection:
    def __init__(self, seed=True):
        self.models = FakeModelManager(seed=seed)
        self.decks = FakeDeckManager(seed=seed)
        self.media = FakeMediaManager()
        self.db = FakeDb(self)
        self.tags = FakeTagManager(self)
        self._notes = {}
        self._cards = {}
        self._next_note_id = 7000
        self._next_card_id = 8000
        self.find_notes_calls = 0

    # --- search ---
    def build_search_string(self, *nodes, joiner="AND"):
        parts = []
        for n in nodes:
            if getattr(n, "dupe", None) is not None:
                parts.append(f"dupe:{n.dupe.notetype_id},{n.dupe.first_field}")
            elif getattr(n, "deck", None) is not None:
                parts.append(f"deck:{n.deck}")
            elif getattr(n, "nids", None) is not None:
                parts.append("nid:" + ",".join(str(i) for i in n.nids))
        return f" {joiner} ".join(parts)

    def find_notes(self, query, order=False, reverse=False):
        """
        Deliberately tiny parser. Unsupported syntax RAISES rather than
        silently matching, so tests can't depend on semantics we don't have.
        """
        self.find_notes_calls += 1
        q = (query or "").strip()
        if not q:
            return sorted(self._notes)  # whole collection, like Anki
        if q.startswith("nid:"):
            wanted = {int(x) for x in q[4:].split(",") if x}
            return sorted(nid for nid in self._notes if nid in wanted)
        if q.startswith("dupe:"):
            mid_s, _, first = q[5:].partition(",")
            mid = int(mid_s)
            stripped = re.sub(r"<[^>]+>", "", first).strip()
            return sorted(
                n.id for n in self._notes.values()
                if n.mid == mid and re.sub(r"<[^>]+>", "", n.fields[0] if n.fields else "").strip() == stripped
            )
        if q.startswith("deck:"):
            name = q[5:]
            deck = self.decks.by_name(name)
            if deck is None:
                return []
            dids = {deck["id"]}
            nids = {c["nid"] for c in self._cards.values() if c["did"] in dids}
            return sorted(nids)
        if q.startswith("tag:"):
            tag = q[4:]
            return sorted(n.id for n in self._notes.values() if tag in n.tags)
        if ":" in q:
            from fakes.anki_stubs import SearchError
            raise SearchError(f"unsupported fake search: {q}")
        needle = q.casefold()
        return sorted(n.id for n in self._notes.values()
                      if any(needle in f.casefold() for f in n.fields))

    def find_cards(self, query):
        nids = set(self.find_notes(query))
        return sorted(c["id"] for c in self._cards.values() if c["nid"] in nids)

    # --- notes ---
    def get_note(self, nid):
        note = self._notes.get(int(nid))
        if note is None:
            from fakes.anki_stubs import NotFoundError
            raise NotFoundError(f"note {nid}")
        return note

    def new_note(self, notetype):
        return FakeNote(self, notetype)

    def add_note(self, note, deck_id):
        self._next_note_id += 1
        note.id = self._next_note_id
        note.guid = f"guid{note.id}"
        note.mod = 1700000000
        self._notes[note.id] = note
        for t in note._nt["tmpls"]:
            self._next_card_id += 1
            self._cards[self._next_card_id] = {
                "id": self._next_card_id, "nid": note.id,
                "did": int(deck_id), "ord": t["ord"],
            }
        return SimpleNamespace(count=1)

    def update_note(self, note):
        self._notes[note.id] = note

    def remove_notes(self, nids):
        count = 0
        for nid in [int(n) for n in nids]:
            if self._notes.pop(nid, None) is not None:
                count += 1
                for cid in [c["id"] for c in self._cards.values() if c["nid"] == nid]:
                    self._cards.pop(cid, None)
        return SimpleNamespace(count=count)

    def card_ids_of_note(self, nid):
        return [c["id"] for c in sorted(self._cards.values(), key=lambda c: c["ord"])
                if c["nid"] == int(nid)]
