"""
In-memory FakeCollection implementing exactly the slice of Anki's Collection
API that tsunagi's adapters call (col.models / col.decks). Dicts follow the
schema11 wire shapes the adapters parse with pydantic.

Managers hand out deepcopies (like Anki's backend returns fresh dicts) and
persist on add/update_dict/save.
"""
import copy
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


class FakeCollection:
    def __init__(self, seed=True):
        self.models = FakeModelManager(seed=seed)
        self.decks = FakeDeckManager(seed=seed)
