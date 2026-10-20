"""Entity overrides (DEL-10..17): a lower level for one acting entity."""

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import jsonschema
import pytest
import yaml
from mcp import Client

from secondchair import cli
from secondchair.cli import main
from secondchair.core import calls, delegation, jobs, workspace
from secondchair.core.delegation import DelegationError
from secondchair.core.server import build_server
from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import Workspace

CONTRACTS = Path(__file__).parents[1] / "docs/contracts"
SCHEMAS = {
    d: json.loads((CONTRACTS / f"{s}.schema.json").read_text())
    for d, s in (("action-log", "action-log-entry"), ("calls", "call"), ("jobs", "job"))
}
EZREN, ADA = "e-11111111", "e-22222222"


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path), "--language", "fr", "--calendar", "absalom"])
    for entity in (EZREN, ADA):
        path = tmp_path / "canon/entities" / f"{entity}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nid: {entity}\nnames: [{entity}]\n---\n")
    return workspace.load(tmp_path)


def records(ws: Workspace, directory: str) -> list[dict]:
    found = [yaml.safe_load(p.read_text()) for p in sorted((ws.root / directory).glob("*.yaml"))]
    for record in found:
        jsonschema.validate(record, SCHEMAS[directory])
    return found


def set_level(ws: Workspace, responsibility: str, level: str) -> None:
    path = ws.root / delegation.TABLE_FILE
    table = yaml.safe_load(path.read_text())
    table["prep"][responsibility]["level"] = level
    path.write_text(yaml.safe_dump(table, sort_keys=False))


def speak(ws: Workspace, entity: str | None, line: str = "Bonjour.", reversible: bool = True):
    """An NPC line by `entity`, under npcs (a stand-in for a block's tool)."""

    def say(text: str) -> Change:
        return Change(path=f"lines/{text}.md", after=text, entity=entity)

    tool = Tool(fn=say, responsibility="npcs", delegated_action=True, reversible=reversible)
    return delegation.act(ws, tool, "claude", lambda: say(line))


def gm(*argv: str, root: Path, interactive: bool = True) -> int:
    with patch.object(cli, "interactive", return_value=interactive):
        return main([*argv, "--workspace", str(root)])


def add(ws: Workspace, entity: str, level: str, moment: str | None = None, **kw: Any) -> dict:
    return delegation.add_override(ws, entity, "npcs", level, moment, "cli", True, **kw)


def test_an_override_lowers_the_acting_entitys_level_and_the_log_records_it(
    ws: Workspace,
) -> None:
    set_level(ws, "npcs", "act-then-review")
    add(ws, EZREN, "propose")

    assert speak(ws, EZREN, "un") == {"entry": 2, "status": "pending"}
    assert speak(ws, ADA, "deux") == {"entry": 3, "status": "applied"}
    assert speak(ws, None, "trois") == {"entry": 4, "status": "applied"}  # DEL-10
    lowered, other, unacted = (e for e in records(ws, "action-log") if e["kind"] == "action")
    assert (lowered["effective_level"], lowered["override_lowered"]) == ("propose", True)
    assert (lowered["entity"], other["entity"], unacted["entity"]) == (EZREN, ADA, None)
    assert (other["override_lowered"], unacted["override_lowered"]) == (False, False)


def test_an_override_at_manual_refuses_the_entitys_actions(ws: Workspace) -> None:
    add(ws, EZREN, "manual")
    with pytest.raises(DelegationError, match="override sets npcs at manual"):
        speak(ws, EZREN)
    assert not (ws.root / "lines").exists()


def test_an_override_restricted_to_a_moment_applies_only_there(ws: Workspace) -> None:
    set_level(ws, "npcs", "act-then-review")
    add(ws, EZREN, "manual", "live-session")
    assert speak(ws, EZREN)["status"] == "applied"
    level = delegation.effective_level(ws, "npcs", "live-session", True, EZREN)
    assert level == "manual"


def test_the_irreversible_hold_still_applies_on_top(ws: Workspace) -> None:
    set_level(ws, "npcs", "autonomous")
    add(ws, EZREN, "act-then-review")
    assert delegation.effective_level(ws, "npcs", "prep", False, EZREN) == "propose"
    assert delegation.effective_level(ws, "npcs", "prep", True, EZREN) == "act-then-review"


def test_adding_never_loosens_an_existing_override(ws: Workspace) -> None:
    add(ws, EZREN, "manual")
    entry = add(ws, EZREN, "act-then-review")
    assert entry["override"]["level"] == "manual"
    assert delegation.overrides(ws) == [
        {"entity": EZREN, "responsibility": "npcs", "level": "manual", "moment": None}
    ]


@pytest.mark.parametrize(
    "responsibility", ["prep", "memory", "vtt_operations", "living_world", "narrative_direction"]
)
def test_an_override_outside_npcs_rules_and_disclosure_is_refused(
    ws: Workspace, responsibility: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(DelegationError, match="takes no entity override"):
        delegation.add_override(ws, EZREN, responsibility, "manual", None, "cli", True)
    assert gm("override", "add", EZREN, responsibility, "manual", root=ws.root) == 1
    assert "takes no entity override" in capsys.readouterr().err
    assert delegation.overrides(ws) == []


def test_an_override_needs_an_entity_in_canon(ws: Workspace) -> None:
    with pytest.raises(DelegationError, match="No entity"):
        add(ws, "e-99999999", "manual")


def test_an_agent_relay_adds_an_override_but_cannot_remove_one(ws: Workspace) -> None:
    async def relay() -> Any:
        async with Client(build_server(ws)) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert "add_entity_override" in names
            assert not any("remove" in n and "override" in n for n in names)
            args = {"entity": EZREN, "responsibility": "disclosure", "level": "manual"}
            return await client.call_tool(
                "add_entity_override", {**args, "gm_words": "Je joue Ezren moi-même."}
            )

    result = asyncio.run(relay())
    assert result.structured_content["entry"] == 1
    [interaction] = records(ws, "action-log")
    assert (interaction["interaction"], interaction["channel"]) == ("add_override", "via agent")
    assert interaction["quote"] == "Je joue Ezren moi-même."

    with pytest.raises(DelegationError, match="authenticated Surface"):
        delegation.remove_override(ws, EZREN, "disclosure", None, "via agent", False)
    assert gm("override", "remove", EZREN, "disclosure", root=ws.root, interactive=False) == 1
    assert len(delegation.overrides(ws)) == 1

    assert gm("override", "remove", EZREN, "disclosure", root=ws.root) == 0
    assert delegation.overrides(ws) == []
    removed = records(ws, "action-log")[-1]
    assert (removed["interaction"], removed["authenticated"]) == ("remove_override", True)


def test_the_cli_adds_an_override_from_any_terminal(ws: Workspace) -> None:
    argv = ("override", "add", EZREN, "rules_and_combat", "propose", "--moment", "live-session")
    assert gm(*argv, root=ws.root, interactive=False) == 0
    assert delegation.overrides(ws) == [
        {
            "entity": EZREN,
            "responsibility": "rules_and_combat",
            "level": "propose",
            "moment": "live-session",
        }
    ]


def test_an_override_withdraws_the_entitys_pending_calls_and_queued_jobs(
    ws: Workspace,
) -> None:
    speak(ws, EZREN, "un")  # npcs at propose in prep: a pending call
    speak(ws, ADA, "deux")

    def queue(responsibility: str) -> dict:
        return jobs.queue(
            ws,
            playbook="voice-an-npc",
            inputs={},
            expected_output="A line.",
            responsibility=responsibility,
            tier="fast",
            entity=EZREN,
        )

    job, other_job = queue("npcs"), queue("disclosure")

    interaction = add(ws, EZREN, "manual")

    ezren_call, ada_call = records(ws, "calls")
    assert (ezren_call["status"], ada_call["status"]) == ("withdrawn", "open")
    assert delegation.read_entry(ws, ezren_call["entry"])["status"] == "rejected"
    statuses = [j["status"] for j in records(ws, "jobs")]
    assert statuses == ["withdrawn", "queued"]  # disclosure is not overridden
    defaults = [e for e in records(ws, "action-log") if e["kind"] == "safe_default"]
    assert [(d["call"], d["job"], d["override"]) for d in defaults] == [
        (None, job["id"], interaction["id"]),
        (ezren_call["id"], None, interaction["id"]),
    ]
    assert other_job["id"] not in [d["job"] for d in defaults]
    assert calls.take_break(ws) == [ada_call]  # not shown at the break


def test_merging_two_entities_keeps_the_most_restrictive_override(ws: Workspace) -> None:
    add(ws, EZREN, "propose")
    add(ws, ADA, "manual")
    add(ws, ADA, "propose", "live-session")
    delegation.add_override(ws, EZREN, "disclosure", "act-then-review", None, "cli", True)

    delegation.merge_overrides(ws, survivor=EZREN, merged=ADA)

    assert sorted(
        (o["responsibility"], o["moment"] or "", o["level"]) for o in delegation.overrides(ws)
    ) == [
        ("disclosure", "", "act-then-review"),
        ("npcs", "", "manual"),
        ("npcs", "live-session", "propose"),
    ]
    assert {o["entity"] for o in delegation.overrides(ws)} == {EZREN}


def test_check_reports_a_malformed_override(ws: Workspace) -> None:
    path = ws.root / delegation.TABLE_FILE
    table = yaml.safe_load(path.read_text())
    table["overrides"] = [{"entity": EZREN, "responsibility": "prep", "level": "manual"}]
    path.write_text(yaml.safe_dump(table))
    assert any("overrides" in e for e in delegation.check(ws))
