"""The living world (05-living-world-calendar.md, ADR 0009): fronts and situations whose state is
facts, the world-turn that advances them and the forecast that looks ahead.

A front or a situation is an entity; all its state is **state facts**, facts carrying
`state: {of, key, value}` (LW-03): on a front, `front` (its rule: carrier, participants,
capacity, rate, `unless`, active), `clock` and one `agenda` fact per step; on a situation,
`situation` (stage, deadline, participants); on a faction, `intent`, `pool`, `capacity` and
`catalogue`, which the GM writes (ADR 0022). Every effect is an offscreen event closing the old
state fact and opening the new one, known only to the carrier and the named participants
(LW-11).

The world-turn is deterministic over `]cursor, now]` (LW-04): the v3 occurrence keys
(`<front>/tick@<date>`, `<front>/<step>`, `<situation>/deadline@<date>`, a rescheduled key
`<key>~<date>`, and a faction's `<faction>/<action>@<date>` and `<faction>/income@<date>`)
are each used once, whatever happens to them (LW-13). Rule effects apply at the
living world's level with the rule's rank; an `unless` and a narrative deadline become jobs
(LW-06); an occurrence contradicting played canon becomes a call and stays queued (LW-09).

Workspace files (docs/contracts/workspace-layout.md): `living-world.yaml` (the cursor) and one
YAML file per occurrence in `occurrences/`; every effect's files are action log entries carrying
the occurrence key, which is what undo walks (LW-12). An occurrence and its cascade are planned
in memory, then written through one roll-forward journal (ADR 0016).
"""

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import yaml

from secondchair.core import admission, calls, delegation, index, journal, knowledge
from secondchair.core.calendar import Calendar, CalendarError
from secondchair.core.delegation import (
    LOG_DIR,
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
from secondchair.core.workspace import CONFIG_FILE, Workspace, WorkspaceError

FRONT, CLOCK, AGENDA, SITUATION = "front", "clock", "agenda", "situation"
INTENT, POOL, CAPACITY, CATALOGUE = "intent", "pool", "capacity", "catalogue"  # ADR 0022
FACTION_KEYS = (INTENT, POOL, CAPACITY, CATALOGUE)
ACTION, FAILURE = "action", "failure"  # a faction's validated choice, and one that failed
INCOME = "income"  # a faction's income for one faction step (ADR 0022 item 2)
EFFECT_CLASSES = ("derived", "narrative")  # a catalogue effect's class, the GM's call (ADR 0009)
STEP = "1w"  # the campaign-wide faction step unless workspace.yaml sets faction_step (ADR 0022)
STAGES = ("available", "active", "resolved", "expired")  # `active`: the party engaged it
STEP_STATUSES = ("pending", "done", "averted")
GROUP_ABOVE = 6  # LW-15
AGENT = "world-turn"


def _effect_tool() -> Tool:
    return Tool(
        fn=world_turn, responsibility="living_world", delegated_action=True, reversible=True
    )


# State facts


def check_state(cal: Calendar, state: Any) -> tuple[dict, list[str]]:
    """A state fact's `state`, normalised, and the entity ids its value names; `CanonError` when
    its shape is not one the world-turn reads."""
    if not isinstance(state, dict) or set(state) != {"of", "key", "value"}:
        raise CanonError("state needs exactly of (an entity id), key and value.")
    key, value = state["key"], state["value"]

    def fields(
        required: set[str], optional: dict[str, Any], v: Any = value, what: str = f"{key} state"
    ) -> dict:
        if not isinstance(v, dict) or not required <= set(v) <= required | set(optional):
            raise CanonError(f"A {what} needs {sorted(required)}, optionally {sorted(optional)}.")
        return {**optional, **v}

    def ids(v: Any, what: str = "participants") -> list[str]:
        if not isinstance(v, list) or not all(isinstance(i, str) and i for i in v):
            raise CanonError(f"{what} must be a list of entity ids.")
        return v

    def words(v: Any, what: str) -> None:
        if not isinstance(v, str) or not v.strip():
            raise CanonError(f"{what} is words in the campaign language.")

    def count(v: Any, what: str, least: int = 0) -> int:
        if type(v) is not int or v < least:
            raise CanonError(f"{what} is an integer of at least {least}.")
        return v

    def items(v: Any, what: str, least: int = 1, most: int | None = None) -> list:
        if not isinstance(v, list) or len(v) < least or (most is not None and len(v) > most):
            raise CanonError(f"{what} is a list of {least} to {most or 'any number of'} items.")
        return v

    def unique(found: list[dict], what: str) -> None:
        if len({i["id"] for i in found}) != len(found):
            raise CanonError(f"Each {what} has its own id.")

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
    elif key == INTENT:  # one to three goals, in the GM's priority order (ADR 0022, item 7)
        goals = items(value, "An intent", 1, 3)
        value = [fields({"id", "goal", "pursues"}, {}, g, "goal") for g in goals]
        for g in value:
            words(g["id"], "A goal's id")
            words(g["goal"], "A goal")
            refs += ids(items(g["pursues"], "A goal's pursues"), "pursues (fronts or situations)")
        unique(value, "goal")
    elif key == POOL:  # named integer resources, each with its income per step and its cap
        if not isinstance(value, dict) or not value:
            raise CanonError("A pool state maps one or more resource names to their value.")
        for name, r in value.items():
            words(name, "A resource's name")
            r = fields({"value", "income", "cap"}, {}, r, f"resource {name!r}")
            count(r["income"], f"{name}'s income")
            if count(r["value"], f"{name}'s value") > count(r["cap"], f"{name}'s cap"):
                raise CanonError(f"{name}'s value is at most its cap.")
    elif key == CAPACITY:
        count(value, "A capacity (actions per step)", 1)
    elif key == CATALOGUE:
        value = [
            fields(
                {"id", "cost", "duration", "effect"},
                {"prerequisites": [], "target": None, "contest": None, "serves": []},
                a,
                "catalogue action",
            )
            for a in items(value, "A catalogue")
        ]
        for a in value:
            words(a["id"], "An action's id")
            if {"/", "@"} & set(a["id"]):  # it names the occurrence <faction>/<action>@<date>
                raise CanonError(f"An action's id has no '/' or '@': {a['id']!r}.")
            if not isinstance(a["cost"], dict):
                raise CanonError(f"{a['id']}'s cost maps pool names to integers.")
            for name, n in a["cost"].items():
                words(name, "A cost's pool")
                count(n, f"{a['id']}'s cost in {name}")
            try:
                cal.days(a["duration"])
            except CalendarError as e:
                raise CanonError(str(e)) from e
            a["effect"] = fields({"class", "does"}, {}, a["effect"], "effect template")
            if a["effect"]["class"] not in EFFECT_CLASSES:
                raise CanonError(f"An effect's class is one of {', '.join(EFFECT_CLASSES)}.")
            words(a["effect"]["does"], "An effect's does")
            for p in items(a["prerequisites"], "Prerequisites", 0):
                if isinstance(p, dict) and set(p) == {"holds"}:
                    words(p["holds"], "A prerequisite's holds (a fact id)")
                elif isinstance(p, dict) and set(p) == {"front", "clock_gte"}:
                    count(p["clock_gte"], "A prerequisite's clock_gte", 1)
                    refs += ids([p["front"]], "A prerequisite's front")
                elif isinstance(p, dict) and set(p) == {"situation", "stage"}:
                    if p["stage"] not in STAGES:
                        raise CanonError(f"A prerequisite's stage is one of {', '.join(STAGES)}.")
                    refs += ids([p["situation"]], "A prerequisite's situation")
                else:
                    raise CanonError(
                        "A prerequisite is {holds: fact id}, {front, clock_gte} or "
                        "{situation, stage}."
                    )
            for goal in items(a["serves"], "An action's serves (goal ids)", 0):
                words(goal, "A served goal's id")
            if a["target"] is not None:
                refs += ids([a["target"]], "An action's target")
            if a["contest"] is not None:
                contest = fields({"pool"}, {}, a["contest"], "contest rule")
                words(contest["pool"], "A contest's pool")
                if a["target"] is None:
                    raise CanonError(f"{a['id']} has a contest rule but no target.")
        unique(value, "catalogue action")
    else:
        raise CanonError(
            f"Unknown state key {key!r}; expected front, clock, agenda, situation, intent, pool, "
            "capacity or catalogue."
        )
    return {**state, "value": value}, refs


def _current(
    ws: Workspace, at: str | None = None, head: bool = False, overlay: Sequence[Change] = ()
) -> dict[str, dict[str, Any]]:
    """Entity id -> its state facts valid on `at`, by default the cursor (#170): one per key, a
    list of agenda steps. A belief (`never_true`) never is. `head`: the head of each chain, the
    fact no event closes whatever its dates (#205), which an effect transforms (an occurrence
    may be applied after a later one, LW-17) and whose dates `_holds` checks; a `valid_to` the
    GM scheduled does not close it; `overlay`, planned changes not yet written, counts as canon
    (ADR 0016). Before the first world-turn, on the campaign's current date (`time.yaml`); with
    neither date, the open ones. The rule is `index.holds`."""
    from secondchair.core import capture  # it builds on canon, which builds on this module

    if head:
        docs = [(c.path, *index.split_doc(c.after)) for c in overlay if c.after is not None]
        planned = [d for path, d, _ in docs if path.startswith(f"{index.EVENTS_DIR}/")]
        events = [e for e in index.search_events(ws) if e["status"] == "canon"] + planned
        closed = {c for e in events for c in e["closes"]}
        facts = [f for f in index.search_facts(ws) if not f["never_true"] and f["id"] not in closed]
        opened = {o: e["date"] for e in planned for o in e["opens"]}
        facts += [
            {**d, "statement": body, "valid_from": opened.get(d["id"]), "never_true": False}
            for path, d, body in docs
            if path.startswith(f"{index.FACTS_DIR}/") and d["id"] not in closed
        ]
    elif at := at or cursor(ws) or capture.time(ws)["current_date"]:
        facts = index.search_facts(ws, at=at)
    else:
        facts = [f for f in index.search_facts(ws) if index.holds(ws.calendar, f, None)]
    found: dict[str, dict[str, Any]] = {}
    for f in facts:
        if f.get("state") is None:
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


def _holds(ws: Workspace, f: dict, date: str) -> bool:
    """Whether fact `f` holds on `date`, by the as-of rule of `search_facts`."""
    return index.holds(ws.calendar, f, date)


def faction_step(ws: Workspace) -> int:
    """Days in the campaign-wide faction step, over which income and capacity count: one week
    unless `workspace.yaml` sets `faction_step` (ADR 0022, GM answer 1)."""
    config = yaml.safe_load((ws.root / CONFIG_FILE).read_text()) or {}
    try:
        return ws.calendar.days(config.get("faction_step", STEP))
    except CalendarError as e:
        raise WorkspaceError(f"workspace.yaml: faction_step: {e}") from e


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

    for entity, s in sorted(_current(ws, head=True).items()):  # each date checked with _holds
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
                if at(day) > at(since) and key not in used and _holds(ws, s[FRONT], day):
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
                    and _holds(ws, s[FRONT], step["when"]["date"])
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
                and _holds(ws, s[SITUATION], v["deadline"])
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
            # A successor applies on its own date: no tick cascades into it.
            more = {"ticks": r["ticks"]} if r.get("ticks") is not None else {}
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
    keeping its key (LW-15); a faction's failed choices are one group, collapsed, each with its
    reason (ADR 0022, GM answer 3)."""
    ticks = Counter(o["entity"] for o in planned if o["kind"] == "tick")
    shown: list[dict] = []
    groups: dict[str, dict] = {}
    failures: dict[str, dict] = {}
    for o in planned:
        if o["kind"] == FAILURE:
            if o["entity"] not in failures:
                failures[o["entity"]] = {"kind": "failures", "entity": o["entity"], "failed": {}}
                shown.append(failures[o["entity"]])
            failures[o["entity"]]["failed"][o["key"]] = o["validation"]
        elif o["kind"] == "tick" and ticks[o["entity"]] > GROUP_ABOVE:
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
        _check_recovered(ws)
        before = {r["id"] for r in occurrences(ws)}
        for occ in plan(ws, start, now):
            if occ.get("cause"):  # a threshold step: the tick it crosses at applies it
                continue
            if occ["class"] == "rule":
                record = _new(occ)  # written by applying it, or by the call holding it
                if level == "propose":
                    _ask(ws, record, "proposal", "accept, reject or reschedule it")
                else:
                    _apply(ws, record)
            else:
                record = _register(ws, occ)
                narrative = record["class"] == "narrative"
                record["job"] = jobs.queue(
                    ws,
                    playbook="propose-narrative-direction" if narrative else "settle-an-unless",
                    inputs={"occurrence": record["key"]},
                    expected_output="A narrative-direction proposal for the deadline."
                    if narrative
                    else "The unless settled with settle_unless, citing fact ids.",
                    responsibility="narrative_direction" if narrative else "living_world",
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
            )
        return recorded


def _new(occ: dict) -> dict:
    """A queued occurrence record, not yet written."""
    base = {"status": "queued", "entries": [], "call": None, "job": None, "cites": []}
    base |= {"cause": None, "rescheduled_from": None, "rescheduled_to": None}
    return {**base, **occ, "rescheduled_date": None}


def _register(ws: Workspace, occ: dict) -> dict:
    """Record an occurrence under its key, which is used once (LW-13)."""
    if any(r["key"] == occ["key"] for r in occurrences(ws)):
        raise DelegationError(f"Occurrence key {occ['key']} is already used.")
    return _append(ws, _new(occ), OCCURRENCES_DIR)


def _ask(ws: Workspace, record: dict, kind: str, what: str) -> None:
    """A call on the GM about an occurrence, which stays queued: left unanswered, nothing
    happens (LW-09, LW-10). A record not yet written is, with it."""
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
    if "id" in record:
        _save(ws, record, OCCURRENCES_DIR)
    else:
        written = _append(ws, record, OCCURRENCES_DIR)
        record.clear()
        record.update(written)


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
    closed_on: str | None = None,
) -> list[Change]:
    """An offscreen event closing `old` and opening the new state fact, and what its knowers
    learn (LW-03, LW-11). File ids derive from the occurrence key, used once. `closed_on`: `old`
    starts after `date` (a later occurrence applied first, LW-17), so a second event, on its
    start, closes it and opens the new fact: no fact ends before it starts (#205) and the chain
    never overlaps (#170). The first event keeps the occurrence's date and changes nothing; a
    retcon of either replaces both (`index`)."""
    fact_id, event_id = _id("f", key, "fact"), _id("v", key, "event")
    fact: dict[str, Any] = {"id": fact_id, "entities": [new_state["of"]], "relation": None}
    fact |= {"valid_from": None, "valid_to": None, "rank": rank, "origin": origin}
    fact["state"] = new_state
    event: dict[str, Any] = {"id": event_id, "date": date, "kind": "offscreen"}
    event |= {"opens": [fact_id], "closes": [old["id"]] if old else [], "replaces": None}
    event |= {"rank": rank, "origin": origin}
    events = [event]
    if closed_on:
        events.insert(0, {**event, "id": _id("v", key, "close"), "date": closed_on})
        event |= {"opens": [], "closes": []}
    opener = events[0]  # what the knowers learn it at, when it starts
    changes = [Change(f"{index.FACTS_DIR}/{fact_id}.md", index.join_doc(fact, statement), key)]
    changes += [
        Change(f"{index.EVENTS_DIR}/{e['id']}.md", index.join_doc(e, description), key)
        for e in events
    ]
    for knower in dict.fromkeys(knowers):  # LW-11: the carrier and named participants only
        k_id = _id("k", key, knower)
        record: dict[str, Any] = {"id": k_id, "knower": knower, "fact": fact_id, "mode": "knows"}
        record |= {"date": opener["date"], "event": opener["id"], "rank": rank, "origin": origin}
        changes.append(Change(f"{index.KNOWLEDGE_DIR}/{k_id}.md", index.join_doc(record, ""), key))
    return changes


def _effect(
    ws: Workspace, record: dict, rank: str, origin: dict, overlay: Sequence[Change] = ()
) -> list[Change]:
    """The files one occurrence writes over canon and the `overlay` of changes planned before
    it; `_Blocked` when it no longer applies or contradicts played canon (LW-09)."""
    s = _current(ws, head=True, overlay=overlay).get(record["entity"], {AGENDA: []})
    key, date, entity = record["key"], record["date"], record["entity"]
    if FRONT in s and not _holds(ws, s[FRONT], date):
        raise _Blocked(f"{entity} is not a front on {date}")
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
    elif record["kind"] in (INCOME, ACTION):  # a faction's pools (ADR 0022 items 2 and 4)
        old = s.get(POOL)
        if old is None or not _decided(old):
            raise _Blocked(f"{entity} holds no pool")
        pools = old["state"]["value"]
        if record["kind"] == INCOME:
            if (value := _credited(pools)) == pools:  # a late accept finds them at their caps
                raise _Blocked(f"{entity}'s pools are at their caps")
        else:  # a pool never goes below zero, whatever moved since the validation
            debit = record["debit"]
            if short := {n: c for n, c in debit.items() if n not in pools or c > pools[n]["value"]}:
                raise _Blocked(f"its pools no longer cover {json.dumps(short)}")
            value = {n: {**r, "value": r["value"] - debit.get(n, 0)} for n, r in pools.items()}
        new_state = {**old["state"], "value": value}
        statement = f"{names[entity]}: " + ", ".join(
            f"{n} {r['value']}/{r['cap']}" for n, r in value.items()
        )
        knowers = [entity]
    else:
        old = s.get(SITUATION)
        if old is None or old["id"] != record["rule"]:
            raise _Blocked(f"situation fact {record['rule']} no longer holds")
        new_state = {**old["state"], "value": {**old["state"]["value"], "stage": "expired"}}
        statement = f"{names[entity]}: expired"
        knowers = old["state"]["value"]["participants"]

    # LW-09: played canon wins, even over a rule effect: the state it closes, or a later state
    # of the same kind the table played.
    # A state the world-turn itself wrote (at a played rule's rank) is not played canon.
    def table(f: dict) -> bool:
        return f["rank"] == "played" and f["origin"].get("kind") != "rule"

    admission.admit(ws, origin, admission.CORE)  # the world-turn composes its own origin
    played = [old] if old and table(old) else []
    played += [
        f
        for f in index.search_facts(ws, entity=entity)
        if table(f)
        and (f.get("state") or {}).get("key") == new_state["key"]
        and f["valid_from"]
        and index.date_key(ws.calendar, f["valid_from"]) > index.date_key(ws.calendar, date)
    ]
    if played:
        raise _Blocked(f"it contradicts played fact {played[0]['id']}")
    late = bool(old and old["valid_from"]) and not _holds(ws, {**old, "valid_to": None}, date)
    closed_on = old["valid_from"] if late else None  # LW-17: the event keeps the date
    return _evolution(key, old, new_state, statement, key, date, rank, origin, knowers, closed_on)


def _rule_rank(ws: Workspace, record: dict) -> tuple[str, dict]:
    """A rule effect keeps the rank of the decision that wrote its rule (ADR 0009)."""
    [rule] = [
        f for f in index.search_facts(ws, include_retconned=True) if f["id"] == record["rule"]
    ]
    return rule["rank"], {"kind": "rule", "fact": record["rule"], "key": record["key"]}


_Plan = list[tuple[dict, list[Change] | None, str | None]]  # each record, its changes or why not


def _changes(
    ws: Workspace, record: dict, rank: tuple[str, dict] | None, overlay: Sequence[Change]
) -> list[Change]:
    if record["kind"] == FAILURE:
        return _failure(ws, record)
    if record["kind"] == ACTION:  # its debit and its effect, one plan (ADR 0022 item 4)
        rank = ("agent_proposal", {"kind": "rule", "fact": record["rule"], "key": record["key"]})
        debit = _effect(ws, record, *rank, overlay) if any(record["debit"].values()) else []
        return debit + _learnt(ws, record, f": {_does(ws, record)}", "effect")
    if record["kind"] == INCOME and rank is None:  # the rank of the pool it credits, its head:
        head = _current(ws, head=True, overlay=overlay).get(record["entity"], {}).get(POOL)
        if head is not None:  # a debited pool's lower rank is never promoted (ADR 0009)
            rank = (head["rank"], {"kind": "rule", "fact": record["rule"], "key": record["key"]})
    if rank is None and record["cites"]:  # an unless settled by a job (LW-10)
        rank = ("agent_proposal", {"kind": "job", "job": str(record["job"])})
    return _effect(ws, record, *(rank or _rule_rank(ws, record)), overlay)


def _apply(
    ws: Workspace,
    record: dict,
    rank: tuple[str, dict] | None = None,
    approve: tuple[str, bool] | None = None,
    job: int | None = None,
) -> bool:
    """Apply one occurrence, cascading a tick into the threshold steps it crosses (T5), as one
    plan (ADR 0016): computed in memory, its level checked once, then written through one
    roll-forward journal, every file an action log entry tagged with its key. `approve`
    (channel, authenticated) approves at once what the level held for approval: the GM
    accepted it. False when it stays queued behind a call on the GM; the record is then
    written, and nothing else."""
    _check_recovered(ws)
    try:
        changes = _changes(ws, record, rank, [])
    except _Blocked as e:
        _ask(ws, record, "exception", f"{e}; reschedule, reject or retcon")
        return False
    planned: _Plan = [(record, changes, None)]
    if record["kind"] == "tick":
        planned += _cascade(ws, record, changes)
    applied = [(c, r["key"]) for r, changes, _ in planned for c in changes or []]
    entries = delegation.plan_actions(ws, _effect_tool(), AGENT, applied, job, approve)
    if entries is None:  # held at propose whole, nothing journaled
        _ask(ws, record, "proposal", "accept, reject or reschedule it")
        return False
    _journal(ws, record, planned, entries)
    for step, _, why in planned[1:]:
        if why is not None:
            _ask(ws, step, "exception", f"{why}; reschedule, reject or retcon")
    return True


def _check_recovered(ws: Workspace) -> None:
    """Refuse while recovery keeps a journal stopped: its canon is half-written (ADR 0016)."""
    if stopped := [j["key"] for _, j in journal._journals(ws)]:
        raise DelegationError(
            f"Occurrence {stopped[0]} was interrupted and recovery stopped on a changed file: "
            "answer its exception call, then run `secondchair recover`."
        )


def _cascade(ws: Workspace, tick: dict, overlay: Sequence[Change]) -> _Plan:
    """The threshold steps a tick crosses, dated at the tick, each once (T5): new ones, and
    those an undo returned to the queue with it; each with its changes over the tick's and the
    earlier steps', or why it is blocked. Writes nothing."""
    s = _current(ws, head=True, overlay=overlay).get(tick["entity"], {AGENDA: []})
    clock = s[CLOCK]["state"]["value"] if CLOCK in s else 0
    known = {r["key"]: r for r in occurrences(ws)}
    overlay, steps = list(overlay), []
    for a in s[AGENDA]:
        step = a["state"]["value"]
        key = f"{tick['entity']}/{step['id']}"
        if step["status"] != "pending" or step["when"].get("clock_gte", clock + 1) > clock:
            continue
        if key not in known:
            occ = {"key": key, "kind": "step", "class": "rule", "entity": tick["entity"]}
            record = _new(occ | {"date": tick["date"], "rule": a["id"], "cause": tick["key"]})
        elif known[key]["status"] == "queued" and known[key]["cause"] == tick["key"]:
            record = known[key]
        else:
            continue
        try:
            changes = _changes(ws, record, None, overlay)
        except _Blocked as e:
            steps.append((record, None, str(e)))
            continue
        overlay += changes
        steps.append((record, changes, None))
    return steps


def _journal(
    ws: Workspace,
    record: dict,
    planned: _Plan,
    entries: list[dict],
    entities: Sequence[str] = (),
    facts: Sequence[str] = (),
    files: Sequence[str] = (),
) -> None:
    """Write the plan through its journal (ADR 0016): each target then its log entries, then the
    step records, then `record`'s, the commit marker. Updates the records in memory. What the
    plan read, for the digest: `record`'s entity and `entities` (their facts), `facts`, the
    rules and cites, and other workspace `files`."""
    groups: list[list[dict]] = []  # each action entry, with its approval if any
    for e in entries:
        if e["kind"] == "action":
            groups.append([e])
        else:
            groups[-1].append(e)
    writes, todo = [], iter(groups)
    for r, changes, _ in planned:
        if changes is None:
            continue
        r["entries"] = []
        for change in changes:
            group = next(todo)
            writes.append(
                {"path": change.path, "before": group[0]["before"], "after": change.after}
            )
            writes += [
                {
                    "path": f"{LOG_DIR}/{e['id']:06d}.yaml",
                    "before": None,
                    "after": delegation.dump(e),
                }
                for e in group
            ]
            r["entries"].append(group[0]["id"])
        r["status"] = "applied"
    records, next_id = [], delegation._next_id(ws, OCCURRENCES_DIR)
    for r, changes, _ in planned:
        if changes is None and "id" in r:
            continue  # blocked and queued already: its call is all it gets
        before = None
        if "id" in r:
            before = (ws.root / OCCURRENCES_DIR / f"{r['id']:06d}.yaml").read_text()
        else:
            at = entries[0]["at"] if entries else datetime.now(UTC).isoformat()
            written = {"id": next_id, "at": at, **r}
            r.clear()
            r.update(written)
            next_id += 1
        path = f"{OCCURRENCES_DIR}/{r['id']:06d}.yaml"
        records.append({"path": path, "before": before, "after": delegation.dump(r)})
    entity, read = record["entity"], set(facts)
    entities = sorted({entity, *entities, *(r["entity"] for r, _, _ in planned)})
    for e in entities:
        read |= {f["id"] for f in index.search_facts(ws, entity=e, include_retconned=True)}
    read |= {r["rule"] for r, _, _ in planned} | {c for r, _, _ in planned for c in r["cites"]}
    events = [e["id"] for e in index.search_events(ws) if read & {*e["opens"], *e["closes"]}]
    reads = [f"{index.ENTITIES_DIR}/{e}.md" for e in entities]
    reads += [*(f"{index.FACTS_DIR}/{f}.md" for f in read), *files]
    reads += [f"{index.EVENTS_DIR}/{e}.md" for e in events]
    plan = journal.new_journal(ws, record["key"], entity, reads, writes + records[1:] + records[:1])
    journal.apply_journal(ws, plan)


# Faction turns (ADR 0022 items 4 and 5)


def _decided(f: dict) -> bool:
    """A faction state fact the validator reads: the GM's decision, or a rule effect on one."""
    return f["rank"] == "gm_decision" or f["origin"].get("kind") == "rule"


def _meets(p: dict, f: dict) -> bool:
    """Whether fact `f` satisfies catalogue prerequisite `p`, whatever its dates."""
    if "holds" in p:
        return f["id"] == p["holds"]
    s = f.get("state") or {}
    if "front" in p:
        return s.get("of") == p["front"] and s["key"] == CLOCK and s["value"] >= p["clock_gte"]
    return (
        s.get("of") == p["situation"]
        and s["key"] == SITUATION
        and s["value"]["stage"] == p["stage"]
    )


def roll(key: str) -> int:
    """A d20 seeded from an occurrence key, `<faction>/<action>@<date>`: the campaign date, the
    faction and the action id, so a replay rolls the same (ADR 0022 item 5)."""
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % 20 + 1


def validate(ws: Workspace, date: str, choices: Any) -> list[dict]:
    """Each faction's ranked choices `{faction: [{action, cites: [fact ids]}]}` checked against
    truth on `date`, not belief, in rank order: its pools name every pool the action costs or
    contests, it has capacity left, every prerequisite holds, its pools cover the cost. Two
    accepted choices contesting one target resolve by the committed pool (the action's cost in
    its contest pool), then `roll`, then the key; a loser stays lost, whatever happens to its
    winner later, and commits nothing, so the budgets are computed again without the losers
    until no new one loses. A failed prerequisite some fact the faction knows or believes would
    meet is a false belief. Only `_decided` faction facts count. One verdict per choice,
    `reason` None when accepted; writes nothing. `CanonError`, the whole output refused, when
    it is malformed, cites an id that is no canon fact (a belief may be cited), or a choice
    names no action of its faction's catalogue or a used key."""
    if not isinstance(choices, dict) or not all(isinstance(r, list) for r in choices.values()):
        raise CanonError(
            "Choices map each faction to its ranked list: the whole output is refused."
        )
    truth, current = index.search_facts(ws, at=date), _current(ws, at=date)
    used = {r["key"] for r in occurrences(ws)}
    facts = {f["id"] for f in index.search_facts(ws)}  # beliefs too: a faction may cite one
    factions = []
    for faction, ranked in sorted(choices.items()):
        s = {k: f for k, f in current.get(faction, {}).items() if k != AGENDA and _decided(f)}
        catalogue = {a["id"]: a for a in s[CATALOGUE]["state"]["value"]} if CATALOGUE in s else {}
        picked = []
        for choice in ranked:
            if not (
                isinstance(choice, dict)
                and set(choice) == {"action", "cites"}
                and isinstance(choice["action"], str)
                and isinstance(choice["cites"], list)
                and all(isinstance(c, str) for c in choice["cites"])
            ):
                raise CanonError(
                    f"A choice is {{action, cites: [fact ids]}}, not {choice!r}: the whole "
                    "output is refused."
                )
            if unknown := [c for c in choice["cites"] if c not in facts]:
                raise CanonError(
                    f"Cites {unknown} are not canon fact ids: the whole output is refused."
                )
            a, key = catalogue.get(choice["action"]), f"{faction}/{choice['action']}@{date}"
            if a is None:
                raise CanonError(
                    f"{faction} has no action {choice['action']!r} in its catalogue: the whole "
                    "output is refused."
                )
            if key in used:
                raise CanonError(f"Occurrence key {key} is already used.")
            used.add(key)
            picked.append((key, a, choice["cites"]))
        factions.append((faction, s, picked))
    held: dict[str, list[dict]] = {}  # each faction's known or believed facts, read when needed
    lost: dict[str, tuple[str, dict]] = {}  # a contest loser stays lost, with its reason
    seen: dict[str, dict] = {}  # each contest result, by key
    while True:
        verdicts: list[dict[str, Any]] = []
        for faction, s, picked in factions:
            pools = s[POOL]["state"]["value"] if POOL in s else {}
            left = s[CAPACITY]["state"]["value"] if CAPACITY in s else 0
            spent: Counter[str] = Counter()
            for key, a, cites in picked:
                v: dict[str, Any] = {
                    "key": key,
                    "faction": faction,
                    "action": a,
                    "rule": s[CATALOGUE]["id"],
                }
                v |= {"cites": cites, "reason": None, "belief": None, "contest": None}
                verdicts.append(v)
                if key in lost:  # it commits nothing
                    v["reason"], v["contest"] = lost[key]
                    continue
                contested = [a["contest"]["pool"]] if a["contest"] else []
                failed = [p for p in a["prerequisites"] if not any(_meets(p, f) for f in truth)]
                short = {
                    n: c
                    for n, c in a["cost"].items()
                    if spent[n] + c > pools.get(n, {}).get("value", 0)
                }
                if unknown := sorted({*a["cost"], *contested} - set(pools)):
                    v["reason"] = f"no pool {', '.join(unknown)}"
                elif left < 1:
                    v["reason"] = "no capacity left this step"
                elif failed:
                    v["reason"] = f"prerequisite {json.dumps(failed[0])} does not hold on {date}"
                    if faction not in held:
                        held[faction] = _held(ws, faction, date)
                    v["belief"] = next(
                        (f["id"] for f in held[faction] if _meets(failed[0], f)), None
                    )
                elif short:
                    v["reason"] = f"pools cannot cover {json.dumps(short)}"
                else:
                    left -= 1
                    spent.update(a["cost"])
        contests: dict[str, list[dict]] = {}
        for v in verdicts:
            if v["action"]["contest"] and v["reason"] is None:
                contests.setdefault(v["action"]["target"], []).append(v)
        losers: dict[str, tuple[str, dict]] = {}
        for target, rivals in contests.items():
            if len(rivals) < 2:
                continue
            for v in rivals:
                committed = v["action"]["cost"].get(v["action"]["contest"]["pool"], 0)
                v["contest"] = {"target": target, "committed": committed, "roll": roll(v["key"])}
            won = max(
                rivals, key=lambda v: (v["contest"]["committed"], v["contest"]["roll"], v["key"])
            )
            for v in rivals:
                v["contest"]["won"] = v is won
                seen[v["key"]] = v["contest"]
                if v is not won:
                    v["reason"] = f"lost the contest for {target} to {won['key']}"
                    losers[v["key"]] = (v["reason"], v["contest"])
        if not losers:
            for v in verdicts:  # a winner whose rivals all lost keeps the contest it won
                if v["reason"] is None and v["contest"] is None:
                    v["contest"] = seen.get(v["key"])
            return verdicts
        lost |= losers


def _held(ws: Workspace, faction: str, date: str) -> list[dict]:
    """The facts `faction` knows or believes on `date`, its suspicions left out."""
    known = knowledge.known(ws, faction, at=date)
    return [
        f
        for f in index.search_facts(ws)
        if f["id"] in known and known[f["id"]]["mode"] != "suspects"
    ]


def faction_turn(ws: Workspace, date: str, choices: Any, job: int | None = None) -> list[dict]:
    """The factions' turn for the faction step ending on `date`: every faction's ranked
    choices at once (F5 and F6 collect every answer first, since contests happen only inside
    one turn), validated (`validate`) and recorded under their keys `<faction>/<action>@<date>`,
    used once (LW-13), in one journal (ADR 0016). An accepted one is an `action` occurrence
    carrying its `debit`, applied in that journal: the debit on its faction's pool and its
    effect, a fact only its faction learns, never one without the other; a narrative one waits
    queued behind a proposal call (ADR 0022 item 6). After the debits, each faction's income is
    credited up to its caps, a rule effect keyed `<faction>/income@<date>`. A failed one is a
    `failure`, `failed`, with its reason (`validation`), listed in the world-turn report
    (`present`). One failed on a false belief is an offscreen event only its faction learns, a
    derived consequence at the living world's level (ADR 0022 decision c), held behind a
    proposal call at propose. `job`: the started faction-intent job that chose. Refused during
    a live session (LW-05), at manual, after the world-turn cursor, and within one faction step
    of another faction turn. Queues no job. Returns the records, its income ones included."""
    from secondchair.core import jobs  # it builds on canon, which builds on this module

    with locked(ws):
        moment, _ = delegation.current_moment(ws)
        if moment == "live-session":
            raise DelegationError("Factions never act during a live session (LW-05).")
        if delegation.effective_level(ws, "living_world", moment, reversible=True) == "manual":
            raise DelegationError(f"living_world is at manual in {moment}: no faction turn.")
        if job is not None and jobs.read(ws, job)["status"] != "started":
            raise DelegationError(f"Job {job} is not started.")
        _check_recovered(ws)
        cal, date, now = ws.calendar, ws.calendar.canonical(date), cursor(ws)

        def at(d: str) -> int:
            return index.date_key(cal, d)

        if now is None or at(date) > at(now):
            raise DelegationError(f"A faction turn is dated on or before the cursor ({now}).")
        step = f"{faction_step(ws)}d"
        if near := [
            r["key"]
            for r in occurrences(ws)
            if r["kind"] in (ACTION, FAILURE, INCOME)  # income once per step, too
            and at(cal.add(r["date"], step)) > at(date)
            and at(cal.add(date, step)) > at(r["date"])
        ]:
            raise DelegationError(f"One faction turn per step: {near[0]} is within {step}.")
        planned: _Plan = []
        prereqs: list[dict] = []
        overlay: list[Change] = []

        def plan_one(record: dict) -> None:
            try:
                changes = _changes(ws, record, None, overlay)
            except _Blocked as e:
                planned.append((record, None, str(e)))
                return
            overlay.extend(changes)
            planned.append((record, changes, None))

        for v in validate(ws, date, choices):
            a, failed = v["action"], v["reason"] is not None
            prereqs += a["prerequisites"]
            occ = {"key": v["key"], "kind": FAILURE if failed else ACTION}
            occ |= {"class": "derived" if failed else a["effect"]["class"]}
            occ |= {"entity": v["faction"], "date": date, "rule": v["rule"], "job": job}
            occ |= {"cites": v["cites"], "action": a["id"], "target": a["target"]}
            occ |= {"validation": v["reason"] or "ok", "belief": v["belief"]}
            occ |= {"debit": {} if failed else a["cost"], "contest": v["contest"]}
            record = _new(occ)
            if failed and v["belief"] is None:
                planned.append((record | {"status": "failed"}, None, None))
            elif occ["class"] == "narrative":  # new narrative waits for the GM (ADR 0022 item 6)
                planned.append((record, None, None))
            else:
                plan_one(record)
        used = {r["key"] for r in occurrences(ws)}
        # Held at propose, no debit lands now: income is planned on the pools as they stand.
        held = delegation.plan_actions(ws, _effect_tool(), AGENT, [], job) is None
        heads = _current(ws, head=True, overlay=[] if held else overlay)
        for faction, s in sorted(_current(ws, at=date).items()):  # credited after the debits
            pool = heads.get(faction, {}).get(POOL)
            key = f"{faction}/income@{date}"
            if (
                POOL in s
                and _decided(s[POOL])
                and pool is not None
                and _credited(pool["state"]["value"]) != pool["state"]["value"]
                and key not in used
            ):
                occ = {"key": key, "kind": INCOME, "class": "rule", "entity": faction}
                plan_one(_new(occ | {"date": date, "rule": s[POOL]["id"], "job": job}))
        if not planned:
            return []
        applied = [(c, r["key"]) for r, changes, _ in planned for c in changes or []]
        entries = (
            delegation.plan_actions(ws, _effect_tool(), AGENT, applied, job) if applied else []
        )
        if entries is None:  # held at propose whole: each record waits, queued, behind a call
            planned = [(r, None, why) for r, _, why in planned]
        # What the plan read (ADR 0016): every faction's facts and knowledge, and the facts its
        # prerequisites name, so a hand edit to any of them before recovery rolls it back.
        entities, facts, files = list(choices), set(), set()
        for p in prereqs:
            if "holds" in p:
                facts.add(p["holds"])
            else:
                entities.append(p.get("front") or p["situation"])
        for faction in choices:
            known = knowledge.known(ws, faction, at=date)
            facts |= set(known)
            via = sorted({faction, *(k["via"] for k in known.values())})
            files |= {
                f"{index.KNOWLEDGE_DIR}/{k['id']}.md" for k in index.search_knowledge(ws, via)
            }
        _journal(ws, planned[0][0], planned, entries or [], entities, sorted(facts), sorted(files))
        for r, _, why in planned:
            if why is not None:
                _ask(ws, r, "exception", f"{why}; reject it, or accept it once it applies")
            elif r["status"] == "queued" and r["kind"] == INCOME:
                _ask(ws, r, "proposal", "its faction is credited its income; accept or reject it")
            elif r["status"] == "queued" and r["kind"] == FAILURE:
                _ask(ws, r, "proposal", "its faction learns its choice failed; accept or reject it")
            elif r["status"] == "queued":
                _ask(ws, r, "proposal", "its faction acts and pays for it; accept or reject it")
        return [r for r, _, _ in planned]


def _credited(pools: dict) -> dict:
    """A faction's pools after one step's income, each up to its cap (ADR 0022 item 2)."""
    return {n: {**r, "value": min(r["value"] + r["income"], r["cap"])} for n, r in pools.items()}


def _does(ws: Workspace, record: dict) -> str:
    """What a faction's action does, from the catalogue fact it was validated against."""
    [catalogue] = [
        f for f in index.search_facts(ws, include_retconned=True) if f["id"] == record["rule"]
    ]
    [does] = [
        a["effect"]["does"] for a in catalogue["state"]["value"] if a["id"] == record["action"]
    ]
    return does


def _failure(ws: Workspace, record: dict) -> list[Change]:
    """A choice failed on a false belief: an offscreen event on its date opening a fact that
    says so, which its faction alone learns (ADR 0022 decision c)."""
    return _learnt(ws, record, f" failed: {record['validation']}")


def _learnt(ws: Workspace, record: dict, says: str, role: str = "") -> list[Change]:
    """An offscreen event on a faction choice's date opening a fact, `<faction>: <action><says>`,
    which its faction alone learns, at the agent-proposal rank of a derived consequence. File
    ids derive from the key, used once, and `role`."""
    key, faction, date = record["key"], record["entity"], record["date"]
    origin = {"kind": "rule", "fact": record["rule"], "key": key}
    admission.admit(ws, origin, admission.CORE)  # the Core composes it
    rank, names = "agent_proposal", {e["id"]: e["names"][0] for e in index.search_entities(ws)}
    fact_id, event_id = _id("f", key, f"{role}fact"), _id("v", key, f"{role}event")
    k_id = _id("k", key, f"{role}{faction}")
    fact: dict[str, Any] = {"id": fact_id, "entities": [faction], "relation": None}
    fact |= {"valid_from": None, "valid_to": None, "rank": rank, "origin": origin}
    event: dict[str, Any] = {"id": event_id, "date": date, "kind": "offscreen"}
    event |= {"opens": [fact_id], "closes": [], "replaces": None, "rank": rank, "origin": origin}
    learnt: dict[str, Any] = {"id": k_id, "knower": faction, "fact": fact_id, "mode": "knows"}
    learnt |= {"date": date, "event": event_id, "rank": rank, "origin": origin}
    statement = f"{names[faction]}: {record['action']}{says}"
    return [
        Change(f"{index.FACTS_DIR}/{fact_id}.md", index.join_doc(fact, statement), key),
        Change(f"{index.EVENTS_DIR}/{event_id}.md", index.join_doc(event, key), key),
        Change(f"{index.KNOWLEDGE_DIR}/{k_id}.md", index.join_doc(learnt, ""), key),
    ]


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
        if delegation.current_moment(ws)[0] == "live-session":
            raise DelegationError("The world does not move during a live session (LW-05).")
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
            _apply(ws, record, job=job)
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
        if answer not in ("accept", "reject", "reschedule"):
            raise DelegationError(f"Answer {answer!r}: expected accept, reject or reschedule.")
        if answer == "accept" and record["class"] == "narrative" and record["kind"] != ACTION:
            raise DelegationError(
                f"{key} is new narrative: answer its narrative-direction proposal, or reject "
                "or reschedule it."
            )
        if answer == "reschedule":
            if record["kind"] in (FAILURE, ACTION, INCOME):  # it belongs to its faction step
                raise DelegationError(f"{key} belongs to its faction step: accept or reject it.")
            if date is None:
                raise DelegationError("Rescheduling needs the new date.")
            date = ws.calendar.canonical(date)
        if record["call"] is not None:
            calls.close(ws, record["call"])
        if answer == "accept":
            record["call"] = None
            _apply(ws, record, approve=(channel, authenticated))
        elif answer == "reject":
            record["status"] = "rejected"
        else:
            record |= {"status": "rescheduled", "rescheduled_date": date}
            record["rescheduled_to"] = f"{key}~{date}"
        _save(ws, record, OCCURRENCES_DIR)
        return _find(ws, key)


def undoable_alone(ws: Workspace, entry: dict) -> bool:
    """Whether one entry of an occurrence may be undone on its own: only a narrative-direction
    job's, whose last undo returns its occurrence to the queue (LW-19). Every other occurrence
    is undone whole (`undo`), or half of it would stay applied."""
    record = next((r for r in occurrences(ws) if r["key"] == entry["occurrence"]), None)
    return record is None or (record["class"] == "narrative" and record["kind"] != ACTION)


def proposal_answered(ws: Workspace, entry: dict) -> None:
    """Follow the GM's answer to a narrative occurrence's proposal (LW-19): an approved entry
    of its `propose-narrative-direction` job applies it; undoing the last one returns it to the
    queue (LW-12). A rejected proposal leaves it queued. Other occurrences are untouched."""
    record = _find(ws, entry["occurrence"])
    if record["class"] != "narrative":
        return
    if entry["status"] == "applied" and record["status"] in ("queued", "applied"):
        record |= {"status": "applied", "entries": [*record["entries"], entry["id"]]}
    elif entry["status"] == "undone" and entry["id"] in record["entries"]:
        record["entries"].remove(entry["id"])
        if not record["entries"]:
            record["status"] = "queued"
    else:
        return
    _save(ws, record, OCCURRENCES_DIR)


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
        first, faction = min(target["entries"]), target["kind"] in (ACTION, FAILURE, INCOME)

        def built_on(r: dict) -> bool:
            """A later effect on the target's entity; for a faction, only along its pool chain:
            a later debit or income on the pool a debit or an income closed."""
            later = r["entity"] == target["entity"] and min(r["entries"]) > first
            return later and (not faction or (_pooled(target) and _pooled(r)))

        todo = {
            r["key"]: r
            for r in records
            if r["status"] == "applied"
            and r["kind"] not in ("pause", "resume")
            and (r["key"] == key or built_on(r))
        }
        while more := [
            r
            for r in records
            if r["status"] == "applied" and r.get("cause") in todo and r["key"] not in todo
        ]:
            todo |= {r["key"]: r for r in more}
        entries = sorted((e for r in todo.values() for e in r["entries"]), reverse=True)
        moment = delegation.current_moment(ws)[1]
        if any(delegation.read_entry(ws, e)["moment_seq"] != moment for e in entries):
            raise DelegationError(
                f"{key} or its cascade belongs to an earlier moment, whose log is frozen: only a "
                "correction or a retcon can change it now."
            )
        for entry in entries:
            delegation.undo(ws, entry, reason, channel, authenticated, whole=True)
        for r in todo.values():
            r |= {"status": "queued", "entries": []}
            _save(ws, r, OCCURRENCES_DIR)
            if r["kind"] in (ACTION, FAILURE, INCOME):  # back in the queue, it waits on the GM
                _ask(ws, r, "proposal", f"undone ({reason}); accept or reject it")
        return sorted(todo)


def _pooled(record: dict) -> bool:
    """Whether a faction occurrence changes its pool: an income, or a debit."""
    return record["kind"] == INCOME or (record["kind"] == ACTION and any(record["debit"].values()))


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
        admission.admit(ws, origin, admission.CORE)
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
