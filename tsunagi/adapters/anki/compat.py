"""Collection operations whose observable quirks belong only to AnkiConnect."""

from ..ops import ValueWithChanges, as_collection_op, as_query_op


@as_collection_op
def resolve_deck_names(col, names):
    """Only the compatibility caller chooses to create decks during a lookup."""
    from anki.collection import OpChanges

    try:
        existing = {deck.id for deck in col.decks.all_names_and_ids()}
        ids = [col.decks.id(name) for name in names]
        resolved = [col.decks.get(did)["name"] for did in ids]
        # The legacy lookup discards its OpChanges; notify Qt about new decks.
        return ValueWithChanges(resolved, OpChanges(deck=any(did not in existing for did in ids)))
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def insert_scalar_reviews(col, reviews):
    """Preserve SQLite scalar coercion and diagnostics for legacy review rows.

    Normal integer rows use the native parameterized writer. This path accepts
    scalar tokens only, never SQL expressions/statements supplied as values.
    Keeping the original statement text also preserves SQLite error offsets.
    """
    import re

    scalar = re.compile(
        r"(?:[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
        r"|0[xX][0-9a-fA-F]+|[a-zA-Z_][a-zA-Z_0-9]*|'(?:[^']|'')*'|)"
    )
    if len(reviews) == 0:
        return
    groups = []
    for row in reviews:
        tokens = [str(value) for value in row]
        if any(scalar.fullmatch(token.strip()) is None for token in tokens):
            raise ValueError("review values must be scalar SQL literals")
        groups.append("(" + ",".join(tokens) + ")")
    sql = "insert into revlog(id,cid,usn,ease,ivl,lastIvl,factor,time,type) values "
    col.db.execute(sql + ",".join(groups))


@as_collection_op
def update_cached_template(col, model_name, template_name, updates):
    """Match AnkiConnect's existing-template edit: update the cache without saving."""
    model = col.models.by_name(model_name)
    for template in model["tmpls"]:
        if template["name"] == template_name:
            template.update(updates)
            return


@as_query_op
def find_ids(col, query, *, cards=False):
    """Preserve Anki's input types and exception text at the shim boundary."""
    try:
        return list(col.find_cards(query) if cards else col.find_notes(query))
    except Exception as exc:
        # The dispatcher exposes ValueError text; native search adds context.
        raise ValueError(str(exc)) from exc


@as_query_op
def deck_tree_names(col):
    """Due-tree membership and leaf names, including omission of empty Default."""
    names = {}

    def visit(node):
        names[int(node.deck_id)] = node.name
        for child in node.children:
            visit(child)

    visit(col.sched.deck_due_tree())
    return names


@as_query_op
def decks_for_cards(col, cards):
    """Keep request order/duplicates and Anki's missing-card deck fallback."""
    if any(type(card) is not int for card in cards):
        result = {}
        try:
            for card in cards:
                did = col.db.scalar("select did from cards where id = ?", card)
                result.setdefault(col.decks.get(did)["name"], []).append(card)
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        return result
    deck_ids = {}
    for offset in range(0, len(cards), 250):
        batch = cards[offset:offset + 250]
        placeholders = ",".join("?" for _ in batch)
        deck_ids.update(col.db.all(
            f"select id, did from cards where id in ({placeholders})", *batch,
        ))
    result = {}
    for card in cards:
        name = col.decks.get(deck_ids.get(card))["name"]
        result.setdefault(name, []).append(card)
    return result


def raw_id_list(values):
    """Materialize legacy iterables without changing their elements or errors."""
    try:
        return list(values)
    except TypeError as exc:
        raise ValueError(str(exc)) from exc


@as_query_op
def validate_object_ids(col, ids, *, notes=False, note_cards=False):
    """Let Anki diagnose raw object IDs before the native batch fetch coerces them."""
    try:
        if note_cards:
            # notesInfo binds IDs to its card lookup before loading note objects.
            for offset in range(0, len(ids), 999):
                batch = ids[offset:offset + 999]
                col.db.all("select id from cards where nid in ("
                           + ",".join("?" for _ in batch) + ")", *batch)
        load = col.get_note if notes else col.get_card
        resolved = []
        for value in ids:
            if type(value) is int:
                resolved.append(value)
                continue
            try:
                resolved.append(load(value).id)
            except Exception as exc:
                if type(exc).__name__ != "NotFoundError":
                    raise
                resolved.append(0)
        return resolved
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_query_op
def raw_card_schedule(col, ids, *, due=False, complete=False):
    """Retain per-ID search and SQL semantics for non-integer legacy values."""
    import time

    try:
        result = []
        for cid in ids:
            if col.find_cards(f"cid:{cid} is:new"):
                result.append(True if due else 0)
            elif due:
                reviewed, interval = col.db.all(
                    "select id/1000.0, ivl from revlog where cid = ?", cid,
                )[-1]
                result.append(bool(col.find_cards(f"cid:{cid} is:due")) if interval >= -1200
                              else reviewed - interval <= time.time())
            else:
                history = col.db.list("select ivl from revlog where cid = ?", cid)
                result.append(history if complete else history[-1])
        return result
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_query_op
def reviews_for_raw_ids(col, ids):
    """Keep SQL batching, raw map keys and key collisions from getReviewsOfCards."""
    from .reviews import COLUMNS

    keys = COLUMNS[:1] + COLUMNS[2:]
    try:
        reviews = {}
        for offset in range(0, len(ids), 999):
            batch = ids[offset:offset + 999]
            rows = col.db.all(
                "select cid, " + ", ".join(keys) + " from revlog where cid in ("
                + ",".join("?" for _ in batch) + ")", *batch,
            )
            for cid, *row in rows:
                reviews.setdefault(cid, []).append(dict(zip(keys, row)))
        return {cid: reviews.get(cid, []) for cid in ids}
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def set_raw_ease_factors(col, cards, factors):
    """Apply legacy entries in order, reporting prior writes even if one fails.

    AnkiConnect skips undo entries, which also clears existing undo history.
    The native ease-factor writer intentionally keeps its own undo behavior.
    """
    result = []
    changes = None
    error = None
    try:
        for index, cid in enumerate(cards):
            try:
                card = col.get_card(cid)
            except Exception as exc:
                if type(exc).__name__ != "NotFoundError":
                    raise
                result.append(False)
                continue
            card.factor = factors[index]
            changes = col.update_card(card, skip_undo_entry=True)
            result.append(True)
    except Exception as exc:
        error = str(exc)
    # Let the operation publish earlier writes before the handler raises.
    value = (result, error)
    return ValueWithChanges(value, changes) if changes is not None else value


@as_query_op
def note_tags(col, note_id):
    """Read legacy tags without coercing the note ID or losing lookup errors."""
    try:
        return list(col.get_note(note_id).tags)
    except Exception as exc:
        if type(exc).__name__ == "NotFoundError":
            raise ValueError(f"Note was not found: {note_id}") from exc
        raise ValueError(str(exc)) from exc


@as_collection_op
def bulk_note_tags(col, notes, tags, add=True):
    """Keep legacy truthiness and let Anki validate the entire raw ID batch."""
    try:
        operation = col.tags.bulk_add if add else col.tags.bulk_remove
        changes = operation(notes, tags)
        return ValueWithChanges(None, changes)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def update_note_model_raw(col, spec):
    """Use AnkiConnect's validation, field reset and non-undoable model update."""
    try:
        nid = spec.get("id")
        if not nid:
            raise ValueError("Note ID is required")
        model_name = spec.get("modelName")
        if not model_name:
            raise ValueError("Model name is required")
        fields = spec.get("fields")
        if not fields or not isinstance(fields, dict):
            raise ValueError("Fields must be provided as a dictionary")
        note = col.get_note(nid)
        model = col.models.by_name(model_name)
        if not model:
            raise ValueError(f"Model '{model_name}' not found")
        note.mid = model["id"]
        note._fmap = col.models.field_map(model)
        note.fields = [""] * len(model["flds"])
        for name, value in fields.items():
            for model_field in note.keys():
                if name.lower() == model_field.lower():
                    note[model_field] = value
                    break
        note.tags = spec.get("tags", [])
        return ValueWithChanges(None, col.update_note(note, skip_undo_entry=True))
    except Exception as exc:
        if type(exc).__name__ == "NotFoundError":
            raise ValueError(f"Note was not found: {nid}") from exc
        raise ValueError(str(exc)) from exc


@as_collection_op
def create_model_raw(col, name, fields, templates, css, is_cloze):
    """Build through Anki's model manager without native API schema coercion."""
    try:
        if len(fields) == 0:
            raise ValueError("Must provide at least one field for inOrderFields")
        if len(templates) == 0:
            raise ValueError("Must provide at least one card for cardTemplates")
        models = col.models
        if name in [entry.name for entry in models.all_names_and_ids()]:
            raise ValueError("Model name already exists")
        model = models.new(name)
        if is_cloze:
            model["type"] = 1
        for field in fields:
            models.add_field(model, models.new_field(field))
        if css is not None:
            model["css"] = css
        for index, card in enumerate(templates, start=1):
            card_name = card["Name"] if "Name" in card else f"Card {index}"
            template = models.new_template(card_name)
            template["qfmt"] = card["Front"]
            template["afmt"] = card["Back"]
            models.add_template(model, template)
        result = models.add(model)
        return ValueWithChanges(model, result.changes)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def update_model_raw(col, spec, *, templates=False):
    """Edit the cached model and save once, preserving raw compatibility values."""
    try:
        name = spec["name"]
        model = col.models.by_name(name)
        if model is None:
            raise ValueError(f"model was not found: {name}")
        if templates:
            incoming = spec["templates"]
            for template in model["tmpls"]:
                supplied = incoming.get(template["name"])
                if supplied:
                    front = supplied.get("Front")
                    if front:
                        template["qfmt"] = front
                    back = supplied.get("Back")
                    if back:
                        template["afmt"] = back
        else:
            model["css"] = spec["css"]
        return ValueWithChanges(None, col.models.update_dict(model))
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _legacy_field_changes():
    """The legacy saving methods discard the backend's change report."""
    from anki.collection import OpChanges

    return OpChanges(notetype=True, note=True, card=True, browser_table=True,
                     browser_sidebar=True, note_text=True, study_queues=True, mtime=True)


@as_collection_op
def mutate_model_field_raw(col, model_name, action, name, value=None, index=None):
    """Follow the model manager's legacy field operations and save order."""
    changed = False
    try:
        models = col.models
        model = models.by_name(model_name)
        if model is None:
            raise ValueError(f"model was not found: {model_name}")
        result = None
        if action == "add":
            field_map = models.field_map(model)
            if name not in field_map:
                models.addField(model, models.new_field(name))
                changed = True
            if index is not None:
                field = models.field_map(model)[name][1]
                models.reposition_field(model, field, index)
        else:
            match = models.field_map(model).get(name)
            if match is None:
                raise ValueError(f"field was not found in {model_name}: {name}")
            field = match[1]
            if action == "rename":
                models.renameField(model, field, value)
                changed = True
            elif action == "reposition":
                models.reposition_field(model, field, index)
            elif action == "remove":
                models.remove_field(model, field)
            elif action == "font":
                if not isinstance(value, str):
                    raise ValueError(f"font should be a string: {value}")
                field["font"] = value
            elif action == "size":
                if not isinstance(value, int):
                    raise ValueError(f"fontSize should be an integer: {value}")
                field["size"] = value
            elif action == "description":
                if not isinstance(value, str):
                    raise ValueError(f"description should be a string: {value}")
                if "description" not in field:
                    return (False, None)
                field["description"] = value
                result = True
            else:
                raise ValueError(f"unknown field operation: {action}")
        changes = models.update_dict(model)
        if changed:
            # Legacy helpers save internally and discard their OpChanges. Include
            # their structural effects even when the final save is a no-op.
            changes.MergeFrom(_legacy_field_changes())
        return ValueWithChanges((result, None), changes)
    except Exception as exc:
        result = (None, str(exc))
        if changed:
            return ValueWithChanges(result, _legacy_field_changes())
        return result


@as_collection_op
def mutate_model_template_raw(col, model_name, action, name=None, value=None, index=None, spec=None):
    """Preserve raw template values and upstream's unsaved existing-template path."""
    try:
        models = col.models
        model = models.by_name(model_name)
        if model is None:
            raise ValueError(f"model was not found: {model_name}")
        if action == "add":
            name, front, back = spec["Name"], spec["Front"], spec["Back"]
            for template in model["tmpls"]:
                if template["name"] == name:
                    template["qfmt"], template["afmt"] = front, back
                    return (None, None)
            template = models.new_template(name)
            template["qfmt"], template["afmt"] = front, back
            models.add_template(model, template)
        else:
            template = next((t for t in model["tmpls"] if t["name"] == name), None)
            if template is None:
                raise ValueError(f"template was not found in {model_name}: {name}")
            if action == "rename":
                template["name"] = value
            elif action == "reposition":
                models.reposition_template(model, template, index)
            elif action == "remove":
                models.remove_template(model, template)
            else:
                raise ValueError(f"unknown template operation: {action}")
        return ValueWithChanges((None, None), models.update_dict(model))
    except Exception as exc:
        return (None, str(exc))
