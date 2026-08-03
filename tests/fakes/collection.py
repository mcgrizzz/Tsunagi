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


def _deck_config(cid, name):
    return {
        "id": cid, "name": name, "mod": 0, "usn": 0, "maxTaken": 60,
        "autoplay": True, "timer": 0, "replayq": True,
        "new": {"delays": [1.0, 10.0], "ints": [1, 4, 0], "initialFactor": 2500,
                "perDay": 20, "order": 1, "bury": False},
        "rev": {"perDay": 200, "ease4": 1.3, "ivlFct": 1.0, "maxIvl": 36500,
                "bury": False, "hardFactor": 1.2},
        "lapse": {"delays": [10.0], "mult": 0.0, "minInt": 1, "leechFails": 8,
                  "leechAction": 1},
        "dyn": False,
    }


class FakeDeckManager:
    def __init__(self, seed=True):
        self._store = {}
        self._configs = {}
        self._next_id = 5000
        self._next_config_id = 6000
        if seed:
            self._store[1] = _deck(1, "Default")
            self._configs[1] = _deck_config(1, "Default")

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    # --- deck configs (options groups) ---
    def all_config(self):
        return [copy.deepcopy(c) for c in self._configs.values()]

    def get_config(self, conf_id):
        c = self._configs.get(int(conf_id))
        return copy.deepcopy(c) if c is not None else None

    def config_dict_for_deck_id(self, did):
        deck = self.get(did, default=False)
        assert deck is not None
        if "conf" in deck:
            conf = self.get_config(int(deck["conf"])) or self.get_config(1)
            conf["dyn"] = False
            return conf
        return deck  # filtered decks embed their own config

    def update_config(self, conf, preserve_usn=False):
        if not conf.get("id"):
            self._next_config_id += 1
            conf["id"] = self._next_config_id
        self._configs[int(conf["id"])] = copy.deepcopy(conf)

    def add_config(self, name, clone_from=None):
        if clone_from is not None:
            conf = copy.deepcopy(clone_from)
            conf["id"] = 0
        else:
            conf = _deck_config(0, name)
        conf["name"] = name
        self.update_config(conf)
        return conf

    def add_config_returning_id(self, name, clone_from=None):
        return self.add_config(name, clone_from)["id"]

    def remove_config(self, conf_id):
        # Anki reassigns every deck using it back to the default config.
        for deck in self._store.values():
            if "conf" in deck and str(deck["conf"]) == str(conf_id):
                deck["conf"] = 1
        self._configs.pop(int(conf_id), None)

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


class FakeCard:
    """
    Faithful to anki.cards.Card in the ways the adapters care about: the
    scheduling columns are plain attributes, and question()/answer() render
    the notetype's templates against the note's fields rather than returning
    a canned string (an inert fake would hide projection/`wants` bugs).
    """

    def __init__(self, col, cid, nid, did, ord_, due):
        self._col = col
        self.id = cid
        self.nid = nid
        self.did = did
        self.odid = 0
        self.ord = ord_
        self.mod = 1700000000
        self.usn = 0
        self.type = 0        # CARD_TYPE_NEW
        self.queue = 0       # QUEUE_TYPE_NEW
        self.due = due
        self.odue = 0
        self.ivl = 0
        self.factor = 0
        self.reps = 0
        self.lapses = 0
        self.left = 0
        self.flags = 0

    def note(self):
        return self._col.get_note(self.nid)

    def note_type(self):
        return self.note().note_type()

    def template(self):
        tmpls = self.note_type()["tmpls"]
        return tmpls[self.ord] if self.ord < len(tmpls) else tmpls[0]

    def current_deck_id(self):
        return self.odid or self.did

    def css(self):
        return self.note_type().get("css", "")

    def _render(self, fmt):
        note = self.note()
        out = fmt.replace("{{FrontSide}}", self._render_side("qfmt"))
        for name, value in zip(note.keys(), note.fields):
            out = out.replace("{{%s}}" % name, value)
        return out

    def _render_side(self, key):
        tmpl = self.template()
        fmt = tmpl.get(key, "")
        note = self.note()
        out = fmt
        for name, value in zip(note.keys(), note.fields):
            out = out.replace("{{%s}}" % name, value)
        return out

    def question(self):
        return self._render_side("qfmt")

    def answer(self):
        return self._render(self.template().get("afmt", ""))


class FakeScheduler:
    """
    The slice of anki.scheduler.base.Scheduler the cards adapter calls.
    Queue/type values are Anki's real constants, so tests assert on the same
    numbers a client would see.
    """

    def __init__(self, col):
        self._col = col

    def _cards(self, ids):
        return [c for c in (self._col._cards.get(int(i)) for i in ids) if c is not None]

    @staticmethod
    def _restore_queue(card):
        # Anki's restore_buried_and_suspended_cards puts the card back in the
        # queue implied by its type.
        card.queue = card.type if card.type in (0, 1, 2) else 0

    # Anki's OpChangesWithCount reports cards actually MODIFIED, not cards
    # submitted - suspending an already-suspended card counts for nothing.
    # unsuspend/unbury return a bare OpChanges with no count at all.
    def suspend_cards(self, ids):
        changed = [c for c in self._cards(ids) if c.queue != -1]
        for c in changed:
            c.queue = -1
        return SimpleNamespace(count=len(changed))

    def unsuspend_cards(self, ids):
        for c in self._cards(ids):
            if c.queue == -1:
                self._restore_queue(c)
        return SimpleNamespace()  # OpChanges: no count

    def bury_cards(self, ids, manual=True):
        target = -3 if manual else -2
        changed = [c for c in self._cards(ids) if c.queue != target]
        for c in changed:
            c.queue = target
        return SimpleNamespace(count=len(changed))

    def unbury_cards(self, ids):
        for c in self._cards(ids):
            if c.queue in (-2, -3):
                self._restore_queue(c)
        return SimpleNamespace()  # OpChanges: no count

    def schedule_cards_as_new(self, card_ids, *, restore_position=False,
                              reset_counts=False, context=None):
        for c in self._cards(card_ids):
            c.type = 0
            c.queue = 0
            c.ivl = 0
            if reset_counts:
                c.reps = 0
                c.lapses = 0
        return SimpleNamespace()  # OpChanges: no count

    def set_due_date(self, card_ids, days, config_key=None):
        low = str(days).split("-")[0]
        try:
            offset = int(low)
        except ValueError as e:
            raise ValueError(f"invalid due date: {days}") from e
        for c in self._cards(card_ids):
            c.type = 2
            c.queue = 2
            c.due = offset
            c.ivl = max(c.ivl, offset)
        return SimpleNamespace()  # OpChanges: no count

    def reposition_new_cards(self, card_ids, starting_from, step_size,
                             randomize, shift_existing):
        # Only cards in the new queue have a position to reposition.
        cards = [c for c in self._cards(card_ids) if c.queue == 0]
        pos = starting_from
        for c in cards:
            c.due = pos
            pos += step_size
        return SimpleNamespace(count=len(cards))

    def deck_due_tree(self):
        decks = sorted(self._col.decks.all(), key=lambda d: d["name"])
        # Anki hides the Default deck from the tree while it's empty and other
        # decks exist, exactly like the deck browser. Adapters must therefore
        # cope with a deck having no node at all.
        if len(decks) > 1 and not any(c.did == 1 for c in self._col._cards.values()):
            decks = [d for d in decks if d["id"] != 1]
        own = {d["id"]: {"new_count": 0, "learn_count": 0,
                         "review_count": 0, "total_in_deck": 0} for d in decks}
        for c in self._col._cards.values():
            counts = own.get(c.did)
            if counts is None:
                continue
            counts["total_in_deck"] += 1
            if c.queue == 0:
                counts["new_count"] += 1
            elif c.queue in (1, 3):
                counts["learn_count"] += 1
            elif c.queue == 2:
                counts["review_count"] += 1

        def build(name_prefix, parent_id):
            children = []
            for d in decks:
                name = d["name"]
                if name_prefix:
                    if not name.startswith(name_prefix + "::"):
                        continue
                    rest = name[len(name_prefix) + 2:]
                else:
                    rest = name
                if "::" in rest:
                    continue
                children.append(build(name, d["id"]))
            counts = own.get(parent_id, {"new_count": 0, "learn_count": 0,
                                         "review_count": 0, "total_in_deck": 0})
            node = SimpleNamespace(
                deck_id=parent_id,
                name=name_prefix.split("::")[-1] if name_prefix else "",
                children=children,
                **{k: counts[k] + sum(getattr(ch, k) for ch in children) for k in counts},
            )
            return node

        return build("", 0)

    def deck_due_tree_ids(self):
        """Deck ids the tree actually contains - lets tests assert the gap."""
        seen = set()

        def walk(node):
            seen.add(int(node.deck_id))
            for child in node.children:
                walk(child)

        walk(self.deck_due_tree())
        return seen


class FakeBackend:
    """
    The two private backend calls cardsInfo's `nextReviews` needs. Kept
    deliberately thin: the adapter treats any failure here as "field absent",
    and that fallback is what protects us if a future Anki moves them.
    """

    def __init__(self, col):
        self._col = col

    def get_scheduling_states(self, card_id):
        return SimpleNamespace(card_id=card_id)

    def describe_next_states(self, states):
        return ["<1m", "<10m", "1d", "4d"]


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

    def rename(self, old, new):
        count = 0
        for note in self._col._notes.values():
            # Anki renames the tag and its children ("a" also renames "a::b").
            renamed = [new + t[len(old):] if t == old or t.startswith(old + "::") else t
                       for t in note.tags]
            if renamed != note.tags:
                note.tags = renamed
                count += 1
        return SimpleNamespace(count=count)

    def remove(self, space_separated_tags):
        drop = {t for t in space_separated_tags.split() if t}
        count = 0
        for note in self._col._notes.values():
            kept = [t for t in note.tags
                    if t not in drop and not any(t.startswith(d + "::") for d in drop)]
            if kept != note.tags:
                note.tags = kept
                count += 1
        return SimpleNamespace(count=count)

    def clear_unused_tags(self):
        # Every tag in the fake is derived from live notes, so nothing is ever
        # unused. Returning 0 is the honest answer, not a stub.
        return SimpleNamespace(count=0)


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
            return [c.did for c in self._col._cards.values() if c.nid == args[0]]
        if norm == "select ivl from revlog where cid = ?":
            return [ivl for (_id, cid, ivl) in self._col._revlog if cid == args[0]]
        raise AssertionError(f"FakeDb: unhandled SQL {norm!r}")

    def all(self, sql, *args):
        norm = " ".join(sql.split())
        if norm == "select id/1000.0, ivl from revlog where cid = ?":
            return [(_id / 1000.0, ivl)
                    for (_id, cid, ivl) in self._col._revlog if cid == args[0]]
        raise AssertionError(f"FakeDb: unhandled SQL {norm!r}")

    def execute(self, sql, *args):
        norm = " ".join(sql.split())
        m = re.match(r"^update cards set type=3, queue=1 where id in \((.*)\)$", norm)
        if m:
            for raw in m.group(1).split(","):
                card = self._col._cards.get(int(raw))
                if card is not None:
                    card.type, card.queue = 3, 1
            return None
        raise AssertionError(f"FakeDb: unhandled SQL {norm!r}")


class FakeCollection:
    def __init__(self, seed=True):
        self.models = FakeModelManager(seed=seed)
        self.decks = FakeDeckManager(seed=seed)
        self.media = FakeMediaManager()
        self.db = FakeDb(self)
        self.tags = FakeTagManager(self)
        self.sched = FakeScheduler(self)
        self._backend = FakeBackend(self)
        self._notes = {}
        self._cards = {}
        self._revlog = []          # (id_ms, cid, ivl) rows
        self._next_note_id = 7000
        self._next_card_id = 8000
        self._next_due = 0
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
            nids = {c.nid for c in self._cards.values() if c.did in dids}
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
        q = (query or "").strip()
        if q == "is:suspended":
            return sorted(c.id for c in self._cards.values() if c.queue == -1)
        if q == "is:buried":
            return sorted(c.id for c in self._cards.values() if c.queue in (-2, -3))
        if q.startswith("cid:"):
            # AnkiConnect's areDue probes "cid:<id> is:new" / "cid:<id> is:due".
            cid_part, _, rest = q[4:].partition(" ")
            card = self._cards.get(int(cid_part))
            if card is None:
                return []
            rest = rest.strip()
            if rest == "is:new":
                return [card.id] if card.queue == 0 else []
            if rest == "is:due":
                return [card.id] if card.queue in (1, 2, 3) else []
            if not rest:
                return [card.id]
            from fakes.anki_stubs import SearchError
            raise SearchError(f"unsupported fake search: {q}")
        nids = set(self.find_notes(query))
        return sorted(c.id for c in self._cards.values() if c.nid in nids)

    # --- cards ---
    def get_card(self, cid):
        card = self._cards.get(int(cid))
        if card is None:
            from fakes.anki_stubs import NotFoundError
            raise NotFoundError(f"card {cid}")
        return card

    def update_card(self, card, skip_undo_entry=False):
        self._cards[int(card.id)] = card

    def set_deck(self, card_ids, deck_id):
        count = 0
        for cid in card_ids:
            card = self._cards.get(int(cid))
            if card is not None and card.did != int(deck_id):
                card.did = int(deck_id)
                card.odid = 0
                count += 1
        return SimpleNamespace(count=count)

    def set_user_flag_for_cards(self, flag, cids):
        count = 0
        for cid in cids:
            card = self._cards.get(int(cid))
            if card is None:
                continue
            new_flags = (card.flags & ~0b111) | int(flag)
            if new_flags != card.flags:
                card.flags = new_flags
                count += 1
        return SimpleNamespace(count=count)

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
            self._next_due += 1
            self._cards[self._next_card_id] = FakeCard(
                self, self._next_card_id, note.id, int(deck_id), t["ord"], self._next_due,
            )
        return SimpleNamespace(count=1)

    def update_note(self, note):
        self._notes[note.id] = note

    def remove_notes(self, nids):
        count = 0
        for nid in [int(n) for n in nids]:
            if self._notes.pop(nid, None) is not None:
                count += 1
                for cid in [c.id for c in self._cards.values() if c.nid == nid]:
                    self._cards.pop(cid, None)
        return SimpleNamespace(count=count)

    def card_ids_of_note(self, nid):
        return [c.id for c in sorted(self._cards.values(), key=lambda c: c.ord)
                if c.nid == int(nid)]
