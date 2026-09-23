#!/usr/bin/env python3
"""Report Anki API availability in this interpreter, without opening a collection.

Run in each isolated Anki environment; this probes the installed wheel, not the
Python/Qt bundled by a desktop installer. Presence does not establish semantics
or a deprecation guarantee. Use the ordinary test suite for behavioral checks.
"""

from __future__ import annotations

import argparse
import inspect
import json
import platform
from importlib import metadata
from pathlib import Path


def package_info(name):
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    return {"version": dist.version, "requires_python": dist.metadata.get("Requires-Python")}


def method_info(owner, names):
    result = {}
    for name in names:
        method = getattr(owner, name, None)
        result[name] = str(inspect.signature(method)) if callable(method) else None
    return result


def message_fields(descriptor):
    """Include nested protobuf messages, where deck config fields may live."""
    result = {descriptor.full_name: [field.name for field in descriptor.fields]}
    for child in descriptor.nested_types:
        result.update(message_fields(child))
    return result


def probe():
    from anki import cards_pb2, deck_config_pb2
    from anki._backend import RustBackend
    from anki.collection import Collection

    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {name: package_info(name) for name in ("anki", "aqt", "PyQt6", "PyQt6-Qt6")},
        "collection": method_info(Collection, (
            "fsrs_enabled", "get_config_bool", "get_config", "find_cards", "sync_status",
            "export_anki_package", "import_anki_package", "get_scheduling_states",
        )),
        "backend": method_info(RustBackend, (
            "fsrs_enabled", "fsrs_reschedule", "get_scheduling_states_inner",
            "get_scheduling_states", "render_uncommitted_card", "sync_status",
            "get_import_anki_package_presets", "update_deck_configs",
            "compute_fsrs_weights", "compute_fsrs_params",
            "evaluate_weights", "evaluate_params", "evaluate_params_legacy", "simulate_fsrs_review",
            "simulate_fsrs_workload", "compute_optimal_retention", "get_notetype_legacy",
        )),
        "card_fields": [field.name for field in cards_pb2.Card.DESCRIPTOR.fields],
        "deck_config_fields": message_fields(deck_config_pb2.DeckConfig.DESCRIPTOR),
        "update_deck_config_fields": message_fields(deck_config_pb2.UpdateDeckConfigsRequest.DESCRIPTOR),
    }
    if report["packages"]["aqt"]:
        from aqt.addons import AddonManager

        report["addon_manager"] = method_info(AddonManager, ("get_logger", "logs_folder"))
    else:
        report["addon_manager"] = None
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    args = parser.parse_args()
    encoded = json.dumps(probe(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
