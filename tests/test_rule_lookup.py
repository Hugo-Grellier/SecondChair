"""The cited rule lookup reads the offline compendium snapshot (#193 D6a). Invented data only."""

from pathlib import Path

import pytest

from secondchair.cli import main
from secondchair.core import rules
from secondchair.core.workspace import Workspace, load
from secondchair_foundry import compendium
from secondchair_foundry.tools import BLOCK


def snapshot(translation: str | None) -> dict:
    entry = {
        "uuid": "Compendium.sys.actions.Item.a1",
        "slug": "invented-stride",
        "name": "Invented Stride",
        "type": "action",
        "pack": "sys.actions",
        "level": None,
        "rarity": "common",
        "traits": ["move"],
        "publication": "Invented Core",
        "remaster": True,
        "description": "PRIVATE TEXT",
    }
    system = {"id": "sys", "version": "7.1.0", "translation": translation}
    return {"system": system, "entries": [entry]}


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path / "c"), "--language", "fr", "--calendar", "absalom"])
    return load(tmp_path / "c")


def lookup_rule(ws: Workspace, **kw):
    [fn] = [t.fn for t in BLOCK.tools(ws) if t.name == "lookup_rule"]
    return fn(**kw)


def test_no_snapshot_is_an_error(ws: Workspace) -> None:
    with pytest.raises(ValueError, match="No compendium snapshot"):
        lookup_rule(ws, query="stride")


def test_entry_is_cited_with_uuid_version_and_translation_offline(ws: Workspace) -> None:
    compendium.store(ws, snapshot("Traduction"))

    found = lookup_rule(ws, query="STRIDE")

    assert found["system_version"] == "7.1.0" and found["translation"] == "Traduction"
    assert found["house_rule_notice"] is None
    [e] = found["entries"]
    assert (e["uuid"], e["system_version"], e["translation"], e["publication"]) == (
        "Compendium.sys.actions.Item.a1",
        "7.1.0",
        "Traduction",
        "Invented Core",
    )
    assert "PRIVATE TEXT" not in str(found)
    assert lookup_rule(ws, query="stride", type="Actor")["entries"] == []


def test_no_translation_module_is_null_and_house_rules_raise_a_notice(ws: Workspace) -> None:
    compendium.store(ws, snapshot(None))
    rules._write_rules(ws, [{"name": "Fast stride", "check": "x", "call": 1, "at": "t"}])

    found = lookup_rule(ws, query="invented-stride")

    assert found["translation"] is None and found["entries"][0]["translation"] is None
    assert "Fast stride" in found["house_rule_notice"]
