"""
Keeps docs/ankiconnect_parity.md honest.

The doc is the parity claim; the registry is the truth. Checking both
directions means a new action can't ship undocumented, and the doc can't claim
an action that isn't wired up.
"""
import re
from pathlib import Path

import pytest

from tsunagi.http.compat import actions  # noqa: F401  (registers the handlers)
from tsunagi.http.compat.ankiconnect import get_available_actions

DOC = Path(__file__).resolve().parent.parent / "docs" / "ankiconnect_parity.md"
ROW = re.compile(r"^\|\s*`([A-Za-z]+)`\s*\|\s*([A-Za-z0-9-]+)\s*\|(.*)\|\s*$")

# Every action upstream exposes, per the @util.api() decorators in
# plugin/__init__.py at de6e6e1b. Not the README, which omits six of them.
UPSTREAM_TOTAL = 122
VALID_STATUSES = {"implemented", "M6", "out-of-scope"}


@pytest.fixture(scope="module")
def rows():
    parsed = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            parsed.append((match.group(1), match.group(2).strip(), match.group(3).strip()))
    return parsed


def test_doc_exists_and_parses(rows):
    assert rows, f"no action rows parsed out of {DOC}"


def test_covers_every_upstream_action(rows):
    assert len(rows) == UPSTREAM_TOTAL


def test_no_duplicate_rows(rows):
    names = [name for name, _status, _notes in rows]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"listed more than once: {sorted(duplicates)}"


def test_statuses_are_known(rows):
    unknown = {status for _name, status, _notes in rows if status not in VALID_STATUSES}
    assert not unknown, f"unknown status values: {sorted(unknown)}"


def test_every_registered_action_is_documented_as_implemented(rows):
    documented = {name for name, status, _ in rows if status == "implemented"}
    registered = set(get_available_actions()["actions"])
    missing = registered - documented
    assert not missing, (
        f"registered but not documented as implemented: {sorted(missing)} - "
        f"add them to {DOC.name}"
    )


def test_every_implemented_row_is_registered(rows):
    documented = {name for name, status, _ in rows if status == "implemented"}
    registered = set(get_available_actions()["actions"])
    phantom = documented - registered
    assert not phantom, (
        f"documented as implemented but not registered: {sorted(phantom)} - "
        f"the parity claim is wrong"
    )


def test_header_counts_match_the_table(rows):
    text = DOC.read_text(encoding="utf-8")
    counts = {status: sum(1 for _n, s, _x in rows if s == status)
              for status in VALID_STATUSES}
    for label, status in (("Implemented", "implemented"),
                          ("Planned (M6)", "M6"),
                          ("Out of scope", "out-of-scope")):
        stated = re.search(rf"\| {re.escape(label)} \| \*\*(\d+)\*\* \|", text)
        assert stated, f"summary row for {label!r} not found"
        assert int(stated.group(1)) == counts[status], (
            f"{label}: header says {stated.group(1)}, table has {counts[status]}"
        )


def test_out_of_scope_rows_give_a_reason(rows):
    for name, status, notes in rows:
        if status == "out-of-scope":
            assert notes, f"{name} is out of scope with no reason given"
