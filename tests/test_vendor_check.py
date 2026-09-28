"""Another add-on's copy of Tsunagi's web stack (backlog 8.3a)."""
import types

import pytest

from tsunagi.vendor_check import (
    Clash,
    addon_folder,
    bundled_versions,
    find_clashes,
    refusal,
)


@pytest.fixture()
def world(tmp_path):
    shared = tmp_path / "tsunagi" / "lib" / "shared"
    for pkg, version in (("pydantic", "1.10.22"), ("fastapi", "0.125.0"), ("attrs", "25.1.0")):
        (shared / pkg).mkdir(parents=True)
        (shared / f"{pkg}-{version}.dist-info").mkdir()
    addons = tmp_path / "addons21"
    anki = tmp_path / "anki_bundle"

    def module(where, version):
        m = types.ModuleType("m")
        m.__file__ = str(where / "__init__.py")
        m.__version__ = version
        return m
    return shared, addons, anki, module


def test_bundled_versions_come_from_dist_info(world):
    shared, *_ = world
    assert bundled_versions(shared) == {"pydantic": "1.10.22", "fastapi": "0.125.0", "attrs": "25.1.0"}


def test_a_different_web_stack_version_blocks(world):
    shared, addons, anki, module = world
    modules = {"pydantic": module(addons / "1234" / "vendor" / "pydantic", "2.9.0")}
    [clash] = find_clashes(shared, [str(anki)], modules)
    assert (clash.name, clash.version, clash.bundled, clash.blocks) == ("pydantic", "2.9.0", "1.10.22", True)


def test_same_version_other_libraries_and_ankis_own_copy_do_not_block(world):
    shared, addons, anki, module = world
    modules = {
        "fastapi": module(addons / "1234" / "fastapi", "0.125.0"),     # same version: works
        "attrs": module(addons / "1234" / "attrs", "21.0.0"),          # not part of the web stack
        "pydantic": module(anki / "pydantic", "2.9.0"),                # Anki's own bundle
    }
    clashes = find_clashes(shared, [str(anki)], modules)
    assert {c.name for c in clashes} == {"fastapi", "attrs"}
    assert not any(c.blocks for c in clashes)


def test_our_own_copy_is_not_a_clash(world):
    shared, _, anki, module = world
    assert find_clashes(shared, [str(anki)], {"pydantic": module(shared / "pydantic", "1.10.22")}) == []


def test_the_message_names_the_add_on(world, tmp_path):
    _, addons, _, _ = world
    file = str(addons / "1234" / "vendor" / "pydantic" / "__init__.py")
    assert addon_folder(file, str(addons)) == "1234"
    assert addon_folder(str(tmp_path / "elsewhere.py"), str(addons)) is None
    message = refusal([Clash("pydantic", file, "2.9.0", "1.10.22")],
                      lambda f: "Other Add-on" if addon_folder(f, str(addons)) else None)
    assert message.startswith("Tsunagi did not start")
    assert "pydantic (version 2.9.0, from the add-on “Other Add-on”; Tsunagi needs 1.10.22)" in message
