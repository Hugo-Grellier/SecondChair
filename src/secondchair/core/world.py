"""The living world (05-living-world-calendar.md, ADR 0009): fronts and situations whose state is
facts, the world-turn that advances them and the forecast that looks ahead.

A front or a situation is an entity; all its state is **state facts**, facts carrying
`state: {of, key, value}` (LW-03): on a front, `front` (its rule: carrier, participants,
capacity, rate, `unless`, active), `clock` and one `agenda` fact per step; on a situation,
`situation` (stage, deadline, participants). Every effect is an offscreen event closing the old
state fact and opening the new one, known only to the carrier and the named participants
(LW-11).

The world-turn is deterministic over `]cursor, now]` (LW-04): the v3 occurrence keys
(`<front>/tick@<date>`, `<front>/<step>`, `<situation>/deadline@<date>`, a rescheduled key
`<key>~<date>`) are each used once, whatever happens to them (LW-13). Rule effects apply at the
living world's level with the rule's rank; an `unless` and a narrative deadline become jobs
(LW-06); an occurrence contradicting played canon becomes a call and stays queued (LW-09).

Workspace files (docs/contracts/workspace-layout.md): `living-world.yaml` (the cursor) and one
YAML file per occurrence in `occurrences/`; every effect's files are action log entries carrying
the occurrence key, which is what undo walks (LW-12).
"""

import hashlib
from collections import Counter
from typing import Any

from secondchair.core import calls, delegation, index
from secondchair.core.calendar import CalendarError
from secondchair.core.delegation import (
    OCCURRENCES_DIR,
    WORLD_FILE,
    DelegationError,
    _append,
    _read_yaml,
    _save,
    _write,
    locked,
)
from secondchair.core.index import CanonError
from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import Workspace

FRONT, CLOCK, AGENDA, SITUATION = "front", "clock", "agenda", "situation"
STAGES = ("available", "active", "resolved", "expired")  # `active`: the party engaged it
STEP_STATUSES = ("pending", "done", "averted")
GROUP_ABOVE = 6  # LW-15
AGENT = "world-turn"


def _effect_tool() -> Tool:
    return Tool(
        fn=world_turn, responsibility="living_world", delegated_action=True, reversible=True
    )


# State facts


def check_state(ws: Workspace, state: Any) -> tuple[dict, list[str]]:
    """A state fact's `state`, normalised, and the entity ids its value names; `CanonError` when
    its shape is not one the world-turn reads."""
    if not isinstance(state, dict) or set(state) != {"of", "key", "value"}:
        raise CanonError("state needs exactly of (an entity id), key and value.")
    key, value, cal = state["key"], state["value"], ws.calendar

    def fields(required: set[str], optional: dict[str, Any]) -> dict:
        if not isinstance(value, dict) or not required <= set(value) <= required | set(optional):
            raise CanonError(
                f"A {key} state needs {sorted(required)}, optionally {sorted(optional)}."
            )
        return {**optional, **value}

    def ids(v: Any) -> list[str]:
        if not isinstance(v, list) or not all(isinstance(i, str) and i for i in v):
            raise CanonError("participants must be a list of entity ids.")
        return v

    refs: list[str] = []
    if key == CLOCK:
        if type(value) is not int or value < 0:
            raise CanonError("A clock state is a non-negative integer.")
    elif key == FRONT:
        value = fields(
            {"carrier", "capacity", "every", "anchor"},
            {"participants": [], "ticks": 1, "unless": None, "active": True},
        )
        try:
            every = cal.days(value["every"])
            value["anchor"] = cal.canonical(value["anchor"])
        except CalendarError as e:
            raise CanonError(str(e)) from e
        if every < 1:
            raise CanonError("A front's every is a positive duration.")
        for name in ("capacity", "ticks"):
            if type(value[name]) is not int or value[name] < 1:
                raise CanonError(f"A front's {name} is a positive integer.")
        if value["unless"] is not None and not str(value["unless"]).strip():
            raise CanonError("A front's unless is a condition in words, or null.")
        if type(value["active"]) is not bool:
            raise CanonError("A front's active is true or false.")
        refs = [value["carrier"], *ids(value["participants"])]
    elif key == AGENDA:
        value = fields({"id", "when"}, {"status": "pending"})
        when = value["when"]
        if not isinstance(when, dict) or len(when) != 1 or set(when) - {"date", "clock_gte"}:
            raise CanonError("An agenda step's when is {date: …} or {clock_gte: …}.")
        if "date" in when:
            value["when"] = {"date": cal.canonical(when["date"])}
        elif type(when["clock_gte"]) is not int or when["clock_gte"] < 1:
            raise CanonError("An agenda step's clock_gte is a positive integer.")
        if value["status"] not in STEP_STATUSES:
            raise CanonError(f"An agenda step's status is one of {', '.join(STEP_STATUSES)}.")
    elif key == SITUATION:
        value = fields({"stage"}, {"deadline": None, "participants": []})
        if value["stage"] not in STAGES:
            raise CanonError(f"A situation's stage is one of {', '.join(STAGES)}.")
        if value["deadline"] is not None:
            value["deadline"] = cal.canonical(value["deadline"])
        refs = ids(value["participants"])
    else:
        raise CanonError(f"Unknown state key {key!r}; expected front, clock, agenda or situation.")
    return {**state, "value": value}, refs


def _current(ws: Workspace) -> dict[str, dict[str, Any]]:
    """Entity id -> its current state facts: one per key, a list of agenda steps."""
    found: dict[str, dict[str, Any]] = {}
    for f in index.search_facts(ws):
        if f.get("state") is None or f["valid_to"] is not None:
            continue
        mine = found.setdefault(f["state"]["of"], {AGENDA: []})
        key = f["state"]["key"]
        if key == AGENDA:
            mine[AGENDA].append(f)
        elif key in mine:
            raise CanonError(
                f"{f['state']['of']} holds two {key} facts: {mine[key]['id']}, {f['id']}."
            )
        else:
            mine[key] = f
    return found


def state(ws: Workspace) -> dict[str, dict]:
    """The living world now: every front (clock, capacity, active, agenda step statuses) and
    every situation (stage, deadline), by entity id."""
    fronts, situations = {}, {}
    for entity, s in _current(ws).items():
        if FRONT in s:
            rule = s[FRONT]["state"]["value"]
            fronts[entity] = {
                "clock": s[CLOCK]["state"]["value"] if CLOCK in s else 0,
                "capacity": rule["capacity"],
                "active": rule["active"],
                "agenda": {
                    a["state"]["value"]["id"]: a["state"]["value"]["status"] for a in s[AGENDA]
                },
            }
        if SITUATION in s:
            v = s[SITUATION]["state"]["value"]
            situations[entity] = {"stage": v["stage"], "deadline": v["deadline"]}
    return {"fronts": fronts, "situations": situations}


# Occurrences and the cursor


def occurrences(ws: Workspace) -> list[dict]:
    return [_read_yaml(p) for p in sorted((ws.root / OCCURRENCES_DIR).glob("*.yaml"))]


def _find(ws: Workspace, key: str) -> dict:
    for record in occurrences(ws):
        if record["key"] == key:
            return record
    raise DelegationError(f"No occurrence {key!r}.")


def cursor(ws: Workspace) -> str | None:
    """The date up to which every occurrence is recorded (applied or queued), None before the
    first world-turn."""
    path = ws.root / WORLD_FILE
    return _read_yaml(path)["cursor"] if path.is_file() else None


def _start(ws: Workspace, since: str | None) -> str:
    current = cursor(ws)
    if current is None:
        if since is None:
            raise DelegationError("No world-turn yet: give the date the world starts from.")
        return ws.calendar.canonical(since)
    if since is not None and ws.calendar.canonical(since) != current:
        raise DelegationError(f"The world-turn cursor is {current}; it only moves forward.")
    return current


# Planning (pure: forecast and world-turn share it)


def plan(ws: Workspace, since: str, until: str, known: list[dict] | None = None) -> list[dict]:
    """The occurrences due over `]since, until]` whose key is not yet used, in date order: ticks
    at the anchored rate up to the clock's capacity, the agenda steps they cascade into (dated
    at the crossing tick), dated steps, deadlines, and rescheduled successors. Writes nothing."""
    cal = ws.calendar
    records = occurrences(ws) if known is None else known
    used = {r["key"] for r in records}
    waiting: Counter[str] = Counter()  # ticks queued or rescheduled, still to count
    for r in records:
        late = r["status"] == "rescheduled" and r["rescheduled_to"] not in used
        if r["kind"] == "tick" and (r["status"] == "queued" or late):
            waiting[r["entity"]] += r["ticks"]

    def at(d: str) -> int:
        return index.date_key(cal, d)

    out: list[dict] = []

    def due(key: str, kind: str, cls: str, entity: str, date: str, rule: str, **more: Any) -> dict:
        used.add(key)
        occ = {"key": key, "kind": kind, "class": cls, "entity": entity, "date": date}
        out.append({**occ, "rule": rule, **more})
        return out[-1]

    for entity, s in sorted(_current(ws).items()):
        if FRONT in s and s[FRONT]["state"]["value"]["active"]:  # a pause suspends it (LW-14)
            rule = s[FRONT]["state"]["value"]
            clock = s[CLOCK]["state"]["value"] if CLOCK in s else 0
            room = rule["capacity"] - clock - waiting[entity]
            steps = [a for a in s[AGENDA] if a["state"]["value"]["status"] == "pending"]
            every = cal.days(rule["every"])
            # ponytail: walks every tick from the anchor; jump to `since` if fronts get old.
            day = cal.add(rule["anchor"], f"{every}d")
            while room > 0 and at(day) <= at(until):
                key = f"{entity}/tick@{day}"
                if at(day) > at(since) and key not in used:
                    n = min(rule["ticks"], room)
                    room -= n
                    cls = "rule" if rule["unless"] is None else "derived"
                    due(key, "tick", cls, entity, day, s[FRONT]["id"], ticks=n)
                    if cls == "rule":  # an unless tick counts once settled (T5)
                        clock += n
                        for a in steps:
                            step = a["state"]["value"]
                            step_key = f"{entity}/{step['id']}"
                            if (
                                step["when"].get("clock_gte", clock + 1) <= clock
                                and step_key not in used
                            ):
                                due(step_key, "step", "rule", entity, day, a["id"], cause=key)
                day = cal.add(day, f"{every}d")
            for a in steps:
                step = a["state"]["value"]
                step_key = f"{entity}/{step['id']}"
                if (
                    "date" in step["when"]
                    and at(step["when"]["date"]) <= at(until)
                    and step_key not in used  # a dated step never scheduled is, late
                ):
                    due(step_key, "step", "rule", entity, step["when"]["date"], a["id"])
        if SITUATION in s:
            v = s[SITUATION]["state"]["value"]
            key = f"{entity}/deadline@{v['deadline']}"
            if (
                v["deadline"] is not None
                and v["stage"] in ("available", "active")
                and at(v["deadline"]) <= at(until)
                and key not in used
            ):
                # An engaged situation's deadline is new narrative (ADR 0009).
                cls = "rule" if v["stage"] == "available" else "narrative"
                due(key, "deadline", cls, entity, v["deadline"], s[SITUATION]["id"])
    for r in records:
        if (
            r["status"] == "rescheduled"
            and r["rescheduled_to"] not in used
            and at(r["rescheduled_date"]) <= at(until)
        ):
            more = {k: r[k] for k in ("ticks", "cause") if r.get(k) is not None}
            due(
                r["rescheduled_to"],
                r["kind"],
                r["class"],
                r["entity"],
                r["rescheduled_date"],
                r["rule"],
                rescheduled_from=r["key"],
                **more,
            )
    return sorted(out, key=lambda o: (at(o["date"]), o["key"]))


def present(planned: list[dict]) -> list[dict]:
    """Occurrences as shown to the GM: more than six ticks of one front are one group, each tick
    keeping its key (LW-15)."""
    ticks = Counter(o["entity"] for o in planned if o["kind"] == "tick")
    shown: list[dict] = []
    groups: dict[str, dict] = {}
    for o in planned:
        if o["kind"] == "tick" and ticks[o["entity"]] > GROUP_ABOVE:
            if o["entity"] not in groups:
                groups[o["entity"]] = {
                    "kind": "ticks",
                    "entity": o["entity"],
                    "keys": [],
                    "dates": [],
                }
                shown.append(groups[o["entity"]])
            groups[o["entity"]]["keys"].append(o["key"])
            groups[o["entity"]]["dates"].append(o["date"])
        else:
            shown.append(o)
    return shown


def forecast(ws: Workspace, until: str, since: str | None = None) -> list[dict]:
    """What coming world-turns would do up to `until` (LW-18): no fact, event or occurrence is
    written and the cursor does not move."""
    return present(plan(ws, _start(ws, since), ws.calendar.canonical(until)))


# The world-turn


def world_turn(ws: Workspace, now: str, since: str | None = None) -> list[dict]:
    """Advance the world over `]cursor, now]` (LW-04): record each due occurrence once, apply
    the rule effects at the living world's level, queue a job for each `unless` and each
    narrative deadline, then move the cursor to `now`. Never during a live session (LW-05);
    idempotent. `since` is the world's starting date, needed on the first run only. Returns
    the occurrences recorded."""
    from secondchair.core import jobs  # it builds on canon, which builds on this module

    with locked(ws):
        moment, _ = delegation.current_moment(ws)
        if moment == "live-session":
            raise DelegationError("The world-turn never runs during a live session; end it first.")
        start, now = _start(ws, since), ws.calendar.canonical(now)
        if index.date_key(ws.calendar, now) < index.date_key(ws.calendar, start):
            raise DelegationError(f"The world-turn cursor is {start}; it never moves back.")
        level = delegation.effective_level(ws, "living_world", moment, reversible=True)
        if level == "manual":
            raise DelegationError(f"living_world is at manual in {moment}: no world-turn.")
        before = {r["id"] for r in occurrences(ws)}
        for occ in plan(ws, start, now):
            if occ.get("cause"):  # a threshold step: the tick it crosses at applies it
                continue
            record = _register(ws, occ)
            if record["class"] == "rule":
                if level == "propose":
                    _ask(ws, record, "proposal", "accept, reject or reschedule it")
                else:
                    _apply(ws, record)
            else:
                narrative = record["class"] == "narrative"
                record["job"] = jobs.queue(
                    ws,
                    playbook="propose-narrative-direction" if narrative else "settle-an-unless",
                    inputs={"occurrence": record["key"]},
                    expected_output="A narrative-direction proposal for the deadline."
                    if narrative
                    else "The unless settled with settle_unless, citing fact ids.",
                    responsibility="narrative_direction" if narrative else "living_world",
                    tier="standard",
                )["id"]
                _save(ws, record, OCCURRENCES_DIR)
        _write(ws.root / WORLD_FILE, f"cursor: '{now}'\n")
        recorded = [r for r in occurrences(ws) if r["id"] not in before]
        if any(r["status"] == "applied" for r in recorded):
            jobs.queue(
                ws,
                playbook="propose-consequences",
                inputs={"occurrences": " ".join(r["key"] for r in recorded)},
                expected_output="Derived consequences proposed, each citing the facts it uses.",
                responsibility="living_world",
                tier="standard",
            )
        return recorded


def _register(ws: Workspace, occ: dict) -> dict:
    """Record an occurrence under its key, which is used once (LW-13)."""
    if any(r["key"] == occ["key"] for r in occurrences(ws)):
        raise DelegationError(f"Occurrence key {occ['key']} is already used.")
    base = {"status": "queued", "entries": [], "call": None, "job": None, "cites": []}
    base |= {"cause": None, "rescheduled_from": None, "rescheduled_to": None}
    return _append(ws, {**base, **occ, "rescheduled_date": None}, OCCURRENCES_DIR)


def _ask(ws: Workspace, record: dict, kind: str, what: str) -> None:
    """A call on the GM about an occurrence, which stays queued: left unanswered, nothing
    happens (LW-09, LW-10)."""
    call = calls.open_call(
        ws,
        kind=kind,
        responsibility="living_world",
        table_moment=delegation.current_moment(ws)[0],
        blocking=False,
        job=record["job"],
        message=f"Occurrence {record['key']} ({record['date']}): {what}.",
    )
    record["call"] = call["id"]
    _save(ws, record, OCCURRENCES_DIR)


def _id(prefix: str, key: str, role: str) -> str:
    """A file id derived from the occurrence key, which is used once: the effect is
    reproducible."""
    return f"{prefix}-{hashlib.sha256(f'{key}|{role}'.encode()).hexdigest()[:8]}"


class _Blocked(Exception):
    """Why an occurrence cannot apply now; it stays queued and calls on the GM."""


def _evolution(
    key: str,
    old: dict | None,
    new_state: dict,
    statement: str,
    description: str,
    date: str,
    rank: str,
    origin: dict,
    knowers: list[str],
) -> list[Change]:
    """An offscreen event closing `old` and opening the new state fact, and what its knowers
    learn (LW-03, LW-11). File ids derive from the occurrence key, used once."""
    fact_id, event_id = _id("f", key, "fact"), _id("v", key, "event")
    fact: dict[str, Any] = {"id": fact_id, "entities": [new_state["of"]], "relation": None}
    fact |= {"valid_from": None, "valid_to": None, "rank": rank, "origin": origin}
    fact["state"] = new_state
    event: dict[str, Any] = {"id": event_id, "date": date, "kind": "offscreen"}
    event |= {"opens": [fact_id], "closes": [old["id"]] if old else [], "replaces": None}
    event |= {"rank": rank, "origin": origin}
    changes = [
        Change(f"{index.FACTS_DIR}/{fact_id}.md", index.join_doc(fact, statement), key),
        Change(f"{index.EVENTS_DIR}/{event_id}.md", index.join_doc(event, description), key),
    ]
    for knower in dict.fromkeys(knowers):  # LW-11: the carrier and named participants only
        k_id = _id("k", key, knower)
        record: dict[str, Any] = {"id": k_id, "knower": knower, "fact": fact_id, "mode": "knows"}
        record |= {"date": date, "event": event_id, "rank": rank, "origin": origin}
        changes.append(Change(f"{index.KNOWLEDGE_DIR}/{k_id}.md", index.join_doc(record, ""), key))
    return changes


def _effect(ws: Workspace, record: dict, rank: str, origin: dict) -> list[Change]:
    """The files one occurrence writes; `_Blocked` when it no longer applies or contradicts
    played canon (LW-09)."""
    s = _current(ws).get(record["entity"], {AGENDA: []})
    key, date, entity = record["key"], record["date"], record["entity"]
    names = {e["id"]: e["names"][0] for e in index.search_entities(ws)}
    if record["kind"] == "tick":
        if FRONT not in s:
            raise _Blocked(f"{entity} is no longer a front")
        rule, old = s[FRONT]["state"]["value"], s.get(CLOCK)
        value = (old["state"]["value"] if old else 0) + record["ticks"]
        new_state = {"of": entity, "key": CLOCK, "value": value}
        # ponytail: state statements are language-neutral data; a playbook words them if needed.
        statement = f"{names[entity]}: {value}/{rule['capacity']}"
        knowers = [rule["carrier"], *rule["participants"]]
    elif record["kind"] == "step":
        old = next((a for a in s[AGENDA] if a["id"] == record["rule"]), None)
        if old is None or FRONT not in s:
            raise _Blocked(f"agenda fact {record['rule']} no longer holds")
        rule = s[FRONT]["state"]["value"]
        new_state = {**old["state"], "value": {**old["state"]["value"], "status": "done"}}
        statement = old["statement"]
        knowers = [rule["carrier"], *rule["participants"]]
    else:
        old = s.get(SITUATION)
        if old is None or old["id"] != record["rule"]:
            raise _Blocked(f"situation fact {record['rule']} no longer holds")
        new_state = {**old["state"], "value": {**old["state"]["value"], "stage": "expired"}}
        statement = f"{names[entity]}: expired"
        knowers = old["state"]["value"]["participants"]
    # LW-09: played canon wins, even over a rule effect: the state it closes, or a later state
    # of the same kind the table played.
    played = [old] if old and old["rank"] == "played" else []
    played += [
        f
        for f in index.search_facts(ws, entity=entity)
        if f["rank"] == "played"
        and (f.get("state") or {}).get("key") == new_state["key"]
        and f["valid_from"]
        and index.date_key(ws.calendar, f["valid_from"]) > index.date_key(ws.calendar, date)
    ]
    if played:
        raise _Blocked(f"it contradicts played fact {played[0]['id']}")
    return _evolution(key, old, new_state, statement, key, date, rank, origin, knowers)


def _rule_rank(ws: Workspace, record: dict) -> tuple[str, dict]:
    """A rule effect keeps the rank of the decision that wrote its rule (ADR 0009)."""
    [rule] = [
        f for f in index.search_facts(ws, include_retconned=True) if f["id"] == record["rule"]
    ]
    return rule["rank"], {"kind": "rule", "fact": record["rule"], "key": record["key"]}


def _apply(
    ws: Workspace,
    record: dict,
    rank: tuple[str, dict] | None = None,
    approve: tuple[str, bool] | None = None,
) -> bool:
    """Apply one occurrence through the action log, every file tagged with its key, then cascade
    a tick into the threshold steps it crosses (T5). `approve` (channel, authenticated) approves
    at once what the level held for approval: the GM accepted it. False when it stays queued
    behind a call on the GM."""
    rank_, origin = rank or _rule_rank(ws, record)
    try:
        changes = _effect(ws, record, rank_, origin)
    except _Blocked as e:
        _ask(ws, record, "exception", f"{e}; reschedule, reject or retcon")
        return False
    for change in changes:
        result = delegation.act(
            ws, _effect_tool(), AGENT, lambda c=change: c, occurrence=record["key"]
        )
        if result["status"] == "pending" and approve is not None:
            delegation.approve(ws, result["entry"], *approve)
        record["entries"].append(result["entry"])
    record["status"] = "applied"
    _save(ws, record, OCCURRENCES_DIR)
    if record["kind"] == "tick":
        _cascade(ws, record, approve)
    return True


def _cascade(ws: Workspace, tick: dict, approve: tuple[str, bool] | None) -> None:
    """The threshold steps a tick crosses, dated at the tick, each once (T5): new ones, and
    those an undo returned to the queue with it."""
    s = _current(ws).get(tick["entity"], {AGENDA: []})
    clock = s[CLOCK]["state"]["value"] if CLOCK in s else 0
    known = {r["key"]: r for r in occurrences(ws)}
    for a in s[AGENDA]:
        step = a["state"]["value"]
        key = f"{tick['entity']}/{step['id']}"
        if step["status"] != "pending" or step["when"].get("clock_gte", clock + 1) > clock:
            continue
        if key not in known:
            occ = {"key": key, "kind": "step", "class": "rule", "entity": tick["entity"]}
            occ |= {"date": tick["date"], "rule": a["id"], "cause": tick["key"]}
            _apply(ws, _register(ws, occ), approve=approve)
        elif known[key]["status"] == "queued" and known[key]["cause"] == tick["key"]:
            _apply(ws, known[key], approve=approve)


# What agents and the GM do with a queued occurrence


def settle_unless(
    ws: Workspace, key: str, unless_holds: bool | None, cites: list[str], job: int
) -> dict:
    """The `settle-an-unless` job's answer (LW-10): whether the front's `unless` held on the
    tick's date, citing the ids of facts valid then. If it held, the tick does not happen; if
    not, it applies, at the agent-proposal rank. No citation, or no answer, calls on the GM at
    the next break and the tick stays queued."""
    from secondchair.core import jobs

    with locked(ws):
        record = _find(ws, key)
        if record["kind"] != "tick" or record["class"] != "derived" or record["status"] != "queued":
            raise DelegationError(f"{key} is not a queued tick waiting on its unless.")
        contract = jobs.read(ws, job)
        if contract["status"] != "started" or contract["inputs"].get("occurrence") != key:
            raise DelegationError(f"Job {job} is not the started job settling {key}.")
        if unless_holds is None or not cites:
            _ask(ws, record, "exception", "its unless could not be settled from canon")
            return record
        valid = {f["id"] for f in index.search_facts(ws, at=record["date"])}
        if missing := [c for c in cites if c not in valid]:
            raise CanonError(f"Facts {missing} are not canon facts valid on {record['date']}.")
        record["cites"] = list(cites)
        if unless_holds:
            record["status"] = "suppressed"
            _save(ws, record, OCCURRENCES_DIR)
            return record
        level = delegation.effective_level(ws, "living_world", contract["moment"], True)
        if level == "propose":
            _save(ws, record, OCCURRENCES_DIR)
            _ask(ws, record, "proposal", "its unless was settled as not holding; accept it")
        else:
            _apply(ws, record, ("agent_proposal", {"kind": "job", "job": str(job)}))
        return record


def decide(
    ws: Workspace,
    key: str,
    answer: str,
    authenticated: bool,
    date: str | None = None,
    channel: str = "cli",
) -> dict:
    """The GM's answer to a queued occurrence: `accept` applies it at its original date (LW-17),
    `reject` drops it for good (its key stays used, LW-13), `reschedule` moves it to `date`
    under a new key linked to it (LW-16)."""
    with locked(ws):
        record = _find(ws, key)
        if record["status"] != "queued":
            raise DelegationError(f"{key} is {record['status']}, not queued.")
        if record["call"] is not None:
            calls.close(ws, record["call"])
        if answer == "accept":
            if record["class"] == "narrative":
                raise DelegationError(
                    f"{key} is new narrative: answer its narrative-direction proposal, or reject "
                    "or reschedule it."
                )
            record["call"] = None
            _apply(ws, record, approve=(channel, authenticated))
        elif answer == "reject":
            record["status"] = "rejected"
        elif answer == "reschedule":
            if date is None:
                raise DelegationError("Rescheduling needs the new date.")
            date = ws.calendar.canonical(date)
            record |= {"status": "rescheduled", "rescheduled_date": date}
            record["rescheduled_to"] = f"{key}~{date}"
        else:
            raise DelegationError(f"Answer {answer!r}: expected accept, reject or reschedule.")
        _save(ws, record, OCCURRENCES_DIR)
        return _find(ws, key)


def undo(ws: Workspace, key: str, reason: str, channel: str, authenticated: bool) -> list[str]:
    """Undo an applied occurrence with its cascade (the steps it crossed, and the later effects
    on the same entity, built on it) and return their keys to the queue (LW-12). Only while its
    moment lasts: then only a correction or a retcon. Returns the keys undone."""
    with locked(ws):
        records = occurrences(ws)
        target = _find(ws, key)
        if target["status"] != "applied":
            raise DelegationError(f"{key} is {target['status']}, not applied.")
        if target["kind"] in ("pause", "resume"):
            raise DelegationError(f"{key} is a GM gesture: resume or pause the front instead.")
        first = min(target["entries"])
        todo = {
            r["key"]: r
            for r in records
            if r["status"] == "applied"
            and r["kind"] not in ("pause", "resume")
            and (r["key"] == key or (r["entity"] == target["entity"] and min(r["entries"]) > first))
        }
        while more := [
            r
            for r in records
            if r["status"] == "applied" and r.get("cause") in todo and r["key"] not in todo
        ]:
            todo |= {r["key"]: r for r in more}
        for entry in sorted((e for r in todo.values() for e in r["entries"]), reverse=True):
            delegation.undo(ws, entry, reason, channel, authenticated)
        for r in todo.values():
            r |= {"status": "queued", "entries": []}
            _save(ws, r, OCCURRENCES_DIR)
        return sorted(todo)


def set_active(ws: Workspace, front: str, active: bool, date: str, authenticated: bool) -> dict:
    """Pause or resume a front, a GM gesture: no catch-up for the pause, and resuming
    re-anchors the rate on the resume date (LW-14). A pause is dated on or before the cursor
    and not before the front's last applied tick, a resume on or after the cursor."""
    with locked(ws):
        date, at = ws.calendar.canonical(date), cursor(ws)
        if at is None:
            raise DelegationError("No world-turn yet: run one before pausing or resuming.")

        def at_(d: str) -> int:
            return index.date_key(ws.calendar, d)

        if not (at_(date) >= at_(at) if active else at_(date) <= at_(at)):
            raise DelegationError(
                f"Resume on or after the cursor ({at}), pause on or before it; got {date}."
            )
        s = _current(ws).get(front, {})
        if FRONT not in s or s[FRONT]["state"]["value"]["active"] == active:
            raise DelegationError(
                f"{front} is not a front that is {'paused' if active else 'active'}."
            )
        old = s[FRONT]
        ticked = [
            r["date"]
            for r in occurrences(ws)
            if r["entity"] == front and r["kind"] == "tick" and r["status"] == "applied"
        ]
        if not active and any(at_(t) > at_(date) for t in ticked):
            raise DelegationError(f"{front} ticked after {date}; pause it on a later date.")
        value: dict[str, Any] = {**old["state"]["value"], "active": active}
        if active:
            value["anchor"] = date
        key = f"{front}/{'resume' if active else 'pause'}@{date}"
        words = f"{'Resume' if active else 'Pause'} {front} on {date}."
        origin = {"kind": "gm", "words": words}
        rank = "gm_decision" if authenticated else "agent_proposal"
        new_state = {**old["state"], "value": value}
        knowers = [value["carrier"], *value["participants"]]
        changes = _evolution(
            key, old, new_state, old["statement"], words, date, rank, origin, knowers
        )
        record = _register(
            ws,
            {"key": key, "kind": "resume" if active else "pause", "class": "rule"}
            | {"entity": front, "date": date, "rule": old["id"]},
        )
        for change in changes:
            result = delegation.act(ws, _effect_tool(), "gm", lambda c=change: c, occurrence=key)
            if result["status"] == "pending":
                delegation.approve(ws, result["entry"], "cli", authenticated)
            record["entries"].append(result["entry"])
        record["status"] = "applied"
        _save(ws, record, OCCURRENCES_DIR)
        return record


# Served to agents


def tools(ws: Workspace) -> list[Tool]:
    """The living world's reads."""

    def living_world() -> dict[str, Any]:
        """The living world now: each front's clock, capacity, whether it is active and its
        agenda steps' statuses, each situation's stage and deadline (by entity id), the
        world-turn cursor, and the occurrences still queued for a decision."""
        return {
            **state(ws),
            "cursor": cursor(ws),
            "queued": [r for r in occurrences(ws) if r["status"] == "queued"],
        }

    def forecast_world(until: str) -> list[dict[str, Any]]:
        """A read-only forecast for prep: the occurrences coming world-turns would record up to
        the campaign date `until`, ticks grouped by front beyond six. Writes nothing."""
        return forecast(ws, until)

    return [
        Tool(
            fn=living_world, responsibility="living_world", delegated_action=False, reversible=True
        ),
        Tool(
            fn=forecast_world,
            responsibility="living_world",
            delegated_action=False,
            reversible=True,
        ),
    ]


def agent_tools(ws: Workspace) -> list:
    """What a `settle-an-unless` job calls, served by the Core."""

    def settle_unless_(
        occurrence: str, unless_holds: bool | None, cites: list[str], job: int
    ) -> dict[str, Any]:
        """Settle a front tick's `unless` for your started settle-an-unless job: whether the
        condition held on the tick's date (`unless_holds`), citing the ids of canon facts valid
        on that date. When canon does not settle it, pass null: the GM is asked at the next
        break and the tick waits. Never guess."""
        with delegation._for_agent():
            return settle_unless(ws, occurrence, unless_holds, cites, job)

    settle_unless_.__name__ = "settle_unless"
    return [settle_unless_]
