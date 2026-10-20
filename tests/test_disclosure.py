"""Disclosure under the irreversible hold (DEL-09, DEL-09a, CAN-17): a disclosure is held at
propose until the GM lifts the hold of its cell, and marks the facts it cites as known by the
party. The VTT is a stand-in for the connected GM client."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from test_canon import call, entity, fact
from test_delegation import gm, log
from test_knowledge import learn

from secondchair.cli import main
from secondchair.core import calls, capture, delegation, index, jobs, knowledge, vtt, workspace
from secondchair.core.delegation import DelegationError
from secondchair.core.server import build_server
from secondchair.core.workspace import Workspace
from secondchair_foundry import desk

TOKEN = "Scene.s1.Token.t1"
PLAYER = "User.u1"


class FakeVtt:
    """The GM client: a hidden token, the world's ceiling at act-then-review."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {TOKEN: {"hidden": True}}
        self.whispered: list[tuple[str, str]] = []

    def perform(
        self, op: str, target: str, params: dict, expect: dict | None, level: str | None
    ) -> tuple[dict, dict]:
        if op == "whisper":
            self.whispered.append((target, params["content"]))
            return {"message": None}, {"message": f"m{len(self.whispered)}"}
        assert op == "reveal_token"
        before = dict(self.docs[target])
        self.docs[target].update(params)
        return before, dict(self.docs[target])


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path / "camp"), "--language", "en", "--calendar", "absalom"])
    ws = workspace.load(tmp_path / "camp")
    (ws.root / "time.yaml").write_text("current_date: '4725-03-02'\nsessions: {}\n")
    return ws


@pytest.fixture
def clue(ws: Workspace) -> str:
    """A fact the party does not know, recorded in prep; then session 1 starts, the play
    profile: disclosure at propose."""
    gauge = entity(ws, "Dry gauge")
    found = fact(ws, "The dry gauge stays at zero while the bell rings.", entities=[gauge])
    delegation.start_session(ws)
    return found


@pytest.fixture
def foundry() -> Iterator[FakeVtt]:
    fake = FakeVtt()
    vtt.connect(fake.perform)
    yield fake
    vtt.connect(None)


def set_disclosure(ws: Workspace, level: str) -> None:
    path = ws.root / delegation.TABLE_FILE
    table = yaml.safe_load(path.read_text())
    table["live-session"]["disclosure"]["level"] = level
    path.write_text(yaml.safe_dump(table, sort_keys=False))


def reveal(ws: Workspace, cites: list[str]) -> Any:
    return call(ws, "reveal_token", token=TOKEN, cites=cites, agent="claude-live")


def lift(ws: Workspace) -> None:
    assert gm("hold", "lift", "disclosure", "live-session", root=ws.root) == 0


def test_a_disclosure_is_held_at_propose_even_at_act_then_review(
    ws: Workspace, foundry: FakeVtt, clue: str
) -> None:
    set_disclosure(ws, "act-then-review")

    result = reveal(ws, [clue])

    assert result.structured_content["status"] == "pending"
    assert foundry.docs[TOKEN] == {"hidden": True}
    disclosure = log(ws)[-1]
    assert (disclosure["effective_level"], disclosure["reversible"]) == ("propose", False)


def test_an_agent_relayed_approval_is_refused(ws: Workspace, foundry: FakeVtt, clue: str) -> None:
    reveal(ws, [clue])
    entry = log(ws)[-1]["id"]

    result = call(ws, "approve_proposal", entry=entry, gm_words="Yes, reveal it.")

    assert result.is_error
    assert "authenticated Surface" in result.content[0].text
    assert foundry.docs[TOKEN] == {"hidden": True}
    assert knowledge.known(ws, index.PARTY) == {}


@pytest.mark.parametrize("surface", ["desk", "cli"])
def test_the_desk_or_an_interactive_terminal_approves_and_the_party_learns_the_cited_facts(
    ws: Workspace, foundry: FakeVtt, clue: str, surface: str
) -> None:
    reveal(ws, [clue])
    entry = log(ws)[-1]["id"]

    if surface == "desk":
        message = {"type": "gesture", "id": "g1", "gesture": "approve", "entry": entry}
        assert desk.take(ws, message)["ok"] is True
    else:
        delegation.approve(ws, entry, "cli", authenticated=True)

    assert foundry.docs[TOKEN] == {"hidden": False}
    learned = knowledge.known(ws, index.PARTY)[clue]
    assert (learned["mode"], learned["date"]) == ("knows", "4725-03-02")
    [record] = (ws.root / "canon/knowledge").glob("*.md")
    front, _ = index.split_doc(record.read_text())
    assert (front["knower"], front["session"]) == ("party", 1)
    assert delegation.log_hand_edits(ws) == []  # the Core wrote it, through the action log


def test_lifting_the_hold_from_a_relay_is_refused(ws: Workspace, clue: str) -> None:
    assert gm("hold", "lift", "disclosure", "live-session", root=ws.root, interactive=False) == 1
    with pytest.raises(DelegationError, match="authenticated Surface"):
        delegation.set_hold(ws, "disclosure", "live-session", False, "via agent", False, "Go.")
    assert "restore_hold" in tool_names(ws)  # an agent can only restore it
    assert not any("lift" in name for name in tool_names(ws))
    assert delegation.held(ws, "live-session", "disclosure") is True


def test_restoring_the_hold_from_a_relay_works_at_once(
    ws: Workspace, foundry: FakeVtt, clue: str
) -> None:
    set_disclosure(ws, "act-then-review")
    lift(ws)
    assert delegation.effective_level(ws, "disclosure", "live-session", False) == "act-then-review"

    result = call(
        ws,
        "restore_hold",
        responsibility="disclosure",
        moment="live-session",
        gm_words="Hold every reveal again.",
    )

    assert not result.is_error, result
    assert delegation.effective_level(ws, "disclosure", "live-session", False) == "propose"
    assert reveal(ws, [clue]).structured_content["status"] == "pending"
    restored = [e for e in log(ws) if e.get("interaction") == "restore_hold"]
    assert [(e["channel"], e["quote"]) for e in restored] == [
        ("via agent", "Hold every reveal again.")
    ]
    assert [e["hold"] for e in log(ws) if e.get("interaction") == "lift_hold"] == [
        {"responsibility": "disclosure", "moment": "live-session"}
    ]


def test_with_the_hold_lifted_a_disclosure_applies_at_once_logged_with_no_undo(
    ws: Workspace, foundry: FakeVtt, clue: str
) -> None:
    set_disclosure(ws, "act-then-review")
    lift(ws)

    result = reveal(ws, [clue])

    assert result.structured_content["status"] == "applied"
    assert foundry.docs[TOKEN] == {"hidden": False}
    disclosure = log(ws)[result.structured_content["entry"] - 1]
    assert (disclosure["status"], disclosure["effective_level"]) == ("applied", "act-then-review")
    assert knowledge.known(ws, index.PARTY)[clue]["mode"] == "knows"
    with pytest.raises(DelegationError, match="irreversible and cannot be undone"):
        delegation.undo(ws, disclosure["id"], "tone", "cli", True)


def test_a_disclosure_citing_an_unknown_or_never_true_fact_is_refused(
    ws: Workspace, foundry: FakeVtt, clue: str
) -> None:
    result = reveal(ws, ["f-00000000"])
    assert result.is_error
    assert "unknown fact ids" in result.content[0].text
    assert foundry.docs[TOKEN] == {"hidden": True}


# Which knower bounds a disclosure (CAN-16): none when the GM's approval is the gate; an acting
# NPC must know every fact it cites.


def say(ws: Workspace, npc: str, cites: list[str]) -> Any:
    line = "The gauge never moves."
    return call(ws, "speak", token=TOKEN, line=line, cites=cites, entity=npc, agent="claude-live")


def test_a_disclosure_may_cite_a_fact_the_party_does_not_know_yet(
    ws: Workspace, foundry: FakeVtt, clue: str
) -> None:
    assert clue not in knowledge.known(ws, index.PARTY)

    assert reveal(ws, [clue]).structured_content["status"] == "pending"


@pytest.fixture
def keeper(ws: Workspace) -> tuple[str, str]:
    """A clue the keeper knows, recorded in prep; then session 1 starts."""
    gauge = entity(ws, "Dry gauge")
    found = fact(ws, "The dry gauge stays at zero while the bell rings.", entities=[gauge])
    npc = entity(ws, "Keeper Ilsa")
    learn(ws, npc, found)
    delegation.start_session(ws)
    return npc, found


def test_an_npc_discloses_only_what_it_knows(
    ws: Workspace, foundry: FakeVtt, keeper: tuple[str, str]
) -> None:
    npc, clue = keeper
    gauge = next(e["id"] for e in index.search_entities(ws) if e["names"] == ["Dry gauge"])

    refused = say(ws, gauge, [clue])

    assert refused.is_error
    assert f"{gauge} does not know ['{clue}']" in refused.content[0].text
    assert say(ws, npc, [clue]).structured_content["status"] == "pending"


def test_an_npc_disclosure_is_checked_again_at_approval(
    ws: Workspace, foundry: FakeVtt, keeper: tuple[str, str]
) -> None:
    npc, clue = keeper
    say(ws, npc, [clue])
    for record in (ws.root / "canon/knowledge").glob("*.md"):
        record.unlink()  # a hand edit: the keeper forgets

    with pytest.raises(DelegationError, match="does not know"):
        delegation.approve(ws, log(ws)[-1]["id"], "cli", authenticated=True)


def test_a_whisper_marks_nothing_known_by_the_party_and_the_wrap_asks_the_gm(
    ws: Workspace, foundry: FakeVtt, clue: str
) -> None:
    set_disclosure(ws, "act-then-review")
    lift(ws)

    told = call(
        ws, "whisper", user=PLAYER, line="The gauge is dry.", cites=[clue], agent="claude-live"
    )

    assert told.structured_content["status"] == "applied", told
    assert foundry.whispered == [(PLAYER, "The gauge is dry.")]
    assert knowledge.known(ws, index.PARTY) == {}  # CAP-08: one player is not the party
    call(ws, "whisper", user="User.u2", line="Dry.", cites=[clue], agent="claude-live")
    delegation.change_moment(ws, "between-sessions")
    jobs.start(ws, 1, {"host": "h", "model": "m", "effort": "e"}, manual=True)
    jobs.end(ws, 1)

    [question] = capture.wrap(ws, 1, authenticated=True, end="4725-03-03")["questions"]
    assert (question["kind"], question["responsibility"]) == ("proposal", "disclosure")
    assert "Whispered to User.u1" in question["message"]
    again = capture.wrap(ws, 1, authenticated=True, end="4725-03-03")["questions"]
    assert [q["id"] for q in again] == [question["id"]]  # held once, not twice

    delegation.approve(ws, question["entry"], "cli", authenticated=True)
    assert capture.wrap(ws, 1, authenticated=True, end="4725-03-03")["settled"] is not None
    learned = knowledge.known(ws, index.PARTY)[clue]
    assert (learned["mode"], learned["date"]) == ("knows", "4725-03-02")
    assert [c for c in calls.read_calls(ws) if c["status"] == "open"] == []


def tool_names(ws: Workspace) -> set[str]:
    async def run() -> set[str]:
        async with Client(build_server(ws)) as client:
            return {t.name for t in (await client.list_tools()).tools}

    return asyncio.run(run())
