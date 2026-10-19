"""VTT actions through the Core (ARC-04, ARC-09): the level check, the action log and undo, with a
stand-in for the connected GM client. End to end over the bridge: test_foundry_bridge.py."""

from collections.abc import Iterator

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from test_delegation import call, log, set_level, ws  # noqa: F401  (ws is a fixture)

from secondchair.core import delegation, vtt
from secondchair.core.tools import Tool, VttAction
from secondchair.core.workspace import Workspace

TOKEN = "Scene.s1.Token.t1"


class FakeVtt:
    """The GM client: documents by UUID, mechanical actions refused (no system adapter)."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {TOKEN: {"x": 100, "y": 200}}

    def perform(self, op: str, target: str, params: dict, expect: dict | None) -> tuple[dict, dict]:
        if op != "move_token":
            raise vtt.VttError(f'No system adapter is installed: "{op}" is a mechanical action.')
        doc = self.docs[target]
        before = dict(doc)
        if expect and any(before[k] != v for k, v in expect.items()):
            raise vtt.VttError(f"{target} changed since: nothing was done.")
        doc.update(params)
        return before, dict(doc)


@pytest.fixture
def foundry() -> Iterator[FakeVtt]:
    fake = FakeVtt()
    vtt.connect(fake.perform)
    yield fake
    vtt.connect(None)


def move(ws: Workspace, x: int, y: int):  # noqa: F811
    return call(ws, "move_token", {"token": TOKEN, "x": x, "y": y, "agent": "claude-live"})


def test_at_act_then_review_an_agent_moves_a_token_and_undo_restores_it(
    ws: Workspace,  # noqa: F811
    foundry: FakeVtt,
) -> None:
    result = move(ws, 300, 200)

    assert result.structured_content == {"entry": 1, "status": "applied"}
    assert foundry.docs[TOKEN] == {"x": 300, "y": 200}
    [entry] = log(ws)
    assert (entry["op"], entry["target"]) == ("move_token", TOKEN)
    assert entry["responsibility"] == "vtt_operations"
    assert entry["effective_level"] == "act-then-review"
    assert (entry["before"], entry["after"]) == ({"x": 100, "y": 200}, {"x": 300, "y": 200})

    delegation.undo(ws, 1, "tone", "cli", True)

    assert foundry.docs[TOKEN] == {"x": 100, "y": 200}
    assert log(ws)[0]["status"] == "undone"


def test_undo_refuses_to_move_a_token_moved_by_hand_since(
    ws: Workspace,  # noqa: F811
    foundry: FakeVtt,
) -> None:
    move(ws, 300, 200)
    foundry.docs[TOKEN]["x"] = 700

    with pytest.raises(delegation.DelegationError, match="changed since"):
        delegation.undo(ws, 1, "other", "cli", True)
    assert foundry.docs[TOKEN]["x"] == 700
    assert log(ws)[0]["status"] == "applied"


def test_at_propose_the_token_moves_only_once_approved(
    ws: Workspace,  # noqa: F811
    foundry: FakeVtt,
) -> None:
    set_level(ws, "prep", "vtt_operations", "propose")

    assert move(ws, 300, 200).structured_content == {"entry": 1, "status": "pending"}
    assert foundry.docs[TOKEN]["x"] == 100

    delegation.approve(ws, 1, "cli", True)

    assert foundry.docs[TOKEN]["x"] == 300
    assert log(ws)[0]["before"] == {"x": 100, "y": 200}


def test_with_no_gm_client_open_the_action_fails_cleanly(ws: Workspace) -> None:  # noqa: F811
    result = move(ws, 300, 200)

    assert result.is_error
    assert "No GM client" in result.content[0].text
    [entry] = log(ws)
    assert entry["status"] == "failed"
    assert "No GM client" in entry["error"]


def test_a_mechanical_action_with_no_system_adapter_is_a_failed_action(
    ws: Workspace,  # noqa: F811
    foundry: FakeVtt,
) -> None:
    def strike(target: str) -> VttAction:
        """Strike."""
        return VttAction(op="strike", target=target, params={"weapon": "dagger"})

    tool = Tool(
        fn=strike, responsibility="rules_and_combat", delegated_action=True, reversible=True
    )
    set_level(ws, "prep", "rules_and_combat", "act-then-review")

    with pytest.raises(ToolError, match="system adapter"):
        delegation.wrap(ws, tool)(target=TOKEN, agent="claude-live")

    [entry] = log(ws)
    assert (entry["op"], entry["status"]) == ("strike", "failed")
    assert foundry.docs[TOKEN] == {"x": 100, "y": 200}


def test_an_approved_action_the_vtt_does_not_take_is_a_failed_action(
    ws: Workspace,  # noqa: F811
) -> None:
    set_level(ws, "prep", "vtt_operations", "propose")
    move(ws, 300, 200)

    with pytest.raises(delegation.DelegationError, match="No GM client"):
        delegation.approve(ws, 1, "cli", True)

    [entry] = log(ws)
    assert entry["status"] == "failed"
    assert "No GM client" in entry["error"]
