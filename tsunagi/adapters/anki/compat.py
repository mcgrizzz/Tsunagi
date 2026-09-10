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


@as_query_op
def read_models_raw(col, values, *, by_id=False):
    """Read each raw lookup in request order, retaining Anki's first error."""
    try:
        result = []
        lookup = col.models.get if by_id else col.models.by_name
        for value in values:
            model = lookup(value)
            if model is None:
                raise ValueError(f"model was not found: {value}")
            # A later action in multi can modify an earlier lookup's result
            # through this cached object before the whole batch is serialized.
            result.append(model)
        return result
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def replace_in_models_raw(col, name, find, replacement, front=True, back=True, css=True):
    """Keep raw truthiness, per-model saves, and successful prefixes on failure."""
    from anki.collection import OpChanges

    changes = OpChanges()
    saved = False
    try:
        models = col.models
        if not name:
            names = models.allNames()
        else:
            if models.by_name(name) is None:
                raise ValueError(f"model was not found: {name}")
            names = [name]
        updated = 0
        for model_name in names:
            model = models.by_name(model_name)
            found = False
            if css and find in model["css"]:
                found = True
                model["css"] = model["css"].replace(find, replacement)
            for template in model.get("tmpls"):
                if front and find in template["qfmt"]:
                    found = True
                    template["qfmt"] = template["qfmt"].replace(find, replacement)
                if back and find in template["afmt"]:
                    found = True
                    template["afmt"] = template["afmt"].replace(find, replacement)
            changes.MergeFrom(models.update_dict(model))
            saved = True
            updated += found
        return ValueWithChanges((updated, None), changes)
    except Exception as exc:
        result = (None, str(exc))
        return ValueWithChanges(result, changes) if saved else result


@as_collection_op
def reschedule_cards_raw(col, cards, action, days=None):
    """Let each upstream scheduling path interpret its raw inputs directly."""
    try:
        if action == "forget":
            from anki.scheduler_pb2 import ScheduleCardsAsNewRequest

            changes = col._backend.schedule_cards_as_new(ScheduleCardsAsNewRequest(
                card_ids=cards, log=True, restore_position=True,
                reset_counts=False, context=None,
            ))
        elif action == "relearn":
            from anki.utils import ids2str

            col.db.execute("update cards set type=3, queue=1 where id in " + ids2str(cards))
            return None
        elif action == "due":
            changes = col.sched.set_due_date(cards, days, config_key=None)
        else:
            raise ValueError(f"unknown scheduling action: {action}")
        return ValueWithChanges(None, changes.changes if hasattr(changes, "changes") else changes)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_query_op
def read_suspended_raw(col, cards, *, missing_ok=False):
    """Keep raw card lookup errors and the unsaved-card behavior of ID zero."""
    from anki.errors import NotFoundError

    try:
        result = []
        for cid in cards:
            try:
                result.append(col.get_card(cid).queue == -1)
            except NotFoundError as exc:
                if not missing_ok:
                    raise ValueError(f"Card was not found: {cid}") from exc
                result.append(None)
        return result
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def suspend_cards_raw(col, cards, suspend=True):
    """Visit and remove raw entries in upstream order before scheduling the rest."""
    from anki.errors import NotFoundError

    try:
        for cid in cards:
            try:
                state = col.get_card(cid).queue == -1
            except NotFoundError as exc:
                raise ValueError(f"Card was not found: {cid}") from exc
            if state == suspend:
                cards.remove(cid)
        if len(cards) == 0:
            return False
        changes = (col.sched.suspend_cards(cards) if suspend
                   else col.sched.unsuspend_cards(cards))
        return ValueWithChanges(True, changes.changes if hasattr(changes, "changes") else changes)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def answer_cards_raw(col, answers):
    """Answer in request order, retaining saved prefixes and their notifications."""
    from anki.collection import OpChanges
    from anki.errors import NotFoundError

    changes = OpChanges()
    saved = False
    result = []
    try:
        for answer in answers:
            try:
                cid = answer["cardId"]
                ease = answer["ease"]
                card = col.get_card(cid)
                card.start_timer()
                change = col.sched.answerCard(card, ease)
                if change is not None:
                    changes.MergeFrom(change.changes if hasattr(change, "changes") else change)
                saved = True
                result.append(True)
            except NotFoundError:
                result.append(False)
        value = (result, None)
    except Exception as exc:
        value = (None, str(exc))
    return ValueWithChanges(value, changes) if saved else value


@as_query_op
def read_ease_factors_raw(col, cards):
    """Preserve raw card lookup behavior and missing-card result positions."""
    from anki.errors import NotFoundError

    try:
        result = []
        for cid in cards:
            try:
                result.append(col.get_card(cid).factor)
            except NotFoundError:
                result.append(None)
        return result
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_query_op
def notes_of_cards_raw(col, cards):
    """Use upstream's integer conversion and one SQL query for distinct notes."""
    from anki.utils import ids2str

    try:
        return col.db.list("select distinct nid from cards where id in " + ids2str(cards))
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_query_op
def export_package_legacy(col, deck_name, path, include_sched=False):
    """Use AnkiConnect's exporter, including its version-specific package rules."""
    try:
        deck = col.decks.by_name(deck_name)
        if deck is None:
            return False
        from anki.exporting import AnkiPackageExporter

        exporter = AnkiPackageExporter(col)
        exporter.did = deck["id"]
        exporter.includeSched = include_sched
        exporter.exportInto(path)
        return True
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def import_package_legacy(col, path):
    """Use the supported legacy importer and refresh views after it completes."""
    from anki.collection import OpChanges

    try:
        from anki.importing import AnkiPackageImporter

        AnkiPackageImporter(col, path).run()
        # The legacy API discards backend change metadata. Import may alter
        # notes, models, scheduling, decks and presets, so refresh those views.
        return ValueWithChanges(True, OpChanges(
            card=True, note=True, notetype=True, deck=True, deck_config=True,
            tag=True, mtime=True, browser_table=True, browser_sidebar=True,
            note_text=True, study_queues=True,
        ))
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_query_op
def get_deck_config_legacy(col, name):
    """Preserve raw legacy deck lookup and the complete returned configuration."""
    try:
        deck = next((deck for deck in col.decks.all_names_and_ids() if deck.name == name), None)
        if deck is None:
            return False
        return col.decks.config_dict_for_deck_id(deck.id)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@as_collection_op
def save_deck_config_legacy(col, config):
    """Keep lookup errors, then report rejected preset saves as False."""
    from anki.collection import OpChanges
    from anki.utils import int_time

    try:
        config_id = int(str(config["id"]))
        if config_id not in {preset["id"] for preset in col.decks.all_config()}:
            return False
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    try:
        config["mod"] = int_time()
        config["usn"] = col.usn()
        col.decks.save(config)
    except Exception:
        return False
    return ValueWithChanges(True, OpChanges(deck_config=True))
