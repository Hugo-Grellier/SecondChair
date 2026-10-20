"""VTT actions through the Core (ARC-04, ARC-09): the level check, the action log and undo, with a
stand-in for the connected GM client. End to end over the bridge: test_foundry_bridge.py."""

import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from test_calls import CALL_SCHEMA, records
from test_delegation import call, log, set_level, ws  # noqa: F401  (ws is a fixture)

from secondchair.core import delegation, vtt
from secondchair.core.delegation import LEVELS
from secondchair.core.tools import Tool, VttAction
from secondchair.core.workspace import Workspace

TOKEN = "Scene.s1.Token.t1"


class FakeVtt:
    """The GM client: documents by UUID, the world's ceiling, mechanical actions refused (no
    system adapter)."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {TOKEN: {"x": 100, "y": 200}}
        self.ceiling = "act-then-review"
        self.levels: list[str | None] = []

    def perform(
        self, op: str, target: str, params: dict, expect: dict | None, level: str | None
    ) -> tuple[dict, dict]:
        self.levels.append(level)
        if level is not None and LEVELS.index(level) > LEVELS.index(self.ceiling):
            raise vtt.CeilingRefusal(f"Refused by this world's delegation ceiling ({self.ceiling})")
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


def calls(ws: Workspace) -> list[dict]:  # noqa: F811
    return records(ws, "calls", CALL_SCHEMA)


def test_above_the_ceiling_an_allowed_action_is_a_failed_action_and_a_call(
    ws: Workspace,  # noqa: F811
    foundry: FakeVtt,
) -> None:
    foundry.ceiling = "propose"

    result = move(ws, 300, 200)

    assert result.is_error
    assert "ceiling" in result.content[0].text
    assert foundry.docs[TOKEN] == {"x": 100, "y": 200}
    [entry] = log(ws)
    assert (entry["effective_level"], entry["status"]) == ("act-then-review", "failed")
    [called] = calls(ws)
    assert called["kind"] == "ceiling_refusal"
    assert (called["entry"], called["responsibility"]) == (entry["id"], "vtt_operations")
    assert called["status"] == "open"


def test_under_the_ceiling_the_gm_approves_and_undoes(
    ws: Workspace,  # noqa: F811
    foundry: FakeVtt,
) -> None:
    foundry.ceiling = "propose"
    set_level(ws, "prep", "vtt_operations", "propose")
    move(ws, 300, 200)

    delegation.approve(ws, 1, "cli", True)
    foundry.ceiling = "manual"
    delegation.undo(ws, 1, "tone", "cli", True)

    assert foundry.levels == ["propose", None]  # the GM's undo is not bounded by the ceiling
    assert foundry.docs[TOKEN] == {"x": 100, "y": 200}
    assert [(c["kind"], c["status"]) for c in calls(ws)] == [("proposal", "answered")]


def test_an_approval_refused_by_the_ceiling_is_a_call(
    ws: Workspace,  # noqa: F811
    foundry: FakeVtt,
) -> None:
    set_level(ws, "prep", "vtt_operations", "propose")
    move(ws, 300, 200)
    foundry.ceiling = "manual"

    with pytest.raises(delegation.DelegationError, match="ceiling"):
        delegation.approve(ws, 1, "cli", True)

    assert log(ws)[0]["status"] == "failed"
    assert [(c["kind"], c["entry"], c["status"]) for c in calls(ws)] == [
        ("proposal", 1, "answered"),
        ("ceiling_refusal", 1, "open"),
    ]


def test_other_actions_go_through_while_the_vtt_takes_one(
    ws: Workspace,  # noqa: F811
    foundry: FakeVtt,
) -> None:
    """The workspace lock is not held across the GM client's round trip (#99): meanwhile the
    action is logged with status unknown, and another agent's action is taken."""
    seen: list[str] = []

    def slow(*args: Any) -> tuple[dict, dict]:
        if not seen:
            seen.append(log(ws)[0]["status"])
            other = threading.Thread(target=move, args=(ws, 500, 200))
            other.start()
            other.join(timeout=5)
            seen.append("other blocked" if other.is_alive() else "other done")
        return foundry.perform(*args)

    vtt.connect(slow)

    assert move(ws, 300, 200).structured_content == {"entry": 1, "status": "applied"}
    assert seen == ["unknown", "other done"]
    assert [e["status"] for e in log(ws)] == ["applied", "applied"]


class Late:
    """A GM client that answers only after the reply timeout (#99)."""

    def __init__(self) -> None:
        self.later: Future[tuple[dict, dict]] = Future()

    def perform(self, *args: Any) -> tuple[dict, dict]:
        raise vtt.Unanswered("The GM client did not answer in time.", self.later)


@pytest.fixture
def late() -> Iterator[Late]:
    client = Late()
    vtt.connect(client.perform)
    yield client
    vtt.connect(None)


def settled(ws: Workspace, status: str) -> dict:  # noqa: F811
    """Entry 1 once a late reply settled it to `status`, in its own thread."""
    for _ in range(100):
        if delegation.read_entry(ws, 1)["status"] == status:
            return log(ws)[0]
        time.sleep(0.05)
    raise AssertionError(f"Entry 1 is {log(ws)[0]['status']}, not {status}.")


def test_a_late_reply_settles_an_unknown_action_as_applied_and_undoable(
    ws: Workspace,  # noqa: F811
    late: Late,
) -> None:
    result = move(ws, 300, 200)

    assert result.is_error
    assert "may have been taken" in result.content[0].text
    assert log(ws)[0]["status"] == "unknown"

    late.later.set_result(({"x": 100, "y": 200}, {"x": 300, "y": 200}))

    entry = settled(ws, "applied")
    assert (entry["before"], entry["after"]) == ({"x": 100, "y": 200}, {"x": 300, "y": 200})
    assert "error" not in entry
    foundry = FakeVtt()
    foundry.docs[TOKEN] = {"x": 300, "y": 200}  # the VTT took it, late
    vtt.connect(foundry.perform)
    delegation.undo(ws, 1, "tone", "cli", True)
    assert foundry.docs[TOKEN] == {"x": 100, "y": 200}


def test_a_late_refusal_settles_an_unknown_action_as_failed(
    ws: Workspace,  # noqa: F811
    late: Late,
) -> None:
    move(ws, 300, 200)

    late.later.set_exception(vtt.VttError(f"{TOKEN} changed since: nothing was done."))

    assert "changed since" in settled(ws, "failed")["error"]


def test_an_approved_action_answered_late_keeps_its_approval(
    ws: Workspace,  # noqa: F811
    late: Late,
) -> None:
    set_level(ws, "prep", "vtt_operations", "propose")
    move(ws, 300, 200)

    with pytest.raises(delegation.DelegationError, match="may have been taken"):
        delegation.approve(ws, 1, "cli", True)
    assert log(ws)[0]["approval"]["channel"] == "cli"
    assert [(c["kind"], c["status"]) for c in calls(ws)] == [("proposal", "answered")]

    late.later.set_result(({"x": 100, "y": 200}, {"x": 300, "y": 200}))

    assert settled(ws, "applied")["approval"]["channel"] == "cli"


def test_a_gm_client_leaving_unanswered_leaves_the_action_unknown(
    ws: Workspace,  # noqa: F811
    late: Late,
) -> None:
    move(ws, 300, 200)

    late.later.cancel()

    time.sleep(0.2)
    assert log(ws)[0]["status"] == "unknown"
