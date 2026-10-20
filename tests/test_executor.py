"""A GM creature's strikes, system actions and saves through the Core (RUL-03..05, RUL-09,
RUL-10, DEL-23), with a stand-in for the GM client. The adapter's side, on a stand-in pf2e
encounter: foundry/tests/executor.test.js."""

from collections.abc import Iterator

import pytest
from test_delegation import call, log, ws  # noqa: F401  (ws is a fixture)

from secondchair.core import delegation, vtt
from secondchair.core.workspace import Workspace

GOBLIN = "Scene.s1.Token.goblin"
SELLA = "Scene.s1.Token.sella"  # a PC


class GmClient:
    """The GM client taking each request as the PF2e adapter would: a PC never acts."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict, dict | None, str | None]] = []
        self.hp = 20

    def perform(
        self, op: str, target: str, params: dict, expect: dict | None, level: str | None
    ) -> tuple[dict, dict]:
        self.requests.append((op, target, params, expect, level))
        if target == SELLA and op != "saving_throw":
            raise vtt.VttError(f"{target} is a player character: ... (RUL-04).")
        if op == "speak":
            return {"message": None}, {"message": "m1"}
        before = {"state": {SELLA: {"hp": {"value": self.hp, "temp": 0}, "conditions": {}}}}
        if expect:  # the GM's undo
            self.hp = params["state"][SELLA]["hp"]["value"]
            return expect, params
        self.hp -= 6
        after = {"state": {SELLA: {"hp": {"value": self.hp, "temp": 0}, "conditions": {}}}}
        return before, {**after, "degree": "success", "damage": 6}


@pytest.fixture
def table(ws: Workspace) -> Iterator[GmClient]:  # noqa: F811
    client = GmClient()
    vtt.connect(client.perform)
    delegation.start_session(ws)
    yield client
    vtt.connect(None)


def strike(ws: Workspace, creature: str = GOBLIN):  # noqa: F811
    arguments = {"creature": creature, "strike": "dogslicer", "target": SELLA, "attack": 2}
    return call(ws, "strike", {**arguments, "entity": "e-1a2b3c4d", "agent": "claude-live"})


def test_an_agent_strike_is_one_logged_system_call_the_gm_undoes(
    ws: Workspace,  # noqa: F811
    table: GmClient,
) -> None:
    assert strike(ws).structured_content == {"entry": 1, "status": "applied"}
    [request] = table.requests
    assert request == (
        "strike",
        GOBLIN,
        {"strike": "dogslicer", "target": SELLA, "map": 1},
        None,
        "act-then-review",
    )
    [entry] = log(ws)
    assert (entry["responsibility"], entry["entity"], entry["reversible"]) == (
        "rules_and_combat",
        "e-1a2b3c4d",
        True,
    )
    assert entry["after"]["damage"] == 6 and table.hp == 14

    delegation.undo(ws, 1, "rules", "cli", True)

    assert table.requests[-1][3] == entry["after"]  # the logged after, expected back
    assert table.hp == 20 and log(ws)[0]["status"] == "undone"


def test_an_action_the_adapter_refuses_for_a_pc_is_a_failed_action(
    ws: Workspace,  # noqa: F811
    table: GmClient,
) -> None:
    result = strike(ws, creature=SELLA)
    assert result.is_error and "RUL-04" in result.content[0].text
    [entry] = log(ws)
    assert entry["status"] == "failed" and "player character" in entry["error"]


def test_system_actions_and_saves_are_rules_and_combat_actions(
    ws: Workspace,  # noqa: F811
    table: GmClient,
) -> None:
    acted = {"creature": GOBLIN, "action": "demoralize", "target": SELLA, "agent": "a"}
    call(ws, "use_action", acted)
    call(ws, "saving_throw", {"target": SELLA, "save": "reflex", "dc": 20, "agent": "a"})
    assert [(r[0], r[1], r[2]) for r in table.requests] == [
        ("use_action", GOBLIN, {"action": "demoralize", "target": SELLA}),
        ("saving_throw", SELLA, {"save": "reflex", "dc": 20}),
    ]
    assert {e["responsibility"] for e in log(ws)} == {"rules_and_combat"}


def test_a_strike_and_a_shouted_line_are_two_actions_under_two_responsibilities(
    ws: Workspace,  # noqa: F811
    table: GmClient,
) -> None:
    strike(ws)
    line = {"token": GOBLIN, "line": "Die, longshanks!", "cites": [], "entity": "e-1a2b3c4d"}
    shouted = call(ws, "speak", {**line, "agent": "claude-live"})

    assert shouted.structured_content == {"entry": 2, "status": "pending"}
    struck, spoken = log(ws)
    assert (struck["tool"], struck["responsibility"], struck["status"]) == (
        "strike",
        "rules_and_combat",
        "applied",
    )
    assert (spoken["tool"], spoken["responsibility"], spoken["reversible"]) == (
        "speak",
        "disclosure",
        False,
    )
    assert spoken["entity"] == struck["entity"] == "e-1a2b3c4d"
    assert len(table.requests) == 1  # the line waits for the GM's authenticated approval
