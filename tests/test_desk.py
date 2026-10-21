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
from test_canon import entity, fact
from test_knowledge import learn

from secondchair.cli import main
from secondchair.core import delegation, director, index, knowledge, observations, workspace
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


# The acting cue (DEL-15, CAN-16)


def npc_who_knows(ws: Workspace) -> tuple[str, str, str]:
    """Tovan Reed, who knows the bell rings on dry nights but not that a relay rings it."""
    tovan = entity(ws, "Tovan Reed")
    bell = fact(ws, "The bell rings on dry nights.", entities=[tovan])
    relay = fact(ws, "A cracked relay rings the bell.", entities=[])
    learn(ws, tovan, bell)
    return tovan, bell, relay


def cue(ws: Workspace, npc: str, line: str, cites: list[str], **more: Any) -> Any:
    goal = "Keep the party away from the tower."
    return call_tool(ws, "show_acting_cue", npc=npc, goal=goal, line=line, cites=cites, **more)


def test_the_desk_shows_the_active_npcs_acting_cue(ws: Workspace) -> None:
    tovan, bell, relay = npc_who_knows(ws)
    assert state(ws)["cue"] is None

    shown = cue(ws, tovan, "It only rings when the nights are dry.", [bell], does_not_know=[relay])
    assert not shown.is_error, shown

    found = state(ws)["cue"]
    assert (found["npc"], found["name"], found["voiced"]) == (tovan, "Tovan Reed", False)
    assert found["goal"] == "Keep the party away from the tower."
    assert found["line"] == "It only rings when the nights are dry."
    assert found["knows"] == [
        {"id": bell, "statement": "The bell rings on dry nights.", "mode": "knows"}
    ]
    assert found["does_not_know"] == [{"id": relay, "statement": "A cracked relay rings the bell."}]


def test_a_cue_posture_is_optional_gm_only_direction_outside_the_audience_guard(
    ws: Workspace,
) -> None:
    tovan, bell, relay = npc_who_knows(ws)
    cue(ws, tovan, "It only rings when the nights are dry.", [bell])
    assert "posture" not in state(ws)["cue"]

    # Posture names a fact Tovan does not hold, yet it is not audience content: not refused.
    shown = cue(
        ws,
        tovan,
        "It only rings when the nights are dry.",
        [bell],
        posture="A cracked relay, afraid",
    )
    assert not shown.is_error, shown
    assert state(ws)["cue"]["posture"] == "A cracked relay, afraid"

    # The guard still applies to the line alone.
    refused = cue(ws, tovan, "A cracked relay rings it.", [relay], posture="calm")
    assert refused.is_error
    assert state(ws)["cue"]["posture"] == "A cracked relay, afraid"  # unchanged


def test_while_a_turn_driver_is_active_the_cue_shows_no_agent_proposal(ws: Workspace) -> None:
    tovan, bell, _relay = npc_who_knows(ws)
    cue(ws, tovan, "It only rings when the nights are dry.", [bell])

    driven = desk.state(ws, "pf2e-combater")
    jsonschema.validate(driven, BRIDGE)
    assert driven["turn_driver"] == "pf2e-combater"
    assert driven["cue"]["line"] is None  # agents stay silent (RUL-12)
    assert (driven["cue"]["npc"], driven["cue"]["voiced"]) == (tovan, False)

    found = state(ws)
    assert found["turn_driver"] is None
    assert found["cue"]["line"] == "It only rings when the nights are dry."


def test_a_line_citing_a_fact_the_npc_does_not_know_is_refused(ws: Workspace) -> None:
    tovan, bell, relay = npc_who_knows(ws)
    cue(ws, tovan, "It only rings when the nights are dry.", [bell])

    refused = cue(ws, tovan, "A cracked relay rings it.", [relay])
    assert refused.is_error and "does not know" in refused.content[0].text
    assert state(ws)["cue"]["line"] == "It only rings when the nights are dry."  # unchanged

    wrong = cue(ws, tovan, "It only rings when the nights are dry.", [bell], does_not_know=[bell])
    assert wrong.is_error and "knows" in wrong.content[0].text


def observe(ws: Workspace, id: str, minute: int, kind: str, scene: str, **payload: Any) -> None:
    envelope: dict[str, Any] = {"id": id, "session": 1, "at": f"2026-10-21T20:{minute:02d}:00Z"}
    envelope |= {"scene": scene, "actor": None, "kind": kind, "visibility": "players"}
    assert observations.record(ws, envelope | {"payload": payload}) is None


def test_a_cue_is_withdrawn_once_play_moves_on_and_a_stale_one_is_never_shown(
    ws: Workspace,
) -> None:
    tovan, bell, _ = npc_who_knows(ws)
    line = "It only rings when the nights are dry."
    gesture(ws, "start_session")
    observe(ws, "o1", 0, "scene", "Scene.tower", action="activate", name="Tower")
    observe(ws, "o2", 1, "combat", "Scene.tower", action="start", combat="c1", round=1, turn=0)
    cue(ws, tovan, line, [bell])

    shown = state(ws)["cue"]
    assert shown["line"] == line
    assert {k: v for k, v in shown["as_of"].items() if k != "at"} == {
        "moment": delegation.current_moment(ws)[1],
        "session": 1,
        "observation": "o2",
        "scene": "Scene.tower",
        "round": 1,
        "turn": 0,
    }
    # A chat in the same turn moves nothing: the cue stays.
    observe(ws, "o3", 2, "chat", "Scene.tower", text="The bell rings.")
    assert state(ws)["cue"] == shown

    # The next turn withdraws it, for good: nothing renders a cue built for an earlier turn.
    observe(ws, "o4", 3, "combat", "Scene.tower", action="turn", combat="c1", round=1, turn=1)
    assert state(ws)["cue"] is None
    observe(ws, "o5", 4, "combat", "Scene.tower", action="end", combat="c1", round=1, turn=1)
    assert state(ws)["cue"] is None

    # A cue shown now stays until the scene changes, even back to an earlier one.
    cue(ws, tovan, line, [bell])
    assert state(ws)["cue"]["as_of"]["round"] is None
    observe(ws, "o6", 5, "scene", "Scene.market", action="activate", name="Market")
    assert state(ws)["cue"] is None
    observe(ws, "o7", 6, "scene", "Scene.tower", action="activate", name="Tower")
    assert state(ws)["cue"] is None

    # A new session withdraws it too, and a cue file with no as_of is never shown.
    cue(ws, tovan, line, [bell])
    gesture(ws, "end_session")
    assert state(ws)["cue"] is None
    (ws.root / knowledge.CUE_FILE).write_text(json.dumps({"npc": tovan, "line": line}))
    assert state(ws)["cue"] is None


def test_a_cue_shown_in_prep_stays_withdrawn_after_a_session(ws: Workspace) -> None:
    tovan, bell, _ = npc_who_knows(ws)
    line = "It only rings when the nights are dry."
    cue(ws, tovan, line, [bell])
    assert state(ws)["cue"]["as_of"]["session"] is None

    gesture(ws, "start_session")  # an empty session withdraws it, with no observation yet
    assert state(ws)["cue"] is None
    observe(ws, "o1", 0, "scene", "Scene.tower", action="activate", name="Tower")
    assert state(ws)["cue"] is None
    gesture(ws, "end_session")  # back outside a session: still withdrawn
    assert state(ws)["cue"] is None

    # A cue shown in an empty session is withdrawn at its end too.
    gesture(ws, "start_session")
    cue(ws, tovan, line, [bell])
    assert state(ws)["cue"]["as_of"]["observation"] is None
    gesture(ws, "end_session")
    assert state(ws)["cue"] is None


def test_i_voice_this_one_withdraws_its_calls_and_hand_back_removes_it(ws: Workspace) -> None:
    tovan, bell, _ = npc_who_knows(ws)

    def speak(text: str) -> Change:
        return Change(path=f"lines/{text}.md", after=text, entity=tovan)

    tool = Tool(fn=speak, responsibility="disclosure", delegated_action=True, reversible=False)
    gesture(ws, "start_session")
    pending = delegation.act(ws, tool, "claude-live", lambda: speak("Go home."), blocking=True)
    assert len(state(ws)["calls"]) == 1

    assert gesture(ws, "voice", entity=tovan)["ok"] is True
    assert {(o["responsibility"], o["level"], o["moment"]) for o in delegation.overrides(ws)} == {
        ("npcs", "manual", None),
        ("disclosure", "manual", None),
    }
    assert state(ws)["calls"] == []  # withdrawn with its safe default
    assert entry(ws, pending["entry"])["status"] == "rejected"
    voiced = [e for e in log(ws) if e.get("interaction") == "add_override"]
    assert {(e["channel"], e["authenticated"]) for e in voiced} == {("desk", True)}

    # At manual the cue is still shown, since it is a read.
    assert not cue(ws, tovan, "It only rings when the nights are dry.", [bell]).is_error
    assert state(ws)["cue"]["voiced"] is True

    assert gesture(ws, "hand_back", entity=tovan)["ok"] is True
    assert delegation.overrides(ws) == []
    assert state(ws)["cue"]["voiced"] is False
    assert gesture(ws, "hand_back", entity=tovan)["ok"] is False


def written(ws: Workspace) -> dict[str, int]:
    """How many action log entries, calls and jobs the workspace holds."""
    return {d: len(list((ws.root / d).glob("*.yaml"))) for d in ("action-log", "calls", "jobs")}


def tower_scene(ws: Workspace) -> tuple[str, str, str, str]:
    """Tovan Reed speaks in the Tower; Mira Pell only in the Market. The party knows the bell
    rings on dry nights; only Tovan knows where the key is. Returns Tovan, the bell, the key and
    Mira."""
    tovan, bell, _ = npc_who_knows(ws)
    key = fact(ws, "The vault key hides under the altar.", entities=[tovan])
    learn(ws, tovan, key)
    learn(ws, "party", bell)
    hid = fact(ws, "Tovan hid the relay.", entities=[tovan])
    learn(ws, tovan, hid)
    learn(ws, "party", hid, mode="suspects")  # the party only suspects it
    mira = entity(ws, "Mira Pell")
    learn(ws, mira, fact(ws, "Mira forged the tithe ledger.", entities=[mira]))
    handoff = ws.root / "prep/session-1/handoff.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "# Session 1\n\n- Tovan Reed lies about the relay.\n- The market is busy.\n"
        "Tower: the bell is cracked.\n"
    )
    gesture(ws, "start_session")
    observe(ws, "o1", 0, "scene", "Scene.tower", action="activate", name="Tower")
    observe(ws, "o2", 1, "chat", "Scene.tower", speaker="Tovan Reed", text="Go home.")
    observe(ws, "o3", 2, "chat", "Scene.market", speaker="Mira Pell", text="Coins!")
    return tovan, bell, key, mira


def test_the_situation_card_shows_who_is_here_what_the_party_knows_and_what_to_keep_secret(
    ws: Workspace,
) -> None:
    tovan, bell, key, _ = tower_scene(ws)
    hid = next(f["id"] for f in index.search_facts(ws) if f["statement"] == "Tovan hid the relay.")
    assert state(ws)["situation"] is None  # nothing until the GM pulls it
    before = written(ws)

    # The result says nothing of the card: it reaches the Desk only in its state.
    assert gesture(ws, "situation") == {"type": "result", "id": "g1", "ok": True}
    card = state(ws)["situation"]
    assert {k: v for k, v in card["as_of"].items() if k != "at"} == {
        "moment": delegation.current_moment(ws)[1],
        "session": 1,
        "observation": "o1",
        "scene": "Scene.tower",
        "round": None,
        "turn": None,
    }
    assert (card["scene"], card["acting"], card["calls"]) == ("Tower", None, [])
    assert card["npcs"] == [
        {
            "id": tovan,
            "name": "Tovan Reed",
            "shared": [  # how the party holds each: a suspicion is not knowledge
                {"id": bell, "statement": "The bell rings on dry nights.", "mode": "knows"}
                | {"party_mode": "knows"},
                {"id": hid, "statement": "Tovan hid the relay.", "mode": "knows"}
                | {"party_mode": "suspects"},
            ],
            "secret": [
                {"id": key, "statement": "The vault key hides under the altar.", "mode": "knows"}
            ],
        }
    ]  # Mira spoke in another scene: not here, and nothing of hers is on the card
    assert card["handoff"] == ["Tovan Reed lies about the relay.", "Tower: the bell is cracked."]
    # A read: no action logged, no call raised, no job queued, so no model is asked.
    assert written(ws) == before
    # Deterministic: a second pull where play stands is the same card but for its time.
    gesture(ws, "situation")
    again = state(ws)["situation"]
    assert again["as_of"]["at"] >= card["as_of"]["at"]
    assert {**again, "as_of": None} == {**card, "as_of": None}
    assert {**again["as_of"], "at": None} == {**card["as_of"], "at": None}


def test_the_situation_card_is_withdrawn_once_play_moves_on_and_names_who_acts(
    ws: Workspace,
) -> None:
    tower_scene(ws)
    gesture(ws, "situation")
    assert state(ws)["situation"] is not None
    observe(ws, "o4", 3, "chat", "Scene.tower", speaker="Tovan Reed", text="Leave.")
    assert state(ws)["situation"] is not None  # a chat line moves nothing

    observe(
        ws,
        "o5",
        4,
        "combat",
        "Scene.tower",
        action="start",
        round=1,
        turn=0,
        combatant="Tovan Reed",
    )
    assert state(ws)["situation"] is None  # combat started: stale
    gesture(ws, "situation")
    card = state(ws)["situation"]
    assert (card["acting"], card["as_of"]["round"], card["as_of"]["turn"]) == ("Tovan Reed", 1, 0)

    observe(ws, "o6", 5, "combat", "Scene.tower", action="turn", round=1, turn=1, combatant="Ada")
    assert state(ws)["situation"] is None  # the next turn
    gesture(ws, "situation")
    observe(ws, "o7", 6, "combat", "Scene.tower", action="round", round=2, turn=1, combatant="Ada")
    assert state(ws)["situation"] is None  # the next round
    gesture(ws, "situation")
    observe(ws, "o8", 7, "scene", "Scene.market", action="activate", name="Market")
    assert state(ws)["situation"] is None  # another scene
    gesture(ws, "end_session")
    gesture(ws, "situation")
    assert state(ws)["situation"]["as_of"]["session"] is None
    gesture(ws, "start_session")
    assert state(ws)["situation"] is None  # a new moment withdraws it


def test_the_situation_card_lists_the_open_calls_about_an_npc_present(ws: Workspace) -> None:
    tovan, *_ = tower_scene(ws)

    def speak(text: str) -> Change:
        return Change(path=f"lines/{text}.md", after=text, entity=tovan)

    tool = Tool(fn=speak, responsibility="disclosure", delegated_action=True, reversible=False)
    pending = delegation.act(ws, tool, "claude-live", lambda: speak("Go home."), blocking=True)
    gesture(ws, "situation")
    [found] = state(ws)["situation"]["calls"]
    assert (found["kind"], found["deadline"]) == ("proposal", "now")
    assert found["text"] == "speak on lines/Go home..md"
    assert pending["status"] == "pending"


def test_outside_a_session_the_card_reads_the_next_sessions_handoff_and_the_cued_npc(
    ws: Workspace,
) -> None:
    tovan, bell, _ = npc_who_knows(ws)
    handoff = ws.root / "prep/session-1/handoff.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("- Tovan Reed rings the bell at dusk.\n- Nobody else.\n")
    gesture(ws, "situation")
    assert state(ws)["situation"]["npcs"] == []  # nobody seen, nobody cued
    cue(ws, tovan, "It only rings when the nights are dry.", [bell])
    gesture(ws, "situation")  # the NPC the GM is voicing counts as present
    card = state(ws)["situation"]
    assert [n["name"] for n in card["npcs"]] == ["Tovan Reed"]
    assert card["handoff"] == ["Tovan Reed rings the bell at dusk."]  # session 1's, the next


def test_a_situation_card_file_with_no_as_of_or_garbled_is_never_shown(ws: Workspace) -> None:
    (ws.root / director.CARD_FILE).write_text(json.dumps({"scene": "Tower"}))
    assert state(ws)["situation"] is None
    # Where play stands, but a damaged body: withdrawn rather than sent for the Desk to choke on.
    as_of = observations.position(ws) | {"at": "2026-10-21T20:00:00+00:00"}
    damaged = {"as_of": as_of, "scene": None, "acting": None, "npcs": [{"name": "Tovan"}]}
    (ws.root / director.CARD_FILE).write_text(json.dumps(damaged | {"handoff": [], "calls": []}))
    assert state(ws)["situation"] is None
    ok = {**damaged, "npcs": [], "handoff": [], "calls": []}
    (ws.root / director.CARD_FILE).write_text(json.dumps(ok))
    assert state(ws)["situation"] == ok
    (ws.root / director.CARD_FILE).write_text("{not json")
    assert state(ws)["situation"] is None

    # A client that sends a speaker or a scene name that is not text gets a card all the same.
    gesture(ws, "start_session")
    observe(ws, "o1", 0, "scene", "Scene.tower", action="activate", name=["Tower"])
    observe(ws, "o2", 1, "chat", "Scene.tower", speaker={"name": "Tovan Reed"})
    assert gesture(ws, "situation")["ok"] is True
    assert (state(ws)["situation"]["scene"], state(ws)["situation"]["npcs"]) == (None, [])
