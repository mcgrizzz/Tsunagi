"""Shared fixtures and comparisons for opt-in AnkiConnect differential tests.

Import fixtures explicitly (``from upstream_support import pair as pair``) in each
suite. Keep action-specific setup and normalization with that action's tests.
"""

import copy
import json
import os
import sqlite3

import pytest

from tools.upstream_reference import load_reference
from tsunagi.http.compat.ankiconnect import handle_ankiconnect_rpc


@pytest.fixture(scope="module")
def upstream():
    checkout = os.environ.get("TSUNAGI_ANKICONNECT_CHECKOUT")
    if not checkout:
        pytest.skip("Set TSUNAGI_ANKICONNECT_CHECKOUT to run upstream comparisons")
    return load_reference(checkout)


@pytest.fixture()
def pair(col, client, tmp_path, upstream):
    from anki.collection import Collection

    model = col.models.by_name("Basic")
    deck = col.decks.id("Parity::日本語")
    for front, back, tags in [
        ("alpha", "one", ["root::child"]),
        ("beta", "two", ["other"]),
        ("gamma", "three", []),
    ]:
        note = col.new_note(model)
        note["Front"], note["Back"], note.tags = front, back, tags
        col.add_note(note, deck)
    reference_path = tmp_path / "reference.anki2"
    with sqlite3.connect(col.path) as source, sqlite3.connect(reference_path) as target:
        source.backup(target)
    reference_col = Collection(str(reference_path))
    upstream.collection = lambda: reference_col
    try:
        yield col, reference_col, upstream
    finally:
        reference_col.close()


def compare(pair, action, params=None, version=6):
    _, _, upstream = pair
    request = {"action": action, "version": version, "params": params or {}}
    reference_request = copy.deepcopy(request)
    if action == "requestPermission":
        # Match upstream's HTTP injection for a request without an Origin.
        reference_request["params"].update(origin="", allowed=True)
    expected = upstream.handler(reference_request)
    actual = handle_ankiconnect_rpc(copy.deepcopy(request))
    # JSON round trip reflects wire types (e.g. tuple/list, integer map keys).
    actual, expected = json.loads(json.dumps(actual)), json.loads(json.dumps(expected))
    if action == "getDeckStats":
        normalize_deck_stats(actual, pair[0])
        normalize_deck_stats(expected, pair[1])
    assert actual == expected, first_difference(actual, expected)
    return actual


def normalize_deck_stats(reply, collection):
    """Compare all stats, replacing independently allocated deck IDs by names."""
    if not isinstance(reply["result"], dict):
        return
    normalized = {}
    for did, row in reply["result"].items():
        full_name = collection.decks.get(int(did))["name"]
        row = dict(row)
        if "deck_id" in row:
            row["deck_id"] = full_name
        normalized[full_name] = row
    reply["result"] = normalized


def first_difference(actual, expected, path="response"):
    if type(actual) is not type(expected):
        return f"{path}: shim={actual!r}; upstream={expected!r}"[:1000]
    if isinstance(actual, dict):
        if actual.keys() != expected.keys():
            return f"{path} keys: shim={list(actual)}; upstream={list(expected)}"
        for key in actual:
            if actual[key] != expected[key]:
                return first_difference(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path} length: shim={len(actual)}; upstream={len(expected)}"
        for index, (left, right) in enumerate(zip(actual, expected)):
            if left != right:
                return first_difference(left, right, f"{path}[{index}]")
    return f"{path}: shim={actual!r}; upstream={expected!r}"[:1000]

