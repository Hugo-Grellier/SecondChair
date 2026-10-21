"""The living world (LW-01, LW-03..05, LW-09, LW-12..18): fronts and situations as state facts,
the deterministic world-turn and the read-only forecast. The v3 world-turn criteria T1-T8
(pf2e-open-campaign, docs/spec/33-world-turn.md) are the tests named after them."""

import asyncio
import json
import shutil
from collections import Counter
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import patch

import jsonschema
import pytest
import yaml
from mcp import Client

from secondchair import cli, runner
from secondchair.cli import main
from secondchair.core import (
    calls,
    canon,
    capture,
    delegation,
    index,
    jobs,
    journal,
    knowledge,
    observations,
    workspace,
    world,
)
from secondchair.core.delegation import DelegationError
from secondchair.core.server import build_server
from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import Workspace

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "docs/contracts/action-log-entry.schema.json").read_text()
)
GM = {"kind": "gm", "words": "The Council squeezes tolls every week."}
# A played origin quotes an observation the Core finds (ADR 0015); the `ws` fixture records it.
SEEN = {
    "kind": "observation",
    "quote": "The bypass stays open.",
    "locator": "observations/outside-sessions.jsonl#seen",
}
DAY0 = "4725-01-01"
DATES = ("4725-01-07", "4725-01-08", "4725-01-14", "4725-01-15")
CONFIG = {"host": "h", "model": "m", "effort": "e"}


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path / "camp"), "--language", "en", "--calendar", "absalom"])
    ws = workspace.load(tmp_path / "camp")
    seen = {"id": "seen", "session": None, "at": "2026-10-19T20:15:00+00:00", "scene": None}
    seen |= {"actor": None, "kind": "chat", "visibility": "players"}
    assert observations.record(ws, seen | {"payload": {"text": SEEN["quote"]}}) is None
    return ws


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


def inverted(ws: Workspace) -> list[str]:
    """The facts whose validity ends before it starts."""
    on = partial(index.date_key, ws.calendar)
    return [
        f["id"]
        for f in index.search_facts(ws, include_retconned=True)
        if f["valid_from"] and f["valid_to"] and on(f["valid_to"]) < on(f["valid_from"])
    ]


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


def test_a_believed_or_future_state_fact_is_not_current_until_its_date(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    rumour = entity(ws, "Rumoured Raid")
    rule = {"carrier": tolls, "capacity": 4, "every": "7d", "anchor": DAY0}
    fact(
        ws,
        "A raid is coming.",
        never_true=True,
        state={"of": rumour, "key": "front", "value": rule},
    )
    flood = situation(ws, "Spring Flood", stage="available", deadline=None)
    late = world._current(ws)[flood]["situation"]
    act(
        ws,
        "correct_fact",
        fact=late["id"],
        statement=late["statement"],
        entities=[],
        origin=GM,
        state=late["state"],
        valid_from="4725-02-01",
    )

    turn(ws, "4725-01-15")

    assert rumour not in world.state(ws)["fronts"]  # a belief never drives the world (#170)
    assert flood not in world.state(ws)["situations"]  # it starts after the cursor
    assert clock(ws, tolls) == 2  # ticks within one turn still see the clock they just moved
    turn(ws, "4725-02-01")
    assert flood in world.state(ws)["situations"]


def test_unless_ticks_settled_out_of_order_move_the_one_clock(ws: Workspace) -> None:
    silt, _ = front(ws, "Silt Choke", unless="the bypass is open")
    closed = fact(ws, "The bypass is closed.", valid_from=DAY0)
    turn(ws, "4725-01-15")
    k1, k2 = f"{silt}/tick@4725-01-08", f"{silt}/tick@4725-01-15"

    world.settle_unless(ws, k2, False, [closed], unless_job(ws, k2))
    world.settle_unless(ws, k1, False, [closed], unless_job(ws, k1))  # applied after a later one

    assert clock(ws, silt) == 2  # #205 review: the head of the chain, not a second open clock
    # #170: the late tick takes hold on the head's start, so the history never overlaps: one
    # clock holds on each date, and no fact ends before it starts.
    on = {d: world._current(ws, at=d)[silt]["clock"]["state"]["value"] for d in DATES}
    assert on == {"4725-01-07": 0, "4725-01-08": 0, "4725-01-14": 0, "4725-01-15": 2}
    turn(ws, "4725-01-22")
    k3 = f"{silt}/tick@4725-01-22"
    world.settle_unless(ws, k3, False, [closed], unless_job(ws, k3))
    assert clock(ws, silt) == 3  # the head is the fact no event closes, not the latest start
    assert not inverted(ws)


def test_a_retcon_of_an_out_of_order_tick_replaces_every_event_of_its_key(ws: Workspace) -> None:
    silt, _ = front(ws, "Silt Choke", unless="the bypass is open")
    closed = fact(ws, "The bypass is closed.", valid_from=DAY0)
    turn(ws, "4725-01-15")
    k1, k2 = f"{silt}/tick@4725-01-08", f"{silt}/tick@4725-01-15"
    world.settle_unless(ws, k2, False, [closed], unless_job(ws, k2))
    world.settle_unless(ws, k1, False, [closed], unless_job(ws, k1))
    delegation.change_moment(ws, "between-sessions")  # frozen: only a retcon changes it now
    with pytest.raises(DelegationError, match="frozen"):
        world.undo(ws, k1, "other", "cli", authenticated=True)

    # #170: the GM retcons exactly the event dated on the tick; its other event goes with it.
    retcon = {"kind": "gm", "words": "That first silt tick never happened."}
    act(
        ws,
        "record_event",
        description="No silt that week.",
        date="4725-01-08",
        origin=retcon,
        replaces=world._id("v", k1, "event"),
    )
    [pending] = [e for e in index.search_events(ws) if e["replaces"]]
    with patch.object(cli, "interactive", return_value=True):
        assert main(["confirm", pending["id"], "-w", str(ws.root)]) == 0

    assert clock(ws, silt) == 1  # the tick of 01-15 stands, as after an in-order retcon
    assert world._current(ws, head=True)[silt]["clock"]["state"]["value"] == 1  # one head
    replaced = {e["id"] for e in index.search_events(ws) if e["status"] == "replaced"}
    assert replaced == {world._id("v", k1, "event"), world._id("v", k1, "close")}


def test_before_the_first_world_turn_the_world_is_read_on_the_current_date(
    ws: Workspace,
) -> None:
    flood = situation(ws, "Spring Flood", stage="available", deadline=None)
    late = world._current(ws)[flood]["situation"]
    act(
        ws,
        "correct_fact",
        fact=late["id"],
        statement=late["statement"],
        entities=[],
        origin=GM,
        state=late["state"],
        valid_from="4725-02-01",
    )
    assert flood in world.state(ws)["situations"]  # no date at all: the open state facts

    capture.set_current_date(ws, "4725-01-20")
    assert flood not in world.state(ws)["situations"]  # #170: it starts after the date
    capture.set_current_date(ws, "4725-02-01")
    assert flood in world.state(ws)["situations"]  # start-inclusive


def test_one_entity_holds_one_state_per_key_on_a_date(ws: Workspace) -> None:
    flood = situation(ws, "Spring Flood", stage="available")
    old = world._current(ws)[flood]["situation"]
    act(
        ws,
        "correct_fact",
        fact=old["id"],
        statement=old["statement"],
        entities=[],
        origin=GM,
        state=old["state"],
        valid_to="4725-01-10",
    )
    rising = {**old["state"], "value": {**old["state"]["value"], "stage": "active"}}
    new = fact(ws, "The flood rises.", state=rising, entities=[flood], valid_from="4725-01-10")

    # A same-day transition: the old state ends where the new one starts (end-exclusive).
    assert world._current(ws, at="4725-01-09")[flood]["situation"]["id"] == old["id"]
    assert world._current(ws, at="4725-01-10")[flood]["situation"]["id"] == new
    act(
        ws,
        "correct_fact",
        fact=new,
        statement="The flood rises.",
        entities=[flood],
        origin=GM,
        state=rising,
        valid_from="4725-01-09",
    )
    with pytest.raises(index.CanonError, match="two situation facts"):
        world._current(ws, at="4725-01-09")  # two stages at once is refused, never picked


def test_a_dated_step_fires_while_its_front_holds_end_exclusive(ws: Workspace) -> None:
    tolls, _ = front(
        ws,
        "Toll Squeeze",
        capacity=9,
        steps={"inside": {"date": "4725-01-19"}, "on-end": {"date": "4725-01-20"}},
    )
    rule = world._current(ws)[tolls]["front"]
    act(
        ws,
        "correct_fact",
        fact=rule["id"],
        statement=rule["statement"],
        entities=[],
        origin=GM,
        state=rule["state"],
        valid_to="4725-01-20",
    )

    keys = turn(ws, "4725-02-01")

    assert f"{tolls}/inside" in keys and f"{tolls}/on-end" not in keys


def test_a_front_starting_inside_the_window_ticks_from_its_start(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    rule = world._current(ws)[tolls]["front"]
    act(
        ws,
        "correct_fact",
        fact=rule["id"],
        statement=rule["statement"],
        entities=[],
        origin=GM,
        state=rule["state"],
        valid_from="4725-01-10",
    )

    assert turn(ws, "4725-01-22") == [f"{tolls}/tick@4725-01-15", f"{tolls}/tick@4725-01-22"]


def test_a_front_the_gm_ends_in_the_future_ticks_until_its_end(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    rule = world._current(ws)[tolls]["front"]
    act(
        ws,
        "correct_fact",
        fact=rule["id"],
        statement=rule["statement"],
        entities=[],
        origin=GM,
        state=rule["state"],
        valid_to="4725-01-20",
    )

    assert turn(ws, "4725-01-29") == [f"{tolls}/tick@4725-01-08", f"{tolls}/tick@4725-01-15"]
    assert world.world_turn(ws, "4725-01-29") == []  # no exception call either
    assert not list(ws.root.glob("calls/*.yaml"))


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
        declared = {i.strip().removesuffix("?") for i in meta["inputs"].split(",")}
        assert set(job["inputs"]) <= declared  # an optional input (`?`) a job may leave out
        assert {i for i in meta["inputs"].split(",") if not i.endswith("?")} <= set(job["inputs"])


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


def test_a_proposal_from_an_observation_stays_pending_never_applied(ws: Workspace) -> None:
    set_level(ws, "prep", "narrative_direction", "autonomous")
    chain = situation(ws, "Inspect the Chain", stage="active", deadline="4725-01-10")
    queued = runner.queue(ws, "propose-narrative-direction", {"observation": "f-1"})
    jobs.start(ws, queued["id"], CONFIG, manual=True)
    result = job_act(
        ws,
        "record_fact",
        queued["id"],
        statement="The bridge guild notices the party.",
        entities=[chain],
        origin={"kind": "job", "job": str(queued["id"])},
    )
    entry = delegation.read_entry(ws, result["entry"])
    assert result["status"] == "pending"
    assert (entry["responsibility"], entry["effective_level"]) == ("narrative_direction", "propose")
    assert "occurrence" not in entry
    with pytest.raises(runner.RunnerError):  # an unknown input is still refused
        runner.queue(ws, "propose-narrative-direction", {"nope": "x"})


def test_a_narrative_occurrence_follows_the_gm_answer_to_its_proposal(ws: Workspace) -> None:
    chain = situation(ws, "Inspect the Chain", stage="active", deadline="4725-01-10")
    turn(ws, "4725-01-10")
    key = f"{chain}/deadline@4725-01-10"
    job = occ(ws, key)["job"]
    jobs.start(ws, job, CONFIG, manual=True)

    def propose(statement: str) -> int:
        origin = {"kind": "job", "job": str(job)}
        args = {"statement": statement, "entities": [chain], "origin": origin}
        result = job_act(ws, "record_fact", job, **args)
        assert delegation.read_entry(ws, result["entry"])["occurrence"] == key
        return result["entry"]

    # A rejected proposal leaves the occurrence queued.
    delegation.reject(ws, propose("The chain holds."), "tone", "cli", authenticated=True)
    assert occ(ws, key)["status"] == "queued"

    # An approved one applies it: it leaves the queue (and S0's narrative_pending).
    snaps, rusts = propose("The chain snaps."), propose("The chain rusts.")
    delegation.approve(ws, snaps, "cli", authenticated=True)
    delegation.approve(ws, rusts, "cli", authenticated=True)
    assert (occ(ws, key)["status"], occ(ws, key)["entries"]) == ("applied", [snaps, rusts])
    assert key not in queued(ws)

    # LW-12: undoing the applied outcome returns it to the queue, entry by entry or as a whole.
    delegation.undo(ws, rusts, "other", "cli", authenticated=True)
    assert (occ(ws, key)["status"], occ(ws, key)["entries"]) == ("applied", [snaps])
    assert world.undo(ws, key, "other", "cli", authenticated=True) == [key]
    assert (occ(ws, key)["status"], occ(ws, key)["entries"]) == ("queued", [])
    assert delegation.read_entry(ws, snaps)["status"] == "undone"


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


# Faction state facts (ADR 0022, LW-02, LW-03, LW-20)


def faction(ws: Workspace) -> tuple[str, str, str]:
    """A faction with its four state facts, written by the GM; its front and a rival."""
    tolls, _ = front(ws, "Toll Squeeze")
    council, rival = entity(ws, "Council"), entity(ws, "Guild")
    goal = {"id": "tolls", "goal": "Own the river", "pursues": [tolls]}
    state_fact(ws, council, "intent", [goal])
    state_fact(ws, council, "pool", {"coin": {"value": 3, "income": 2, "cap": 10}})
    state_fact(ws, council, "capacity", 1)
    bribe: dict[str, Any] = {"id": "bribe", "cost": {"coin": 2}, "duration": "1w"}
    bribe |= {"effect": {"class": "derived", "does": "A toll clerk looks away."}}
    bribe |= {"prerequisites": [{"front": tolls, "clock_gte": 1}], "contest": {"pool": "coin"}}
    state_fact(ws, council, "catalogue", [bribe | {"target": rival}])
    return council, tolls, rival


def test_a_faction_holds_intent_pool_capacity_and_catalogue_as_state_facts(
    ws: Workspace,
) -> None:
    council, tolls, rival = faction(ws)

    s = world._current(ws)[council]
    assert {k for k in s if s[k]} == {"intent", "pool", "capacity", "catalogue"}
    [bribe] = s["catalogue"]["state"]["value"]
    assert bribe["contest"] == {"pool": "coin"} and bribe["target"] == rival
    assert {council, tolls, rival} <= set(s["catalogue"]["entities"])  # what it names
    assert world.state(ws)["fronts"].keys() == {tolls}  # a faction is no front


def test_a_faction_state_fact_must_have_a_shape_the_world_turn_reads(ws: Workspace) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    council = entity(ws, "Council")
    goal = {"id": "tolls", "goal": "Own the river", "pursues": [tolls]}
    coin = {"value": 3, "income": 2, "cap": 10}
    effect = {"class": "derived", "does": "A clerk looks away."}
    bribe = {"id": "bribe", "cost": {"coin": 2}, "duration": "1w", "effect": effect}
    for key, value, message in (
        ("intent", [], "list of 1 to 3"),
        ("intent", [goal] * 4, "list of 1 to 3"),
        ("intent", [goal, goal], "own id"),
        ("intent", [goal | {"pursues": []}], "pursues"),
        ("intent", [goal | {"pursues": ["e-nobody"]}], "Unknown"),
        ("intent", [goal | {"goal": " "}], "words"),
        ("intent", [goal | {"why": "x"}], "goal needs"),
        ("pool", {}, "one or more"),
        ("pool", {"coin": coin | {"value": 11}}, "at most its cap"),
        ("pool", {"coin": coin | {"income": -1}}, "income"),
        ("pool", {"coin": coin | {"value": 1.5}}, "value"),
        ("pool", {"coin": {"value": 3}}, "resource 'coin' needs"),
        ("capacity", 0, "at least 1"),
        ("capacity", True, "capacity"),
        ("catalogue", [], "list of 1"),
        ("catalogue", [bribe, bribe], "own id"),
        ("catalogue", [bribe | {"cost": 2}], "cost maps"),
        ("catalogue", [bribe | {"cost": {"coin": -1}}], "cost in coin"),
        ("catalogue", [bribe | {"duration": "1m"}], "uration"),
        ("catalogue", [bribe | {"effect": effect | {"class": "rule"}}], "derived, narrative"),
        ("catalogue", [bribe | {"effect": {"class": "derived"}}], "effect template needs"),
        ("catalogue", [bribe | {"prerequisites": [{"holds": "f-1", "x": 1}]}], "prerequisite is"),
        ("catalogue", [bribe | {"prerequisites": [{"front": tolls, "clock_gte": 0}]}], "clock_gte"),
        ("catalogue", [bribe | {"prerequisites": [{"front": "e-x", "clock_gte": 1}]}], "Unknown"),
        ("catalogue", [bribe | {"target": "e-nobody"}], "Unknown"),
        ("catalogue", [bribe | {"contest": {"pool": "coin"}}], "no target"),
        ("catalogue", [bribe | {"contest": {"rule": "x"}, "target": tolls}], "contest rule needs"),
        ("catalogue", [bribe | {"secret": True}], "catalogue action needs"),
        ("catalogue", [bribe | {"cost": True}], "cost maps"),
        ("pool", {"coin": 3}, "resource 'coin' needs"),
        ("catalogue", [bribe | {"duration": "0d"}], "uration"),
        ("catalogue", [bribe | {"prerequisites": {"holds": "f-1"}}], "Prerequisites is a list"),
        ("catalogue", [bribe | {"contest": {"pool": " "}, "target": tolls}], "contest's pool"),
        ("catalogue", [bribe | {"serves": "tolls"}], "serves"),
    ):
        with pytest.raises(index.CanonError, match=message):
            state_fact(ws, council, key, value)
    assert council not in world._current(ws)  # nothing was written


def test_a_faction_pool_is_read_as_of_a_date_and_never_from_a_belief(ws: Workspace) -> None:
    council, _, _ = faction(ws)
    old = world._current(ws)[council]["pool"]
    act(
        ws,
        "correct_fact",
        fact=old["id"],
        statement=old["statement"],
        entities=old["entities"],
        origin=GM,
        state=old["state"],
        valid_from=DAY0,
        valid_to="4725-01-10",
    )
    richer = {**old["state"], "value": {"coin": {"value": 7, "income": 2, "cap": 10}}}
    new = fact(ws, "The Council is richer.", state=richer, valid_from="4725-01-10")
    broke = {**old["state"], "value": {"coin": {"value": 0, "income": 0, "cap": 1}}}
    fact(ws, "The Council is broke.", never_true=True, state=broke)

    def coin(at: str) -> int:
        return world._current(ws, at=at)[council]["pool"]["state"]["value"]["coin"]["value"]

    assert (coin("4725-01-09"), coin("4725-01-10")) == (3, 7)  # end-exclusive (#170)
    on_9th = {f["id"] for f in index.search_facts(ws, at="4725-01-09")}
    assert old["id"] in on_9th and new not in on_9th


def test_undoing_a_faction_state_fact_removes_it(ws: Workspace) -> None:
    council, _, _ = faction(ws)
    entries, _ = delegation.read_log(ws)
    catalogue = world._current(ws)[council]["catalogue"]["id"]

    delegation.undo(ws, entries[-1]["id"], "other", "cli", True)

    assert "catalogue" not in world._current(ws)[council]
    assert catalogue not in {f["id"] for f in index.search_facts(ws)}
    assert {"intent", "pool", "capacity"} <= world._current(ws)[council].keys()


def test_a_faction_holds_one_fact_per_key_on_any_date(ws: Workspace) -> None:
    council, _, _ = faction(ws)
    poorer = {"of": council, "key": "pool", "value": {"coin": {"value": 1, "income": 1, "cap": 5}}}

    # A second current pool would stop every later world-turn (#251 review): refused at write.
    with pytest.raises(index.CanonError, match="already holds a pool fact"):
        fact(ws, "The Council is poorer.", state=poorer)
    with pytest.raises(index.CanonError, match="already holds a pool fact"):
        fact(ws, "The Council is poorer later.", state=poorer, valid_from="4725-03-01")
    fact(ws, "The Council fears it is poorer.", state=poorer, never_true=True)  # a belief may
    old = world._current(ws)[council]["pool"]
    act(  # correcting the one pool in place is no second pool
        ws,
        "correct_fact",
        fact=old["id"],
        statement=old["statement"],
        entities=old["entities"],
        origin=GM,
        state=old["state"],
        valid_to="4725-03-01",
    )
    fact(ws, "The Council is poorer later.", state=poorer, valid_from="4725-03-01")
    world.state(ws)  # the world still reads
    assert world._current(ws, at="4725-03-01")[council]["pool"]["state"] == poorer

    # The other documented first step: an event that closes the current one, then the new one.
    current = world._current(ws, at="4725-03-01")[council]["pool"]["id"]
    act(
        ws,
        "record_event",
        description="The Council's coffers are emptied.",
        date="4725-04-01",
        origin=GM,
        closes=[current],
    )
    broke = {**poorer, "value": {"coin": {"value": 0, "income": 1, "cap": 5}}}
    fact(ws, "The Council is broke.", state=broke, valid_from="4725-04-01")
    assert world._current(ws, at="4725-04-01")[council]["pool"]["state"] == broke


def test_a_catalogue_action_serves_the_faction_goals(ws: Workspace) -> None:
    council, _, _ = faction(ws)
    old = world._current(ws)[council]["catalogue"]
    effect = {"class": "derived", "does": "A clerk looks away."}
    bribe = {"id": "bribe", "cost": {}, "duration": "1w", "effect": effect}

    for serves, ok in ((["tolls"], True), (["crown"], False)):
        state = {**old["state"], "value": [bribe | {"serves": serves}]}
        args = {"fact": old["id"], "statement": "Bribes.", "entities": [], "origin": GM}
        if ok:
            act(ws, "correct_fact", state=state, **args)
        else:
            with pytest.raises(index.CanonError, match="unknown goals"):
                act(ws, "correct_fact", state=state, **args)
    [action] = world._current(ws)[council]["catalogue"]["state"]["value"]
    assert action["serves"] == ["tolls"]


def test_a_job_never_writes_a_faction_state_fact(ws: Workspace) -> None:
    council, _, _ = faction(ws)
    turn(ws, "4725-01-08")
    [job] = [j["id"] for j in jobs.pending(ws) if j["playbook"] == "propose-consequences"]
    jobs.start(ws, job, CONFIG, manual=True)
    state = {"of": council, "key": "capacity", "value": 2}

    # ADR 0022 (a): the GM writes the menu; a job's own work never does, whatever its cell.
    with pytest.raises(index.CanonError, match="GM's to write"):
        job_act(
            ws,
            "record_fact",
            job,
            statement="The Council acts twice.",
            entities=[council],
            origin={"kind": "job", "job": str(job)},
            state=state,
        )
    assert world._current(ws)[council]["capacity"]["state"]["value"] == 1


def test_a_hand_edited_faction_fact_is_read_as_the_tools_write_it(ws: Workspace) -> None:
    council = entity(ws, "Council")
    effect = {"class": "derived", "does": "A clerk looks away."}
    bribe = {"id": "bribe", "cost": {}, "duration": "1w", "effect": effect}

    def hand(fact_id: str, action: dict) -> None:
        front: dict[str, Any] = {"id": fact_id, "entities": [council], "relation": None}
        front |= {"valid_from": None}
        front |= {"valid_to": None, "rank": "agent_proposal", "origin": GM}
        front |= {"state": {"of": council, "key": "catalogue", "value": [action]}}
        (ws.root / index.FACTS_DIR).mkdir(exist_ok=True)
        (ws.root / index.FACTS_DIR / f"{fact_id}.md").write_text(index.join_doc(front, "Bribes."))

    hand("f-hand0001", bribe)
    [read] = index.search_facts(ws, entity=council)
    assert read["state"]["value"] == [  # the defaults filled, as record_fact fills them
        bribe | {"prerequisites": [], "target": None, "contest": None, "serves": []}
    ]

    hand("f-hand0001", bribe | {"target": "e-nobody"})
    assert "unknown entities ['e-nobody']" in " ".join(index.rebuild(ws))
    assert index.search_facts(ws, entity=council) == []  # skipped, like an invalid shape
    hand("f-hand0001", bribe | {"prerequisites": [{"front": "e-gone", "clock_gte": 1}]})
    assert "unknown entities ['e-gone']" in " ".join(index.rebuild(ws))


def test_the_faction_step_is_one_week_unless_the_campaign_sets_it(ws: Workspace) -> None:
    assert world.faction_step(ws) == 7
    config = ws.root / workspace.CONFIG_FILE
    data = yaml.safe_load(config.read_text())
    config.write_text(yaml.safe_dump(data | {"faction_step": "2w"}))
    assert world.faction_step(ws) == 14
    config.write_text(yaml.safe_dump(data | {"faction_step": "1m"}))
    with pytest.raises(workspace.WorkspaceError, match="faction_step"):
        world.faction_step(ws)


# Faction turns: the deterministic validator and contests (ADR 0022 items 4 and 5, F4)

TURN = "4725-01-05"


def decided(ws: Workspace, fact_id: str) -> str:
    """The GM confirms a fact at a terminal: a GM decision, the only faction fact read."""
    with patch.object(cli, "interactive", return_value=True):
        assert main(["confirm", fact_id, "-w", str(ws.root)]) == 0
    return fact_id


def action(name: str, cost: dict, **more: Any) -> dict:
    effect = {"class": "derived", "does": f"{name} happens."}
    return {"id": name, "cost": cost, "duration": "1w", "effect": effect, **more}


def gm_faction(
    ws: Workspace, name: str, coin: int, capacity: int, *catalogue: dict, pool: bool = True
) -> str:
    me = entity(ws, name)
    if pool:
        decided(ws, state_fact(ws, me, "pool", {"coin": {"value": coin, "income": 1, "cap": 10}}))
    decided(ws, state_fact(ws, me, "capacity", capacity))
    decided(ws, state_fact(ws, me, "catalogue", list(catalogue)))
    return me


def learn(ws: Workspace, knower: str, fact_id: str, mode: str) -> None:
    [found] = [t for t in knowledge.tools(ws) if t.name == "record_knowledge"]
    record = partial(found.fn, knower=knower, fact=fact_id, origin=GM, mode=mode, date=DAY0)
    delegation.act(ws, found, "prep-agent", record)


def chose(*actions: str) -> list[dict]:
    return [{"action": a, "cites": []} for a in actions]


def fturn(ws: Workspace, date: str, choices: Any, job: int | None = None) -> list[dict]:
    """A faction turn on `date`, the world-turn cursor first brought up to it."""
    at = world.cursor(ws)
    if at is None or index.date_key(ws.calendar, at) < index.date_key(ws.calendar, date):
        turn(ws, date)
    return world.faction_turn(ws, date, choices, job)


def failure_event(ws: Workspace, key: str) -> list[dict]:
    return [e for e in index.search_events(ws) if e["origin"].get("key") == key]


def test_a_prerequisite_is_checked_against_truth_and_a_false_belief_is_learnt_by_its_faction(
    ws: Workspace,
) -> None:
    tolls, carrier = front(ws, "Toll Squeeze")
    gate = situation(ws, "Open Gate", stage="available")
    squeeze = action("squeeze", {"coin": 1}, prerequisites=[{"front": tolls, "clock_gte": 2}])
    rumour = action("rumour", {"coin": 1}, prerequisites=[{"front": tolls, "clock_gte": 3}])
    enter = action("enter", {"coin": 1}, prerequisites=[{"situation": gate, "stage": "available"}])
    council = gm_faction(ws, "Council", 5, 3, squeeze, rumour, enter)
    spy = entity(ws, "Spy")
    member = {"type": "member_of", "subject": spy, "object": council}
    fact(ws, "The spy serves the Council.", relation=member)
    # The Council believes the clock is at 2; in truth it is at 0. It holds nothing about 3.
    belief = {"of": tolls, "key": "clock", "value": 2}
    believed = fact(ws, "The squeeze is well under way.", never_true=True, state=belief)
    learn(ws, council, believed, "believes")
    jobs_before = jobs.pending(ws)

    records = fturn(ws, TURN, {council: chose("squeeze", "rumour", "enter")})

    by = {r["action"]: r for r in records}
    ok = by["enter"]
    assert (ok["kind"], ok["status"], ok["debit"]) == ("action", "applied", {"coin": 1})
    assert (by["rumour"]["kind"], by["rumour"]["status"]) == ("failure", "failed")
    assert by["rumour"]["belief"] is None and by["rumour"]["entries"] == []
    false = by["squeeze"]
    assert (false["kind"], false["status"], false["belief"]) == ("failure", "applied", believed)
    assert "does not hold on 4725-01-05" in false["validation"]
    assert jobs.pending(ws) == jobs_before  # a faction turn queues no job

    # ADR 0022 decision (c): an offscreen event on its date that only the Council learns.
    [event] = failure_event(ws, false["key"])
    assert (event["kind"], event["date"]) == ("offscreen", TURN)
    [failed] = event["opens"]
    learnt = index.search_knowledge(ws, [council, carrier, spy, index.PARTY])
    assert [(k["knower"], k["fact"]) for k in learnt if k["fact"] == failed] == [(council, failed)]
    assert knowledge.known(ws, spy, at=TURN)[failed]["via"] == council  # CAN-14: its members
    assert failed not in knowledge.known(ws, carrier, at=TURN)
    [said] = [f for f in index.search_facts(ws, at=TURN) if f["id"] == failed]
    assert said["rank"] == "agent_proposal" and "squeeze failed" in said["statement"]
    assert said["origin"]["kind"] == "rule"
    assert world.state(ws)["fronts"][tolls]["clock"] == 0  # truth is untouched


def test_a_false_belief_on_a_fact_or_a_stage_fails_while_a_suspicion_does_not_count(
    ws: Workspace,
) -> None:
    gate = situation(ws, "Gate", stage="resolved")
    ford = fact(ws, "The ford is shallow.", valid_from=DAY0, valid_to="4725-01-03")
    rumour = fact(ws, "The ford is guarded.", never_true=True)
    cross = action("cross", {"coin": 1}, prerequisites=[{"holds": ford}])
    raid = action("raid", {"coin": 1}, prerequisites=[{"holds": rumour}])
    enter = action("enter", {"coin": 1}, prerequisites=[{"situation": gate, "stage": "available"}])
    council = gm_faction(ws, "Council", 5, 3, cross, raid, enter)
    learn(ws, council, ford, "knows")  # true once, no longer on the turn's date
    learn(ws, council, rumour, "suspects")  # a suspicion is no belief
    stage = {"of": gate, "key": "situation", "value": {"stage": "available"}}
    opened = fact(ws, "The gate stands open.", never_true=True, state=stage)
    learn(ws, council, opened, "believes")

    records = fturn(ws, TURN, {council: chose("cross", "raid", "enter")})

    assert {r["action"]: (r["status"], r["belief"]) for r in records} == {
        "cross": ("applied", ford),
        "raid": ("failed", None),
        "enter": ("applied", opened),
    }


def test_only_gm_decided_or_rule_effect_faction_facts_are_read(ws: Workspace) -> None:
    council = gm_faction(ws, "Council", 0, 2, action("bribe", {"coin": 1}), pool=False)
    guild = entity(ws, "Guild")
    state_fact(ws, guild, "catalogue", [action("bribe", {"coin": 1})])  # relayed, not decided
    turn(ws, TURN)
    before = snapshot(ws.root)

    with pytest.raises(index.CanonError, match="whole output is refused"):
        world.faction_turn(ws, TURN, {guild: chose("bribe")})
    assert snapshot(ws.root) == before
    relayed = state_fact(ws, council, "pool", {"coin": {"value": 5, "income": 1, "cap": 10}})
    assert world.validate(ws, TURN, {council: chose("bribe")})[0]["reason"] == "no pool coin"

    # A rule effect on the pool (F3's income or debit, here hand-written) is read.
    delegation.undo(ws, delegation.read_log(ws)[0][-1]["id"], "other", "cli", True)
    assert relayed not in {f["id"] for f in index.search_facts(ws)}
    [catalogue] = [
        f for f in index.search_facts(ws, entity=council) if f["state"]["key"] == "catalogue"
    ]
    pool: dict[str, Any] = {"id": "f-r0000001", "entities": [council], "relation": None}
    pool |= {"valid_from": None, "valid_to": None, "rank": "agent_proposal"}
    pool |= {"origin": {"kind": "rule", "fact": catalogue["id"], "key": f"{council}/income@{DAY0}"}}
    pool |= {
        "state": {
            "of": council,
            "key": "pool",
            "value": {"coin": {"value": 5, "income": 1, "cap": 10}},
        }
    }
    (ws.root / index.FACTS_DIR / "f-r0000001.md").write_text(index.join_doc(pool, "Income."))
    assert world.validate(ws, TURN, {council: chose("bribe")})[0]["reason"] is None


def test_a_malformed_or_off_catalogue_output_is_refused_whole(ws: Workspace) -> None:
    council = gm_faction(ws, "Council", 5, 2, action("bribe", {"coin": 1}))
    turn(ws, TURN)
    before = snapshot(ws.root)

    for choices in (
        {council: chose("bribe", "invade")},
        {council: [{"action": "bribe"}]},
        {council: ["bribe"]},
        {council: [{"action": "bribe", "cites": "f-1"}]},
        {council: "bribe"},
        [council],
    ):
        with pytest.raises(index.CanonError, match="whole output is refused"):
            world.faction_turn(ws, TURN, choices)
    with pytest.raises(index.CanonError, match="already used"):
        world.faction_turn(ws, TURN, {council: chose("bribe", "bribe")})

    assert snapshot(ws.root) == before  # nothing recorded


def test_cost_capacity_and_pool_names_are_checked_in_rank_order(ws: Workspace) -> None:
    council = gm_faction(
        ws,
        "Council",
        3,
        2,
        action("march", {"troops": 1}),
        action("hoard", {"coin": 4}),
        action("bribe", {"coin": 2}),
        action("toll", {"coin": 1}),
        action("spy", {"coin": 2}),
        action("feast", {"coin": 0}),
    )
    order = chose("march", "hoard", "bribe", "spy", "toll", "feast")

    records = fturn(ws, TURN, {council: order})

    assert {r["action"]: r["validation"] for r in records} == {
        "march": "no pool troops",  # an unknown pool is named
        "hoard": 'pools cannot cover {"coin": 4}',
        "bribe": "ok",
        "spy": 'pools cannot cover {"coin": 2}',  # 2 of its 3 coins are already committed
        "toll": "ok",
        "feast": "no capacity left this step",
    }


def test_one_faction_turn_per_step_never_after_the_cursor(ws: Workspace) -> None:
    council = gm_faction(ws, "Council", 5, 1, action("bribe", {"coin": 1}))
    fturn(ws, TURN, {council: chose("bribe")})

    with pytest.raises(DelegationError, match="on or before the cursor"):
        world.faction_turn(ws, "4725-01-06", {council: chose("bribe")})
    turn(ws, "4725-01-12")
    for inside in ("4725-01-11", "4725-01-05", "4725-01-01"):
        with pytest.raises(DelegationError, match="One faction turn per step"):
            world.faction_turn(ws, inside, {council: chose("bribe")})
    [next_week] = world.faction_turn(ws, "4725-01-12", {council: chose("bribe")})
    assert next_week["status"] == "applied"


def test_a_faction_turn_is_refused_up_front_at_manual_for_an_unstarted_job_or_live(
    ws: Workspace,
) -> None:
    council = gm_faction(ws, "Council", 5, 1, action("bribe", {"coin": 1}))
    turn(ws, TURN)
    queued_job = jobs.queue(
        ws,
        playbook="settle-an-unless",
        inputs={"occurrence": "x"},
        expected_output="x",
        responsibility="living_world",
    )["id"]
    before = snapshot(ws.root)

    with pytest.raises(DelegationError, match="not started"):
        world.faction_turn(ws, TURN, {council: chose("bribe")}, job=queued_job)
    set_level(ws, "prep", "living_world", "manual")
    with pytest.raises(DelegationError, match="living_world is at manual"):
        world.faction_turn(ws, TURN, {council: chose("bribe")})
    set_level(ws, "prep", "living_world", "act-then-review")
    delegation.change_moment(ws, "live-session")
    with pytest.raises(DelegationError, match="never act during a live session"):
        world.faction_turn(ws, TURN, {council: chose("bribe")})

    after = snapshot(ws.root)
    assert {p for p in after if p.startswith(("occurrences/", "canon/", "action-log/"))} == {
        p for p in before if p.startswith(("occurrences/", "canon/", "action-log/"))
    }


def test_an_interrupted_faction_turn_is_finished_by_recovery(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    squeeze = action("squeeze", {"coin": 1}, prerequisites=[{"front": tolls, "clock_gte": 1}])
    council = gm_faction(ws, "Council", 5, 3, squeeze, action("toll", {"coin": 1}))
    learn(
        ws,
        council,
        fact(ws, "It began.", never_true=True, state={"of": tolls, "key": "clock", "value": 1}),
        "believes",
    )
    turn(ws, TURN)

    def crash(step: str) -> None:
        if step.startswith("occurrences/"):
            raise RuntimeError(step)

    monkeypatch.setattr(journal, "_fault", crash)
    with pytest.raises(RuntimeError):
        world.faction_turn(ws, TURN, {council: chose("squeeze", "toll")})
    monkeypatch.setattr(journal, "_fault", lambda step: None)
    with delegation.locked(ws):  # the first acquisition recovers
        pass

    found = {r["key"]: r["status"] for r in world.occurrences(ws) if r["kind"] != "tick"}
    assert found == {
        f"{council}/squeeze@{TURN}": "applied",
        f"{council}/toll@{TURN}": "applied",
        f"{council}/income@{TURN}": "applied",
    }
    assert not list((ws.root / delegation.JOURNAL_DIR).glob("*.yaml"))


def contest(ws: Workspace, council_cost: int = 2, guild_cost: int = 2) -> tuple[str, str, str]:
    bridge = entity(ws, "Bridge")
    seize = {"target": bridge, "contest": {"pool": "coin"}}
    council = gm_faction(ws, "Council", 5, 1, action("seize", {"coin": council_cost}, **seize))
    guild = gm_faction(ws, "Guild", 5, 1, action("seize", {"coin": guild_cost}, **seize))
    return council, guild, bridge


def test_a_contest_is_seeded_from_its_keys_and_replays_to_the_same_records(
    ws: Workspace, tmp_path: Path
) -> None:
    council, guild, bridge = contest(ws)
    turn(ws, TURN)
    copy = tmp_path / "replay"
    shutil.copytree(ws.root, copy)
    choices = {council: chose("seize"), guild: chose("seize")}

    def outcome(w: Workspace) -> list[dict]:
        records = world.faction_turn(w, TURN, choices)
        return [{k: v for k, v in r.items() if k != "at"} for r in records]

    first, replay = outcome(ws), outcome(workspace.load(copy))

    assert first == replay  # every field but the wall-clock `at`
    rolls = {r["entity"]: r["contest"]["roll"] for r in first}
    assert rolls == {f: world.roll(f"{f}/seize@{TURN}") for f in (council, guild)}
    [won] = [r for r in first if r["status"] == "applied"]
    [lost] = [r for r in first if r["status"] == "failed"]
    assert won["contest"]["won"] and not lost["contest"]["won"]
    assert lost["validation"] == f"lost the contest for {bridge} to {won['key']}"
    assert won["contest"]["roll"] >= lost["contest"]["roll"]  # equal commitments: the roll


def test_a_larger_commitment_wins_a_contest_whatever_the_roll(ws: Workspace) -> None:
    council, guild, _ = contest(ws, council_cost=3, guild_cost=1)

    records = fturn(ws, TURN, {council: chose("seize"), guild: chose("seize")})

    assert {r["entity"]: r["status"] for r in records} == {council: "applied", guild: "failed"}


def test_a_contest_loser_commits_nothing_so_its_faction_can_afford_its_next_choice(
    ws: Workspace,
) -> None:
    bridge = entity(ws, "Bridge")
    seize = {"target": bridge, "contest": {"pool": "coin"}}
    council = gm_faction(
        ws, "Council", 3, 2, action("seize", {"coin": 2}, **seize), action("toll", {"coin": 2})
    )
    guild = gm_faction(ws, "Guild", 5, 1, action("seize", {"coin": 3}, **seize))

    records = fturn(ws, TURN, {council: chose("seize", "toll"), guild: chose("seize")})

    assert {r["key"]: r["validation"] for r in records} == {
        f"{council}/seize@{TURN}": f"lost the contest for {bridge} to {guild}/seize@{TURN}",
        f"{council}/toll@{TURN}": "ok",  # its 3 coins cover it once the lost seize is dropped
        f"{guild}/seize@{TURN}": "ok",
    }


def dissolving(ws: Workspace, c_coin: int, c_capacity: int, *c_more: dict) -> tuple[str, ...]:
    """A loses X to B, which frees coin for `ay`, which then starves `a1`, which had beaten C's
    `c1` on T: the contest on T dissolves after `c1` lost it."""
    x, t = entity(ws, "X"), entity(ws, "T")
    cx = {"target": x, "contest": {"pool": "coin"}}
    ct = {"target": t, "contest": {"pool": "coin"}}
    a = gm_faction(
        ws,
        "A",
        3,
        3,
        action("ax", {"coin": 2}, **cx),
        action("ay", {"coin": 3}),
        action("a1", {"coin": 1}, **ct),
    )
    b = gm_faction(ws, "B", 5, 1, action("bx", {"coin": 3}, **cx))
    c = gm_faction(ws, "C", c_coin, c_capacity, action("c1", {"coin": 0}, **ct), *c_more)
    return a, b, c


def test_a_contest_loser_stays_lost_when_its_winner_fails_later(ws: Workspace) -> None:
    a, b, c = dissolving(ws, 0, 1, action("c2", {"coin": 0}))

    records = fturn(ws, TURN, {a: chose("ax", "ay", "a1"), b: chose("bx"), c: chose("c1", "c2")})

    by = {r["key"].split("/")[1].split("@")[0]: r for r in records}
    assert by["a1"]["validation"] == 'pools cannot cover {"coin": 1}'
    assert (by["c1"]["status"], by["c1"]["contest"]["won"]) == ("failed", False)
    assert by["c1"]["validation"].startswith("lost the contest")
    assert by["c2"]["status"] == "applied"  # the lost c1 used no capacity
    assert by["bx"]["contest"]["won"] and by["ay"]["status"] == "applied"


def test_validated_choices_never_overdraw_a_pool(ws: Workspace) -> None:
    a, b, c = dissolving(ws, 2, 2, action("c2", {"coin": 2}), action("c3", {"coin": 2}))

    records = fturn(
        ws, TURN, {a: chose("ax", "ay", "a1"), b: chose("bx"), c: chose("c1", "c2", "c3")}
    )

    spent: Counter[str] = Counter()
    for r in records:
        if r["status"] == "applied":
            spent[r["entity"]] += r["debit"].get("coin", 0)
    assert spent == {a: 3, b: 3, c: 2}
    assert [r["action"] for r in records if r["entity"] == c and r["status"] == "applied"] == ["c2"]


def test_a_cite_that_is_no_canon_fact_refuses_the_whole_output(ws: Workspace) -> None:
    council = gm_faction(ws, "Council", 5, 2, action("bribe", {"coin": 1}))
    belief = fact(ws, "The Guild is broke.", never_true=True)
    turn(ws, TURN)
    before = snapshot(ws.root)

    for cites in (["../../../nope"], ["f-00000000"]):
        with pytest.raises(index.CanonError, match="not canon fact ids"):
            world.faction_turn(ws, TURN, {council: [{"action": "bribe", "cites": cites}]})
    assert snapshot(ws.root) == before
    # A belief may be cited, held by the faction or not (D25).
    [record] = world.faction_turn(ws, TURN, {council: [{"action": "bribe", "cites": [belief]}]})
    assert record["cites"] == [belief]


def test_an_empty_faction_turn_records_nothing_and_leaves_its_step_free(ws: Workspace) -> None:
    council = gm_faction(ws, "Council", 5, 1, action("bribe", {"coin": 1}))

    assert fturn(ws, TURN, {}) == [] and fturn(ws, TURN, {council: []}) == []
    assert world.faction_turn(ws, TURN, {council: chose("bribe")})[0]["status"] == "applied"


def test_a_hand_edit_to_any_faction_it_read_rolls_an_interrupted_turn_back(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    tolls, _ = front(ws, "Toll Squeeze")
    squeeze = action("squeeze", {"coin": 1}, prerequisites=[{"front": tolls, "clock_gte": 1}])
    council = gm_faction(ws, "Council", 5, 3, squeeze, action("toll", {"coin": 1}))
    guild = gm_faction(ws, "Guild", 5, 3, squeeze, action("toll", {"coin": 1}))
    for who in (council, guild):
        began = {"of": tolls, "key": "clock", "value": 1}
        learn(ws, who, fact(ws, f"It began for {who}.", never_true=True, state=began), "believes")
    turn(ws, TURN)
    choices = {council: chose("squeeze", "toll"), guild: chose("squeeze", "toll")}
    second = sorted(choices)[1]  # not the faction whose record commits the journal
    [pool] = [f for f in index.search_facts(ws, entity=second) if f["state"]["key"] == "pool"]

    def crash(step: str) -> None:
        if step.startswith("occurrences/"):
            raise RuntimeError(step)

    monkeypatch.setattr(journal, "_fault", crash)
    with pytest.raises(RuntimeError):
        world.faction_turn(ws, TURN, choices)
    monkeypatch.setattr(journal, "_fault", lambda step: None)
    path = ws.root / index.FACTS_DIR / f"{pool['id']}.md"
    path.write_text(path.read_text().replace("value: 5", "value: 0"))
    with delegation.locked(ws):  # the first acquisition recovers
        pass

    assert [r for r in world.occurrences(ws) if r["kind"] != "tick"] == []
    assert "faction turn must run again" in calls.read_calls(ws)[-1]["message"]
    assert len(world.faction_turn(ws, TURN, choices)) == 4  # run again, it plans afresh


def test_failed_choices_are_listed_collapsed_with_their_reason_in_the_report(
    ws: Workspace,
) -> None:
    council, guild, _ = contest(ws)
    records = fturn(ws, TURN, {council: chose("seize"), guild: chose("seize")})

    shown = world.present(records)

    [lost] = [r for r in records if r["kind"] == "failure"]
    failures = {"kind": "failures", "entity": lost["entity"]}
    assert failures | {"failed": {lost["key"]: lost["validation"]}} in shown
    assert sorted(s["kind"] for s in shown) == ["action", "failures"]


def false_belief(ws: Workspace) -> str:
    tolls, _ = front(ws, "Toll Squeeze")
    squeeze = action("squeeze", {"coin": 1}, prerequisites=[{"front": tolls, "clock_gte": 1}])
    council = gm_faction(ws, "Council", 5, 1, squeeze)
    belief = {"of": tolls, "key": "clock", "value": 1}
    learn(ws, council, fact(ws, "The squeeze began.", never_true=True, state=belief), "believes")
    return council


def test_a_failure_on_a_false_belief_waits_for_the_gm_at_propose(ws: Workspace) -> None:
    council = false_belief(ws)
    set_level(ws, "prep", "living_world", "propose")

    [record] = fturn(ws, TURN, {council: chose("squeeze")})

    assert (record["status"], record["entries"]) == ("queued", [])
    assert record["call"] is not None and failure_event(ws, record["key"]) == []
    with pytest.raises(DelegationError, match="accept or reject"):
        world.decide(ws, record["key"], "reschedule", True, date="4725-01-12")
    assert world.decide(ws, record["key"], "reject", authenticated=True)["status"] == "rejected"
    assert failure_event(ws, record["key"]) == []


def test_an_applied_failure_is_accepted_late_or_undone_back_to_the_queue(ws: Workspace) -> None:
    council = false_belief(ws)

    [record] = fturn(ws, TURN, {council: chose("squeeze")})
    assert record["status"] == "applied" and failure_event(ws, record["key"])

    income = f"{council}/income@{TURN}"  # later on the same faction: undone with it (LW-12)
    undone = world.undo(ws, record["key"], "other", "cli", authenticated=True)
    assert undone == sorted([record["key"], income])
    assert occ(ws, record["key"])["status"] == "queued"
    assert failure_event(ws, record["key"]) == []
    assert world.decide(ws, record["key"], "accept", authenticated=True)["status"] == "applied"
    [event] = failure_event(ws, record["key"])
    assert event["date"] == TURN  # LW-17: it keeps its date


def test_a_catalogue_action_id_never_breaks_its_occurrence_key(ws: Workspace) -> None:
    council, gate = entity(ws, "Council"), situation(ws, "Gate", stage="available")
    for bad, message in (
        (action("a/b", {}), "no '/' or '@'"),
        (action("a@b", {}), "no '/' or '@'"),
        (action("x", {}, prerequisites=[{"situation": gate, "stage": "open"}]), "stage is one"),
        (action("x", {}, prerequisites=[{"situation": "e-x", "stage": "active"}]), "Unknown"),
    ):
        with pytest.raises(index.CanonError, match=message):
            state_fact(ws, council, "catalogue", [bad])


# Income, debit and effect (ADR 0022 items 2, 4 and 6, F3)

NEXT = "4725-01-12"  # one faction step after TURN


def coin(ws: Workspace, faction: str, at: str) -> int:
    [pool] = [
        f
        for f in index.search_facts(ws, at=at, entity=faction)
        if (f.get("state") or {}).get("key") == "pool"
    ]
    return pool["state"]["value"]["coin"]["value"]


def effect_facts(ws: Workspace, key: str) -> list[dict]:
    """The facts saying what a faction's action did: its effect, never its debited pool."""
    return [
        f
        for f in index.search_facts(ws)
        if f["origin"].get("key") == key and f.get("state") is None
    ]


def test_income_is_credited_once_per_step_up_to_the_cap(ws: Workspace) -> None:
    council = entity(ws, "Council")
    decided(ws, state_fact(ws, council, "pool", {"coin": {"value": 8, "income": 3, "cap": 10}}))

    assert fturn(ws, TURN, {}) == []  # no choice, still its income
    income = occ(ws, f"{council}/income@{TURN}")
    assert (income["kind"], income["class"], income["status"]) == ("income", "rule", "applied")
    assert coin(ws, council, TURN) == 10  # 8 + 3, stopped at the cap
    [credited] = index.search_facts(ws, at=TURN, entity=council)
    assert credited["rank"] == "gm_decision"  # a rule effect keeps its rule's rank (ADR 0009)
    assert credited["origin"]["key"] == income["key"]
    assert world.faction_turn(ws, TURN, {}) == []  # its key is used once (LW-13)
    assert [r["key"] for r in world.occurrences(ws) if r["kind"] == "income"] == [income["key"]]

    turn(ws, NEXT)
    world.faction_turn(ws, NEXT, {})
    assert f"{council}/income@{NEXT}" not in {r["key"] for r in world.occurrences(ws)}  # at cap


def test_an_accepted_choice_debits_its_pool_and_applies_its_effect_in_one_plan(
    ws: Workspace,
) -> None:
    council = gm_faction(ws, "Council", 5, 2, action("bribe", {"coin": 2}), action("feast", {}))
    spy = entity(ws, "Spy")

    bribe, feast = fturn(ws, TURN, {council: chose("bribe", "feast")})

    assert (bribe["kind"], bribe["status"], bribe["debit"]) == ("action", "applied", {"coin": 2})
    assert coin(ws, council, TURN) == 4  # 5 - 2, then the step's income of 1
    [effect] = effect_facts(ws, bribe["key"])
    assert effect["statement"] == "Council: bribe: bribe happens."
    assert effect["rank"] == "agent_proposal" and effect["origin"]["kind"] == "rule"
    assert effect["id"] in knowledge.known(ws, council, at=TURN)
    assert effect["id"] not in knowledge.known(ws, spy, at=TURN)
    # One plan: the pool's fact, event and knowledge, then the effect's.
    logged = [e for e in delegation.read_log(ws)[0] if e.get("occurrence") == bribe["key"]]
    assert sorted(bribe["entries"]) == [e["id"] for e in logged] and len(logged) == 6
    [debited] = [
        f for f in index.search_facts(ws) if f["origin"].get("key") == bribe["key"] and f["state"]
    ]
    assert debited["state"]["value"]["coin"]["value"] == 3
    assert feast["debit"] == {} and len(feast["entries"]) == 3  # a free action: its effect only
    # The debited pool is a rule effect the next validation reads (D12).
    turn(ws, NEXT)
    assert world.validate(ws, NEXT, {council: chose("bribe")})[0]["reason"] is None


def test_new_narrative_from_the_catalogue_waits_for_the_gm_and_debits_only_once_accepted(
    ws: Workspace,
) -> None:
    seize = action("seize", {"coin": 4})
    seize["effect"]["class"] = "narrative"
    council = gm_faction(ws, "Council", 5, 1, seize)

    [record] = fturn(ws, TURN, {council: chose("seize")})

    assert (record["class"], record["status"], record["entries"]) == ("narrative", "queued", [])
    assert record["call"] is not None and effect_facts(ws, record["key"]) == []
    assert coin(ws, council, TURN) == 6  # its income only
    with pytest.raises(DelegationError, match="accept or reject"):
        world.decide(ws, record["key"], "reschedule", True, date=NEXT)
    assert world.decide(ws, record["key"], "accept", authenticated=True)["status"] == "applied"
    assert coin(ws, council, TURN) == 2 and len(effect_facts(ws, record["key"])) == 1
    dates = {e["date"] for e in index.search_events(ws) if e["origin"].get("key") == record["key"]}
    assert dates == {TURN}  # LW-17: it keeps its date


def test_a_pool_never_goes_below_zero_when_an_accept_comes_after_spending(ws: Workspace) -> None:
    seize = action("seize", {"coin": 4})
    seize["effect"]["class"] = "narrative"
    council = gm_faction(ws, "Council", 5, 1, seize, action("bribe", {"coin": 5}))
    [held] = fturn(ws, TURN, {council: chose("seize")})  # 5 + 1 income = 6
    turn(ws, NEXT)
    world.faction_turn(ws, NEXT, {council: chose("bribe")})  # 6 - 5 + 1 = 2
    before = snapshot(ws.root)

    record = world.decide(ws, held["key"], "accept", authenticated=True)

    assert record["status"] == "queued" and record["call"] is not None
    assert coin(ws, council, NEXT) == 2 and effect_facts(ws, held["key"]) == []
    changed = {p for p, b in snapshot(ws.root).items() if before.get(p) != b}
    assert not {p for p in changed if p.startswith(("canon/", "action-log/"))}


def test_at_propose_the_debit_its_effect_and_the_income_wait_whole(ws: Workspace) -> None:
    council = gm_faction(ws, "Council", 5, 1, action("bribe", {"coin": 2}))
    set_level(ws, "prep", "living_world", "propose")

    [record] = fturn(ws, TURN, {council: chose("bribe")})

    income = occ(ws, f"{council}/income@{TURN}")
    assert record["status"] == income["status"] == "queued"
    assert record["call"] is not None and income["call"] is not None
    assert coin(ws, council, TURN) == 5 and effect_facts(ws, record["key"]) == []
    world.decide(ws, record["key"], "accept", authenticated=True)
    assert coin(ws, council, TURN) == 3 and len(effect_facts(ws, record["key"])) == 1
    world.decide(ws, income["key"], "accept", authenticated=True)
    assert coin(ws, council, TURN) == 4


def test_undoing_an_action_returns_its_debit_and_effect_together(ws: Workspace) -> None:
    council = gm_faction(ws, "Council", 5, 1, action("bribe", {"coin": 2}))
    [record] = fturn(ws, TURN, {council: chose("bribe")})

    undone = world.undo(ws, record["key"], "other", "cli", authenticated=True)

    assert undone == sorted([record["key"], f"{council}/income@{TURN}"])
    assert coin(ws, council, TURN) == 5 and effect_facts(ws, record["key"]) == []
    world.decide(ws, record["key"], "accept", authenticated=True)
    assert coin(ws, council, TURN) == 3 and len(effect_facts(ws, record["key"])) == 1


def test_a_contest_loser_never_debits_and_learns_no_effect(ws: Workspace) -> None:
    council, guild, _ = contest(ws, council_cost=3, guild_cost=1)

    records = fturn(ws, TURN, {council: chose("seize"), guild: chose("seize")})

    by = {r["entity"]: r for r in records}
    won, lost = by[council], by[guild]
    assert (won["status"], lost["status"], lost["entries"]) == ("applied", "failed", [])
    assert coin(ws, council, TURN) == 3  # 5 - 3 + 1
    assert coin(ws, guild, TURN) == 6  # its income only
    assert effect_facts(ws, lost["key"]) == [] and len(effect_facts(ws, won["key"])) == 1
