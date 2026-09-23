"""Package compatibility across Anki's old implementation and replacement API."""

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from zipfile import ZipFile

import pytest

from tsunagi.adapters.anki import compat


@pytest.mark.parametrize("module_name,class_name", [
    ("anki.exporting", "AnkiPackageExporter"),
    ("anki.importing", "AnkiPackageImporter"),
])
def test_package_detection_does_not_resolve_deprecated_alias(monkeypatch, module_name, class_name):
    module = ModuleType(module_name)

    def forbidden_alias(name):
        raise AssertionError(f"Deprecated alias accessed: {name}")

    module.__getattr__ = forbidden_alias
    monkeypatch.setitem(sys.modules, module_name, module)
    assert compat._legacy_package_class(module_name, class_name) is None

    original_class = object()
    setattr(module, class_name, original_class)
    assert compat._legacy_package_class(module_name, class_name) is original_class


def test_removed_package_module_can_use_backend(monkeypatch):
    monkeypatch.setitem(sys.modules, "anki.exporting", None)
    assert compat._legacy_package_class("anki.exporting", "AnkiPackageExporter") is None


def test_broken_package_dependency_is_not_hidden(monkeypatch):
    def broken_import(name):
        raise ModuleNotFoundError("Missing dependency", name="some_dependency")

    monkeypatch.setattr(importlib, "import_module", broken_import)
    with pytest.raises(ModuleNotFoundError, match="Missing dependency"):
        compat._legacy_package_class("anki.exporting", "AnkiPackageExporter")


@pytest.fixture
def modern_package_api(monkeypatch):
    # Exercise future removal of both legacy modules, even on older test wheels.
    # These option objects have the same relevant public shape as Anki's proto.
    module = ModuleType("anki.import_export_pb2")
    module.ExportAnkiPackageOptions = SimpleNamespace
    module.ImportAnkiPackageOptions = SimpleNamespace
    module.ImportAnkiPackageRequest = SimpleNamespace
    monkeypatch.setitem(sys.modules, "anki.import_export_pb2", module)
    monkeypatch.setitem(sys.modules, "anki.exporting", None)
    monkeypatch.setitem(sys.modules, "anki.importing", None)


@pytest.mark.parametrize("scheduling", [False, True])
def test_modern_compat_export_keeps_legacy_format_and_preset_policy(modern_package_api, scheduling):
    pytest.importorskip("anki.collection")
    calls = []

    def export(*, out_path, options, limit):
        calls.append((out_path, options, limit))

    col = SimpleNamespace(
        decks=SimpleNamespace(by_name=lambda name: {"id": 42}),
        export_anki_package=export,
    )
    assert compat.export_package_legacy.__wrapped__(col, "Default", "out.apkg", scheduling) is True
    path, options, limit = calls[0]
    assert len(calls) == 1
    assert path == "out.apkg" and limit.deck_id == 42
    assert vars(options) == {
        "with_scheduling": scheduling, "with_media": True,
        "legacy": True, "with_deck_configs": scheduling,
    }


def test_modern_compat_import_uses_fixed_options_and_real_changes(modern_package_api):
    pytest.importorskip("anki.collection")
    requests = []
    changes = object()

    def import_package(request):
        requests.append(request)
        return SimpleNamespace(changes=changes)

    # No preferences backend: compatibility must not read saved native choices.
    col = SimpleNamespace(import_anki_package=import_package)
    result = compat.import_package_legacy.__wrapped__(col, "in.apkg")
    assert result.value is True and result.changes is changes
    assert len(requests) == 1 and requests[0].package_path == "in.apkg"
    assert vars(requests[0].options) == {
        "merge_notetypes": True, "with_scheduling": True, "with_deck_configs": True,
    }


def test_failed_modern_import_is_not_retried(modern_package_api):
    pytest.importorskip("anki.collection")
    calls = []

    def import_package(request):
        calls.append(request)
        raise RuntimeError("Invalid package")

    with pytest.raises(ValueError, match="^Invalid package$"):
        compat.import_package_legacy.__wrapped__(
            SimpleNamespace(import_anki_package=import_package), "bad.apkg")
    assert len(calls) == 1


@pytest.mark.parametrize("scheduling", [False, True])
def test_compat_package_round_trip_preserves_media_and_scheduling(client, col, tmp_path, scheduling):
    from test_v1_collection import add_note, rpc, seed

    seed(client)
    nid = add_note(client, '<img src="package-test.svg">')["id"]
    media = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    col.media.write_data("package-test.svg", media)
    card = col.get_card(col.card_ids_of_note(nid)[0])
    card.type = card.queue = 2
    card.ivl = 17
    card.due = 30
    col.update_card(card)
    path = tmp_path / "compat.apkg"
    assert rpc(client, "exportPackage", {
        "deck": "JP", "path": str(path), "includeSched": scheduling,
    }) == {"result": True, "error": None}
    with ZipFile(path) as package:
        assert "collection.anki21b" not in package.namelist()
        assert "collection.anki2" in package.namelist()
    col.remove_notes(col.find_notes("deck:JP"))
    media_path = Path(col.media.dir()) / "package-test.svg"
    media_path.unlink()
    assert rpc(client, "importPackage", {"path": str(path)}) == {"result": True, "error": None}
    assert len(col.find_notes("deck:JP")) == 3
    assert media_path.read_bytes() == media
    restored = col.get_card(col.card_ids_of_note(nid)[0])
    assert restored.ivl == (17 if scheduling else 0)
    assert restored.type == (2 if scheduling else 0)
    if compat._legacy_package_class("anki.importing", "AnkiPackageImporter") is None:
        assert col.undo_status().undo
        col.undo()
        assert col.find_notes("deck:JP") == []
