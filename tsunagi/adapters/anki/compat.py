"""Collection reads whose observable quirks belong to AnkiConnect's contract."""

from ..ops import as_collection_op, as_query_op


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
