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
