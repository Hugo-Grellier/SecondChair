"""The Director's Desk, Core side (ARC-12, ARC-14, DEL-03, DEL-03a, DEL-26, DEL-29): the state
the Core sends it and the gestures it relays (docs/contracts/foundry-bridge.md)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from mcp import Client

from secondchair.cli import main
from secondchair.core import delegation, workspace
from secondchair.core.server import build_server
from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import Workspace
from secondchair_foundry import desk

CONTRACTS = Path(__file__).parents[1] / "docs/contracts"
BRIDGE = json.loads((CONTRACTS / "foundry-bridge.schema.json").read_text())
LOG_SCHEMA = json.loads((CONTRACTS / "action-log-entry.schema.json").read_text())
GM_WORDS = {"kind": "gm", "words": "The bell tower fell in 4710."}


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path), "--language", "en", "--calendar", "absalom"])
    return workspace.load(tmp_path)


def call_tool(ws: Workspace, tool: str, **arguments: Any) -> Any:
    async def run() -> Any:
        async with Client(build_server(ws)) as client:
            return await client.call_tool(tool, {"agent": "claude-live", **arguments})

    return asyncio.run(run())


def gesture(ws: Workspace, name: str, **fields: Any) -> dict:
    message = {"type": "gesture", "id": "g1", "gesture": name, **fields}
    jsonschema.validate(message, BRIDGE)
    result = desk.take(ws, message)
    jsonschema.validate(result, BRIDGE)
    assert result["id"] == "g1"
    return result


def state(ws: Workspace) -> dict:
    found = desk.state(ws)
    jsonschema.validate(found, BRIDGE)
    return found


def entry(ws: Workspace, entry_id: int) -> dict:
    found = yaml.safe_load((ws.root / f"action-log/{entry_id:06d}.yaml").read_text())
    jsonschema.validate(found, LOG_SCHEMA)
    return found


def log(ws: Workspace) -> list[dict]:
    return [entry(ws, int(p.stem)) for p in sorted((ws.root / "action-log").glob("*.yaml"))]


def test_calls_due_now_appear_and_are_approved_from_the_desk(ws: Workspace) -> None:
    gesture(ws, "start_session")
    call_tool(ws, "create_entity", names=["Ada Fen"], blocking=True)
    call_tool(ws, "create_entity", names=["Bo Lark"])  # due at the break, not now

    [due] = state(ws)["calls"]
    assert (due["kind"], due["entry"], due["responsibility"]) == ("proposal", 1, "memory")
    assert "Ada Fen" in due["detail"] and due["reversible"] is True

    assert gesture(ws, "approve", entry=1)["ok"] is True
    assert state(ws)["calls"] == []
    approval = log(ws)[-1]
    assert (approval["interaction"], approval["channel"], approval["authenticated"]) == (
        "approve",
        "desk",
        True,
    )
    assert entry(ws, 1)["status"] == "applied"


def test_a_rejection_from_the_desk_carries_a_reason_from_the_closed_list(ws: Workspace) -> None:
    gesture(ws, "start_session")
    call_tool(ws, "create_entity", names=["Ada Fen"], blocking=True)

    off_list = {"type": "gesture", "id": "g1", "gesture": "reject", "entry": 1, "reason": "boring"}
    refused = desk.take(ws, off_list)  # the contract already refuses it; so does the Core
    assert refused["ok"] is False and "contradiction" in refused["error"]
    assert entry(ws, 1)["status"] == "pending"

    assert gesture(ws, "reject", entry=1, reason="tone")["ok"] is True
    assert entry(ws, 1)["status"] == "rejected"
    assert (log(ws)[-1]["reason"], log(ws)[-1]["channel"]) == ("tone", "desk")


def test_the_break_pile_is_shown_at_a_break_the_gm_signals(ws: Workspace) -> None:
    gesture(ws, "start_session")
    call_tool(ws, "create_entity", names=["Bo Lark"])

    assert state(ws)["calls"] == []  # held for the break, not an interruption
    result = gesture(ws, "break")
    [held] = result["pile"]
    assert (held["entry"], held["status"], held["deadline"]) == (1, "open", "break")
    assert gesture(ws, "approve", entry=1)["ok"] is True


def test_start_and_end_session_change_the_moment(ws: Workspace) -> None:
    assert state(ws)["moment"] == "prep"
    assert gesture(ws, "start_session")["ok"] is True
    assert (state(ws)["moment"], state(ws)["session"]) == ("live-session", 1)

    again = gesture(ws, "start_session")
    assert again["ok"] is False and "already open" in again["error"]

    assert gesture(ws, "end_session")["ok"] is True
    assert (state(ws)["moment"], state(ws)["session"]) == ("between-sessions", None)
    assert gesture(ws, "end_session")["ok"] is False


def test_an_irreversible_approval_is_accepted_from_the_desk(ws: Workspace) -> None:
    def speak() -> Change:
        return Change(path="lines/1.md", after="The bell rings.")

    tool = Tool(fn=speak, responsibility="disclosure", delegated_action=True, reversible=False)
    gesture(ws, "start_session")
    assert delegation.act(ws, tool, "claude-live", speak, blocking=True)["status"] == "pending"
    [due] = state(ws)["calls"]
    assert due["reversible"] is False

    assert gesture(ws, "approve", entry=1)["ok"] is True
    assert (ws.root / "lines/1.md").read_text() == "The bell rings."
    assert entry(ws, 1)["approval"]["channel"] == "desk"


def test_a_gm_decision_is_confirmed_from_the_desk(ws: Workspace) -> None:
    call_tool(ws, "record_fact", statement="The bell tower fell.", entities=[], origin=GM_WORDS)
    [decision] = state(ws)["decisions"]
    assert decision["text"] == "The bell tower fell."
    assert decision["words"] == GM_WORDS["words"]

    assert gesture(ws, "confirm", doc=decision["id"])["ok"] is True
    assert state(ws)["decisions"] == []
    confirmed = log(ws)[-1]
    assert (confirmed["interaction"], confirmed["channel"]) == ("confirm", "desk")


def test_a_gesture_the_desk_does_not_know_is_refused(ws: Workspace) -> None:
    result = desk.take(ws, {"type": "gesture", "id": "g1", "gesture": "undo", "entry": 1})
    jsonschema.validate(result, BRIDGE)
    assert result["ok"] is False
