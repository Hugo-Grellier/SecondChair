"""The cited rule lookup reads the offline compendium snapshot (#193 D6a). Invented data only."""

from pathlib import Path

import pytest

from secondchair.cli import main
from secondchair.core import calls, delegation, rules
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
    delegation.start_session(ws)
    with delegation.locked(ws):
        call = calls.open_call(
            ws,
            kind="discrepancy",
            responsibility=rules.RESPONSIBILITY,
            table_moment=delegation.current_moment(ws)[0],
            blocking=False,
            message="m",
            check="degree",
        )
    rules.mark_intended(ws, call["id"], "Fast stride", "cli", True)

    found = lookup_rule(ws, query="invented-stride")

    assert found["translation"] is None and found["entries"][0]["translation"] is None
    assert "Fast stride" in found["house_rule_notice"]


def test_a_blank_query_is_refused_and_a_missing_name_is_skipped(ws: Workspace) -> None:
    compendium.store(ws, snapshot(None))
    for blank in ("", "  "):
        with pytest.raises(ValueError, match="must not be empty"):
            lookup_rule(ws, query=blank)
    (ws.root / rules.HOUSE_RULES_FILE).write_text("house_rules:\n- check: degree\n")

    assert lookup_rule(ws, query="stride")["house_rule_notice"] is None


def test_no_match_exact_uuid_and_limit_clamp(ws: Workspace) -> None:
    payload = snapshot(None)
    more = [
        {**payload["entries"][0], "uuid": f"Compendium.sys.actions.Item.b{i}"} for i in range(3)
    ]
    payload["entries"] += more
    compendium.store(ws, payload)

    assert lookup_rule(ws, query="zzz")["entries"] == []
    [by_uuid] = lookup_rule(ws, query="Compendium.sys.actions.Item.b1")["entries"]
    assert by_uuid["uuid"] == "Compendium.sys.actions.Item.b1"
    assert len(lookup_rule(ws, query="stride", limit=2)["entries"]) == 2
    assert len(lookup_rule(ws, query="stride", limit=0)["entries"]) == 1  # clamped to 1
    assert len(lookup_rule(ws, query="stride", limit=1000)["entries"]) == 4  # clamped to 100
