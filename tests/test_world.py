"""The living world (LW-01, LW-03..05, LW-09, LW-12..18): fronts and situations as state facts,
the deterministic world-turn and the read-only forecast. The v3 world-turn criteria T1-T8
(pf2e-open-campaign, docs/spec/33-world-turn.md) are the tests named after them."""

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import jsonschema
import pytest
import yaml
from mcp import Client

from secondchair import cli, runner
from secondchair.cli import main
from secondchair.core import calls, canon, delegation, index, jobs, knowledge, workspace, world
from secondchair.core.delegation import DelegationError
from secondchair.core.server import build_server
from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import Workspace

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "docs/contracts/action-log-entry.schema.json").read_text()
)
GM = {"kind": "gm", "words": "The Council squeezes tolls every week."}
SEEN = {"kind": "observation", "quote": "The bypass stays open.", "locator": "s1.md:4"}
DAY0 = "4725-01-01"
CONFIG = {"host": "h", "model": "m", "effort": "e"}


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path / "camp"), "--language", "en", "--calendar", "absalom"])
    return workspace.load(tmp_path / "camp")


def act(ws: Workspace, tool: str, **args: Any) -> None:
    [found] = [t for t in canon.tools(ws) if t.name == tool]
    delegation.act(ws, found, "prep-agent", lambda: found.fn(**args))


def entity(ws: Workspace, name: str) -> str:
    act(ws, "create_entity", names=[name])
    [found] = [e for e in index.search_entities(ws, name) if e["names"] == [name]]
    return found["id"]


def fact(ws: Workspace, statement: str, origin: dict = GM, **fields: Any) -> str:
    act(ws, "record_fact", statement=statement, origin=origin, **{"entities": [], **fields})
    found = [f for f in index.search_facts(ws, include_retconned=True, text=statement)]
    [found] = [f for f in found if f["statement"] == statement]
    return found["id"]


def state_fact(ws: Workspace, of: str, key: str, value: Any, origin: dict = GM) -> str:
    return fact(
        ws, f"{of} {key} {json.dumps(value)}", origin, state={"of": of, "key": key, "value": value}
    )


def front(ws: Workspace, name: str, **rule: Any) -> tuple[str, str]:
    """A front entity and its carrier, with its rule, its clock at 0 and its agenda steps."""
    me, carrier = entity(ws, name), entity(ws, f"{name} Carrier")
    steps = rule.pop("steps", {})
    rule = {"carrier": carrier, "capacity": 4, "every": "7d", "anchor": DAY0, **rule}
    state_fact(ws, me, "front", rule)
    state_fact(ws, me, "clock", 0)
    for step, when in steps.items():
        state_fact(ws, me, "agenda", {"id": step, "when": when})
    return me, carrier


def situation(ws: Workspace, name: str, **value: Any) -> str:
    me = entity(ws, name)
    state_fact(ws, me, "situation", value)
    return me


def turn(ws: Workspace, now: str) -> list[str]:
    return [
        r["key"]
        for r in world.world_turn(ws, now, since=DAY0 if world.cursor(ws) is None else None)
    ]


def clock(ws: Workspace, of: str) -> int:
    return world.state(ws)["fronts"][of]["clock"]


def occ(ws: Workspace, key: str) -> dict:
    [found] = [r for r in world.occurrences(ws) if r["key"] == key]
    return found


def queued(ws: Workspace) -> list[str]:
    return [r["key"] for r in world.occurrences(ws) if r["status"] == "queued"]


def unless_job(ws: Workspace, key: str) -> int:
    job = occ(ws, key)["job"]
    jobs.start(ws, job, CONFIG, manual=True)
    return job


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# v3 world-turn criteria


def test_t1_ticks_at_the_anchored_rate_and_a_rerun_records_nothing(ws: Workspace) -> None:
    tolls, council = front(ws, "Toll Squeeze")
    mira = entity(ws, "Mira Pell")
    rule = world._current(ws)[tolls]["front"]
    act(
        ws,
        "correct_fact",
        fact=rule["id"],
        statement=rule["statement"],
        entities=rule["entities"],
        origin=GM,
        state={**rule["state"], "value": {**rule["state"]["value"], "participants": [mira]}},
    )

    assert turn(ws, "4725-01-15") == [f"{tolls}/tick@4725-01-08", f"{tolls}/tick@4725-01-15"]
    assert turn(ws, "4725-01-15") == []
    assert world.cursor(ws) == "4725-01-15"
    assert clock(ws, tolls) == 2
    # Each tick is an offscreen event closing the old clock fact and opening the new one, at
    # the rank of the GM's rule (ADR 0009), known only to the carrier and the participant.
    [now] = [
        f
        for f in index.search_facts(ws, entity=tolls)
        if (f["state"] or {}).get("key") == "clock" and f["valid_to"] is None
    ]
    assert now["valid_from"] == "4725-01-15"
    assert now["rank"] == rule["rank"] == "agent_proposal"
    assert now["origin"] == {"kind": "rule", "fact": rule["id"], "key": f"{tolls}/tick@4725-01-15"}
    [event] = index.search_events(ws, fact=now["id"])
    assert (event["kind"], event["date"], len(event["closes"])) == ("offscreen", "4725-01-15", 1)
    knowers = index.search_knowledge(ws, [council, mira, index.PARTY])
    assert {(k["knower"], k["fact"]) for k in knowers if k["fact"] == now["id"]} == {
        (council, now["id"]),
        (mira, now["id"]),
    }
    entries = [yaml.safe_load(p.read_text()) for p in sorted((ws.root / "action-log").glob("*"))]
    for e in entries:
        jsonschema.validate(e, SCHEMA)
    assert {e["occurrence"] for e in entries if e.get("agent") == "world-turn"} == {
        f"{tolls}/tick@4725-01-08",
        f"{tolls}/tick@4725-01-15",
    }


def test_t2_a_dated_step_is_scheduled_once_over_three_runs(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze", steps={"draft": {"date": "4725-01-10"}})

    first = turn(ws, "4725-01-12")
    assert f"{tolls}/draft" in first
    assert turn(ws, "4725-01-12") == []
    assert f"{tolls}/draft" not in turn(ws, "4725-02-01")
    assert world.state(ws)["fronts"][tolls]["agenda"] == {"draft": "done"}


def test_t3_the_world_turn_writes_rule_effects_only_and_queues_consequences(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    before = {f["id"] for f in index.search_facts(ws, include_retconned=True)}

    turn(ws, "4725-01-08")

    new = [f for f in index.search_facts(ws, include_retconned=True) if f["id"] not in before]
    assert [f["origin"]["kind"] for f in new] == ["rule"]  # the clock; no invented consequence
    [job] = [j for j in jobs.pending(ws) if j["playbook"] == "propose-consequences"]
    assert job["inputs"] == {"occurrences": f"{tolls}/tick@4725-01-08"}
    assert job["responsibility"] == "living_world"


def test_t4_an_unless_is_settled_by_citing_facts_valid_on_the_tick_date(ws: Workspace) -> None:
    silt, _ = front(ws, "Silt Choke", unless="the bypass is open")
    closed = fact(ws, "The bypass is closed.", valid_from=DAY0)
    late = fact(ws, "The bypass is guarded.", valid_from="4725-02-01")
    key = f"{silt}/tick@4725-01-08"

    turn(ws, "4725-01-08")
    assert queued(ws) == [key]  # the job settles it; the Core calls no model (LW-06)
    job = unless_job(ws, key)
    assert jobs.read(ws, job)["playbook"] == "settle-an-unless"

    with pytest.raises(index.CanonError, match="not canon facts valid on 4725-01-08"):
        world.settle_unless(ws, key, False, [late], job)
    record = world.settle_unless(ws, key, False, [closed], job)

    assert record["status"] == "applied"
    assert occ(ws, key)["cites"] == [closed]
    assert clock(ws, silt) == 1


def test_an_unless_that_holds_suppresses_the_tick_and_one_left_unsettled_calls_at_the_break(
    ws: Workspace,
) -> None:
    silt, _ = front(ws, "Silt Choke", unless="the bypass is open")
    opened = fact(ws, "The bypass is open.", SEEN, valid_from=DAY0)
    turn(ws, "4725-01-15")
    first, second = f"{silt}/tick@4725-01-08", f"{silt}/tick@4725-01-15"

    assert (
        world.settle_unless(ws, first, True, [opened], unless_job(ws, first))["status"]
        == "suppressed"
    )
    world.settle_unless(ws, second, None, [], unless_job(ws, second))

    assert clock(ws, silt) == 0
    assert queued(ws) == [second]
    [call] = [c for c in calls.take_break(ws) if c["kind"] == "exception"]
    assert second in call["message"] and call["deadline"] == "break"
    delegation.change_moment(ws, "between-sessions")  # unanswered: no tick, still queued
    assert queued(ws) == [second] and clock(ws, silt) == 0


def test_t5_a_tick_crossing_a_threshold_triggers_its_step_once(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze", steps={"draft": {"clock_gte": 3}})
    silt, _ = front(
        ws, "Silt Choke", unless="the bypass is open", steps={"petition": {"clock_gte": 1}}
    )
    closed = fact(ws, "The bypass is closed.", valid_from=DAY0)

    turn(ws, "4725-01-29")

    assert occ(ws, f"{tolls}/draft")["date"] == "4725-01-22"  # dated at the crossing tick
    assert occ(ws, f"{tolls}/draft")["cause"] == f"{tolls}/tick@4725-01-22"
    assert [r["key"] for r in world.occurrences(ws)].count(f"{tolls}/draft") == 1
    # An unless tick counts once settled: applied later, it crosses its threshold then (T5).
    assert world.state(ws)["fronts"][silt]["agenda"] == {"petition": "pending"}
    key = f"{silt}/tick@4725-01-08"
    world.settle_unless(ws, key, False, [closed], unless_job(ws, key))
    assert (occ(ws, f"{silt}/petition")["date"], occ(ws, f"{silt}/petition")["status"]) == (
        "4725-01-08",
        "applied",
    )
    key = f"{silt}/tick@4725-01-15"
    world.settle_unless(ws, key, False, [closed], unless_job(ws, key))
    assert [r["key"] for r in world.occurrences(ws)].count(f"{silt}/petition") == 1


def test_t6_the_queue_survives_reruns_and_a_late_accept_keeps_its_original_date(
    ws: Workspace,
) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    silt, _ = front(
        ws, "Silt Choke", unless="the bypass is open", steps={"petition": {"clock_gte": 1}}
    )
    late = f"{silt}/tick@4725-01-08"

    turn(ws, "4725-01-15")  # invocation 1
    assert clock(ws, tolls) == 2 and late in queued(ws)
    consequences = [j for j in jobs.pending(ws) if j["playbook"] == "propose-consequences"]
    assert len(consequences) == 1
    pending = (queued(ws), len(jobs.pending(ws)), len(world.occurrences(ws)))

    assert turn(ws, "4725-01-15") == []  # invocation 2: nothing new, nothing duplicated
    assert (queued(ws), len(jobs.pending(ws)), len(world.occurrences(ws))) == pending

    with patch.object(cli, "interactive", return_value=True):  # the GM accepts the tick
        assert main(["world", "decide", late, "accept", "-w", str(ws.root)]) == 0
    assert occ(ws, late)["status"] == "applied"
    [tick] = [f for f in index.search_facts(ws, entity=silt) if f["origin"].get("key") == late]
    assert tick["valid_from"] == "4725-01-08"  # LW-17: dated at its original date
    assert occ(ws, f"{silt}/petition")["status"] == "applied"  # its cascade, once
    turn(ws, "4725-01-15")
    assert [r["key"] for r in world.occurrences(ws)].count(f"{silt}/petition") == 1


def test_t7_a_pause_has_no_catch_up_and_a_resume_reanchors(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    turn(ws, "4725-01-08")
    with pytest.raises(DelegationError, match="pause on or before"):
        world.set_active(ws, tolls, False, "4725-01-09", authenticated=True)

    world.set_active(ws, tolls, False, "4725-01-08", authenticated=True)
    assert turn(ws, "4725-01-29") == []  # three weeks paused
    with pytest.raises(DelegationError, match="Resume on or after"):
        world.set_active(ws, tolls, True, "4725-01-20", authenticated=True)
    world.set_active(ws, tolls, True, "4725-01-31", authenticated=True)

    assert turn(ws, "4725-02-14") == [f"{tolls}/tick@4725-02-07", f"{tolls}/tick@4725-02-14"]
    assert clock(ws, tolls) == 3
    rule = world._current(ws)[tolls]["front"]
    assert rule["rank"] == "gm_decision" and rule["state"]["value"]["anchor"] == "4725-01-31"


def test_t8_rescheduling_creates_a_linked_key_and_the_old_one_is_never_planned(
    ws: Workspace,
) -> None:
    silt, _ = front(ws, "Silt Choke", unless="the bypass is open")
    key = f"{silt}/tick@4725-01-08"
    turn(ws, "4725-01-08")

    world.decide(ws, key, "reschedule", authenticated=True, date="4725-01-20")

    assert occ(ws, key)["status"] == "rescheduled"
    assert occ(ws, key)["rescheduled_to"] == f"{key}~4725-01-20"
    assert key not in [o["key"] for o in world.forecast(ws, "4725-01-20")]
    assert f"{key}~4725-01-20" not in [o["key"] for o in world.forecast(ws, "4725-01-14")]
    recorded = turn(ws, "4725-01-20")
    assert f"{key}~4725-01-20" in recorded and key not in recorded
    assert occ(ws, f"{key}~4725-01-20")["rescheduled_from"] == key
    with pytest.raises(DelegationError, match="rescheduled, not queued"):
        world.decide(ws, key, "accept", authenticated=True)


# The other living-world contracts


def test_a_key_is_used_once_even_when_rejected(ws: Workspace) -> None:
    silt, _ = front(ws, "Silt Choke", unless="the bypass is open")
    key = f"{silt}/tick@4725-01-08"
    turn(ws, "4725-01-08")

    world.decide(ws, key, "reject", authenticated=True)

    turn(ws, "4725-02-01")
    assert [r["key"] for r in world.occurrences(ws)].count(key) == 1
    assert occ(ws, key)["status"] == "rejected"
    with pytest.raises(DelegationError, match="already used"):
        world._register(ws, {"key": key})


def test_more_than_six_ticks_of_one_front_are_shown_grouped_with_one_key_each(
    ws: Workspace,
) -> None:
    tolls, _ = front(ws, "Toll Squeeze", capacity=10)
    silt, _ = front(ws, "Silt Choke", capacity=10, every="14d")

    planned = world.plan(ws, DAY0, "4725-02-19")
    shown = world.present(planned)

    [group] = [o for o in shown if o["kind"] == "ticks"]
    assert group["entity"] == tolls and len(group["keys"]) == 7 == len(set(group["keys"]))
    assert [o["entity"] for o in shown if o["kind"] == "tick"] == [silt] * 3
    assert len(planned) == 10
    with patch.object(cli, "interactive", return_value=True):
        assert main(["world", "turn", "4725-02-19", "--since", DAY0, "-w", str(ws.root)]) == 0
    assert clock(ws, tolls) == 7


def test_the_clock_stops_at_its_capacity(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze", capacity=2)
    assert len(turn(ws, "4725-03-01")) == 2
    assert clock(ws, tolls) == 2


def test_an_occurrence_contradicting_played_canon_becomes_a_call_and_stays_queued(
    ws: Workspace,
) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    played = state_fact(ws, tolls, "clock", 3, SEEN)  # the table settled the clock
    [zero] = [
        f
        for f in index.search_facts(ws, entity=tolls)
        if (f["state"] or {}).get("key") == "clock" and f["rank"] != "played"
    ]
    act(
        ws,
        "record_event",
        description="The squeeze was played out.",
        date=DAY0,
        origin=SEEN,
        kind="played",
        opens=[played],
        closes=[zero["id"]],
    )
    key = f"{tolls}/tick@4725-01-08"

    turn(ws, "4725-01-08")

    assert occ(ws, key)["status"] == "queued" and clock(ws, tolls) == 3
    [call] = [c for c in calls.read_calls(ws) if c["id"] == occ(ws, key)["call"]]
    assert (call["kind"], call["status"]) == ("exception", "open")
    assert played in call["message"]
    turn(ws, "4725-01-08")
    assert queued(ws) == [key]  # still queued by default
    world.decide(ws, key, "reject", authenticated=True)
    assert [c["status"] for c in calls.read_calls(ws) if c["id"] == call["id"]] == ["answered"]


def test_a_world_turn_is_refused_during_a_live_session(ws: Workspace) -> None:
    front(ws, "Toll Squeeze")
    delegation.change_moment(ws, "live-session")

    with pytest.raises(DelegationError, match="never runs during a live session"):
        turn(ws, "4725-01-08")
    assert world.occurrences(ws) == [] and world.cursor(ws) is None


def test_the_cursor_never_moves_back(ws: Workspace) -> None:
    front(ws, "Toll Squeeze")
    turn(ws, "4725-01-15")
    with pytest.raises(DelegationError, match="never moves back"):
        turn(ws, "4725-01-08")
    with pytest.raises(DelegationError, match="only moves forward"):
        world.world_turn(ws, "4725-02-01", since=DAY0)


def test_a_forecast_leaves_the_workspace_byte_identical(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze", steps={"draft": {"clock_gte": 2}})
    front(ws, "Silt Choke", unless="the bypass is open")
    situation(ws, "Replace the Rope", stage="available", deadline="4725-01-20")
    turn(ws, "4725-01-08")
    index.search_facts(ws)  # the derived index is up to date
    before = snapshot(ws.root)

    forecast = world.forecast(ws, "4725-01-29")

    assert snapshot(ws.root) == before
    assert f"{tolls}/draft" in [o["key"] for o in forecast]
    assert sorted(o["key"] for o in forecast) == sorted(turn(ws, "4725-01-29"))
    with patch.object(cli, "interactive", return_value=True):
        assert main(["world", "forecast", "4725-03-01", "-w", str(ws.root)]) == 0


def test_undoing_an_effect_undoes_its_cascade_and_returns_the_keys_to_the_queue(
    ws: Workspace,
) -> None:
    tolls, _ = front(ws, "Toll Squeeze", steps={"draft": {"clock_gte": 2}})
    turn(ws, "4725-01-22")
    first, second, third = (f"{tolls}/tick@4725-01-{d}" for d in ("08", "15", "22"))
    assert clock(ws, tolls) == 3
    facts_before = len(index.search_facts(ws))

    undone = world.undo(ws, second, "other", "cli", authenticated=True)

    assert undone == sorted([second, third, f"{tolls}/draft"])
    assert clock(ws, tolls) == 1
    assert world.state(ws)["fronts"][tolls]["agenda"] == {"draft": "pending"}
    assert sorted(queued(ws)) == undone
    assert len(index.search_facts(ws)) == facts_before - 3
    assert turn(ws, "4725-01-22") == []  # their keys are not planned again
    world.decide(ws, second, "accept", authenticated=True)  # the step comes back with it
    assert occ(ws, f"{tolls}/draft")["status"] == "applied"
    assert clock(ws, tolls) == 2

    delegation.change_moment(ws, "between-sessions")  # the moment is frozen
    with pytest.raises(DelegationError, match="frozen"):
        world.undo(ws, first, "other", "cli", authenticated=True)


def test_a_situation_deadline_expires_it_unless_the_party_engaged_it(ws: Workspace) -> None:
    orin = entity(ws, "Orin Doss")
    ferry = situation(
        ws, "Replace the Rope", stage="available", deadline="4725-01-20", participants=[orin]
    )
    chain = situation(ws, "Inspect the Chain", stage="active", deadline="4725-01-10")

    turn(ws, "4725-02-01")

    assert world.state(ws)["situations"] == {
        ferry: {"stage": "expired", "deadline": "4725-01-20"},
        chain: {"stage": "active", "deadline": "4725-01-10"},
    }
    expired = [f for f in index.search_facts(ws, entity=ferry) if f["valid_to"] is None]
    assert {k["knower"] for k in index.search_knowledge(ws, [orin, index.PARTY])} == {orin}
    assert expired[0]["valid_from"] == "4725-01-20"
    # An engaged situation's deadline is new narrative: a job, never applied by the Core.
    narrative = occ(ws, f"{chain}/deadline@4725-01-10")
    assert (narrative["class"], narrative["status"]) == ("narrative", "queued")
    assert jobs.read(ws, narrative["job"])["responsibility"] == "narrative_direction"
    with pytest.raises(DelegationError, match="new narrative"):
        world.decide(ws, narrative["key"], "accept", authenticated=True)


def test_at_propose_rule_effects_wait_for_the_gm(ws: Workspace) -> None:
    table = yaml.safe_load((ws.root / "delegation.yaml").read_text())
    table["prep"]["living_world"]["level"] = "propose"
    (ws.root / "delegation.yaml").write_text(yaml.safe_dump(table))
    tolls, _ = front(ws, "Toll Squeeze")
    key = f"{tolls}/tick@4725-01-08"

    turn(ws, "4725-01-08")

    assert queued(ws) == [key] and clock(ws, tolls) == 0
    assert calls.read_calls(ws)[-1]["kind"] == "proposal"
    world.decide(ws, key, "accept", authenticated=True)
    assert clock(ws, tolls) == 1


def test_agents_read_the_living_world_and_settle_an_unless_over_mcp(ws: Workspace) -> None:
    silt, _ = front(ws, "Silt Choke", unless="the bypass is open")
    closed = fact(ws, "The bypass is closed.", valid_from=DAY0)
    turn(ws, "4725-01-08")
    key = f"{silt}/tick@4725-01-08"
    job = unless_job(ws, key)

    async def run() -> tuple[Any, Any, Any]:
        async with Client(build_server(ws)) as client:
            seen = await client.call_tool("living_world", {})
            ahead = await client.call_tool("forecast_world", {"until": "4725-01-22"})
            settled = await client.call_tool(
                "settle_unless",
                {"occurrence": key, "unless_holds": False, "cites": [closed], "job": job},
            )
            return seen, ahead, settled

    seen, ahead, settled = asyncio.run(run())
    assert [r["key"] for r in seen.structured_content["queued"]] == [key]
    assert [o["key"] for o in ahead.structured_content["result"]] == [
        f"{silt}/tick@4725-01-15",
        f"{silt}/tick@4725-01-22",
    ]
    assert not settled.is_error and clock(ws, silt) == 1


def test_a_state_fact_must_have_a_shape_the_world_turn_reads(ws: Workspace) -> None:
    tolls = entity(ws, "Toll Squeeze")
    for value, message in (
        ({"carrier": tolls, "capacity": 0, "every": "7d", "anchor": DAY0}, "capacity"),
        ({"carrier": tolls, "capacity": 2, "every": "1m", "anchor": DAY0}, "uration"),
        ({"carrier": "e-nobody", "capacity": 2, "every": "7d", "anchor": DAY0}, "Unknown"),
    ):
        with pytest.raises(index.CanonError, match=message):
            state_fact(ws, tolls, "front", value)
    with pytest.raises(index.CanonError, match="Unknown state key"):
        state_fact(ws, tolls, "mood", 1)
    with pytest.raises(index.CanonError, match="rule effect"):
        fact(ws, "x", {"kind": "rule", "fact": "f-1", "key": "k"})


def test_a_front_ruled_at_the_played_rank_keeps_ticking(ws: Workspace) -> None:
    me, carrier = entity(ws, "Toll Squeeze"), entity(ws, "Lock Council")
    rule = {"carrier": carrier, "capacity": 4, "every": "7d", "anchor": DAY0}
    state_fact(ws, me, "front", rule, SEEN)  # the table played the rule itself

    turn(ws, "4725-01-15")

    assert clock(ws, me) == 2 and queued(ws) == []


def test_a_rescheduled_threshold_step_applies_on_its_new_date(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze", steps={"draft": {"clock_gte": 1}})
    turn(ws, "4725-01-08")
    world.undo(ws, f"{tolls}/draft", "other", "cli", authenticated=True)

    with pytest.raises(DelegationError, match="needs the new date"):
        world.decide(ws, f"{tolls}/draft", "reschedule", authenticated=True)
    world.decide(ws, f"{tolls}/draft", "reschedule", authenticated=True, date="4725-01-20")
    turn(ws, "4725-01-20")

    assert occ(ws, f"{tolls}/draft~4725-01-20")["status"] == "applied"
    assert world.state(ws)["fronts"][tolls]["agenda"] == {"draft": "done"}


def test_an_unless_is_not_settled_during_a_live_session(ws: Workspace) -> None:
    silt, _ = front(ws, "Silt Choke", unless="the bypass is open")
    closed = fact(ws, "The bypass is closed.", valid_from=DAY0)
    turn(ws, "4725-01-08")
    key = f"{silt}/tick@4725-01-08"
    job = unless_job(ws, key)
    delegation.change_moment(ws, "live-session")

    with pytest.raises(DelegationError, match="live session"):
        world.settle_unless(ws, key, False, [closed], job)
    assert queued(ws) == [key]


# World-turn jobs (LW-06, LW-08, DEL-08, VIS-01)


def set_level(ws: Workspace, moment: str, responsibility: str, level: str) -> None:
    table = yaml.safe_load((ws.root / "delegation.yaml").read_text())
    table[moment][responsibility]["level"] = level
    (ws.root / "delegation.yaml").write_text(yaml.safe_dump(table))


def job_act(ws: Workspace, tool: str, job: int, **args: Any) -> delegation.ActionResult:
    [found] = [t for t in [*canon.tools(ws), *knowledge.tools(ws)] if t.name == tool]
    return delegation.act(ws, found, "world-agent", lambda: found.fn(**args), job=job)


def test_every_world_turn_job_has_a_playbook_matching_its_contract(ws: Workspace) -> None:
    front(ws, "Toll Squeeze")
    front(ws, "Silt Choke", unless="the bypass is open")
    situation(ws, "Inspect the Chain", stage="active", deadline="4725-01-08")
    turn(ws, "4725-01-08")

    queued_jobs = jobs.pending(ws)
    assert sorted(j["playbook"] for j in queued_jobs) == [
        "propose-consequences",
        "propose-narrative-direction",
        "settle-an-unless",
    ]
    for job in queued_jobs:  # the Core cannot read playbooks (ARC-01): they must agree
        meta = runner.playbook(job["playbook"])
        assert meta["responsibility"] == job["responsibility"]
        assert meta["tier"] == job["tier"]
        assert meta["expected-output"] == job["expected_output"]
        assert meta["inputs"] == ",".join(sorted(job["inputs"]))


def test_new_narrative_is_held_at_propose_whatever_its_cell(ws: Workspace) -> None:
    set_level(ws, "prep", "narrative_direction", "autonomous")
    chain = situation(ws, "Inspect the Chain", stage="active", deadline="4725-01-10")
    turn(ws, "4725-01-10")
    job = occ(ws, f"{chain}/deadline@4725-01-10")["job"]
    jobs.start(ws, job, CONFIG, manual=True)

    assert delegation.effective_level(ws, "narrative_direction", "prep", True) == "propose"
    # Whatever tool it uses, the job's new narrative is a narrative-direction action (ADR 0009).
    result = job_act(
        ws,
        "record_fact",
        job,
        statement="The chain snaps.",
        entities=[chain],
        origin={"kind": "job", "job": str(job)},
    )
    entry = delegation.read_entry(ws, result["entry"])
    assert result["status"] == "pending"
    assert (entry["responsibility"], entry["effective_level"]) == ("narrative_direction", "propose")


def test_a_derived_consequence_is_an_agent_proposal_at_the_living_world_level(
    ws: Workspace,
) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    mira = entity(ws, "Mira Pell")
    turn(ws, "4725-01-08")
    [job] = [j["id"] for j in jobs.pending(ws) if j["playbook"] == "propose-consequences"]
    jobs.start(ws, job, CONFIG, manual=True)
    [tick] = [f for f in index.search_facts(ws, entity=tolls) if f["origin"]["kind"] == "rule"]
    origin = {"kind": "job", "job": str(job)}
    learn = {"fact": tick["id"], "origin": origin, "date": "4725-01-09"}

    # LW-08: the living world never discloses; reaching the party goes through disclosure.
    with pytest.raises(DelegationError, match="never discloses"):
        job_act(ws, "record_knowledge", job, knower=index.PARTY, **learn)
    result = job_act(ws, "record_knowledge", job, knower=mira, **learn)

    assert result["status"] == "applied"  # living_world is at act-then-review in prep
    assert delegation.read_entry(ws, result["entry"])["responsibility"] == "living_world"
    learnt = {k["knower"]: k["rank"] for k in index.search_knowledge(ws, [mira, index.PARTY])}
    assert learnt == {mira: "agent_proposal"}

    # Nor through a disclosure tool; and the tool's own cell still binds the job (DEL-23).
    tell = Tool(
        fn=lambda: Change("canon/x.md", "x"),
        responsibility="disclosure",
        delegated_action=True,
        reversible=False,
    )
    with pytest.raises(DelegationError, match="never discloses"):
        delegation.act(ws, tell, "world-agent", tell.fn, job=job)
    set_level(ws, "prep", "memory", "manual")
    with pytest.raises(DelegationError, match="memory is at manual"):
        job_act(ws, "record_fact", job, statement="Tolls rise.", entities=[tolls], origin=origin)
