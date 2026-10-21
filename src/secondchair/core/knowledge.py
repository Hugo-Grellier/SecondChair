"""Who knows what (04-canon-memory-capture.md, CAN-13..16, ADR 0007).

A knower is the party as a whole, an NPC or a faction; a place's knowledge is its common
knowledge. Knowledge is closed-world: a knower knows, believes or suspects only what is recorded
for it, plus what it inherits from the factions it is a member of and the places it lives in
(one level, never from its own members). Content written for an audience cites the facts it uses
and goes through `guard`.
"""

import json
import re
import secrets
from typing import Any

from secondchair.core import admission, index
from secondchair.core.index import KNOWLEDGE_DIR, MODES, PARTY, CanonError
from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import STATE_DIR, Workspace

CUE_FILE = f"{STATE_DIR}/cue.json"  # the active acting cue, derived state (DEL-15)
# BEN-07's canary format; a canary is an inert marker no audience may ever receive.
CANARY = re.compile(r"CANARY-[A-Za-z0-9]+-\d+")
INHERITED = ("member_of", "lives_in")  # a faction's knowledge, a place's common knowledge


class AudienceRefused(CanonError):
    """Audience content the Core refuses (CAN-16), every reason in the message."""


def known(ws: Workspace, knower: str, at: str | None = None) -> dict[str, dict[str, Any]]:
    """Fact id -> how `knower` holds it on campaign date `at` (any time when empty): its
    strongest mode, the knower it holds it through (itself, a faction or a place) and when it
    learned it."""
    sources = [knower]
    if knower != PARTY:
        for relation in INHERITED:
            sources += [
                f["relation"]["object"]
                for f in index.search_facts(ws, entity=knower, relation=relation, at=at)
                if f["relation"]["subject"] == knower and not f["never_true"]
            ]
    held: dict[str, dict[str, Any]] = {}
    for k in index.search_knowledge(ws, sources, at):
        mine = held.get(k["fact"])
        if mine is None or MODES.index(k["mode"]) < MODES.index(mine["mode"]):
            held[k["fact"]] = {
                "mode": k["mode"],
                "via": k["knower"],
                "date": k["date"],
                "event": k["event"],
                "statement": k["statement"],
                "never_true": k["never_true"],
            }
    return held


def guard(
    ws: Workspace, audience: str, text: str, cites: list[str], at: str | None = None
) -> dict[str, str]:
    """Check content written for `audience` (CAN-16): every cited fact exists and the audience
    holds it, and the text carries no canary and no entity name the audience holds no fact
    about by that name (its own names excepted). Returns cited fact -> mode, or raises
    `AudienceRefused` with every reason. Paraphrased leaks are not caught; the bench measures
    them."""
    if audience != PARTY and audience not in {e["id"] for e in index.search_entities(ws)}:
        raise CanonError(f"Audience {audience!r} is neither {PARTY!r} nor an entity.")
    canon_ids = {f["id"] for f in index.search_facts(ws)}
    holds = known(ws, audience, at)
    reasons = []
    if unknown := [c for c in cites if c not in canon_ids]:
        reasons.append(f"unknown fact ids {unknown}")
    if unheld := [c for c in cites if c in canon_ids and c not in holds]:
        reasons.append(f"{audience} does not know {unheld}")
    if canaries := sorted(set(CANARY.findall(text))):
        reasons.append(f"canary markers {canaries}")
    said = " ".join(h["statement"] for h in holds.values())
    secret = sorted(
        {
            name
            for e in index.search_entities(ws)
            if e["id"] != audience
            for name in e["names"] + e["aliases"]
            if _mentions(text, name) and not _mentions(said, name)
        }
    )
    if secret:
        reasons.append(f"names {audience} holds no fact about: {secret}")
    if reasons:
        raise AudienceRefused(f"Content for {audience} refused: {'; '.join(reasons)}.")
    return {c: holds[c]["mode"] for c in cites}


def show_cue(
    ws: Workspace,
    npc: str,
    goal: str,
    line: str,
    cites: list[str],
    knows: list[str] | None = None,
    does_not_know: list[str] | None = None,
    posture: str | None = None,
) -> dict[str, Any]:
    """Make `npc`'s acting cue the active one the Director's Desk shows (DEL-15, ARC-14): its
    line goes through `guard` (CAN-16), every fact it knows must be held, every fact it does not
    know must not be. `posture` is GM-only direction, never audience content, so it skips `guard`.
    A read: it is shown whatever the NPC's level, manual included."""
    names = {e["id"]: e["names"] for e in index.search_entities(ws)}
    if npc not in names:
        raise CanonError(f"No NPC {npc!r} in canon.")
    modes = guard(ws, npc, line, cites)
    holds = known(ws, npc)
    facts = {f["id"]: f for f in index.search_facts(ws)}
    extra = [k for k in knows or [] if k not in modes]
    if unknown := [f for f in [*extra, *(does_not_know or [])] if f not in facts]:
        raise CanonError(f"Unknown fact ids {unknown}.")
    if unheld := [k for k in extra if k not in holds]:
        raise CanonError(f"{npc} does not know {unheld}.")
    if held := [f for f in does_not_know or [] if f in holds]:
        raise CanonError(f"{npc} knows {held}: it cannot be among what it does not know.")
    cue = {
        "npc": npc,
        "name": (names[npc] or [npc])[0],
        "goal": goal,
        "line": line,
        "knows": [
            {"id": f, "statement": holds[f]["statement"], "mode": holds[f]["mode"]}
            for f in dict.fromkeys([*cites, *extra])
        ],
        "does_not_know": [
            {"id": f, "statement": facts[f]["statement"]}
            for f in dict.fromkeys(does_not_know or [])
        ],
    }
    if posture:
        cue["posture"] = posture
    # ponytail: one active cue in derived state, replaced by the next and kept until then (a
    # stale NPC id included); a cue per NPC, cleared at the end of a moment, if needed.
    written = ws.root / f"{CUE_FILE}.{secrets.token_hex(4)}"  # never read half written
    written.write_text(json.dumps(cue, ensure_ascii=False))
    written.replace(ws.root / CUE_FILE)
    return cue


def active_cue(ws: Workspace) -> dict[str, Any] | None:
    """The acting cue last shown, if any; none when its derived file is unreadable."""
    try:
        return json.loads((ws.root / CUE_FILE).read_text())
    except OSError, ValueError:
        return None


def _mentions(text: str, name: str) -> bool:
    # ponytail: exact, case-sensitive whole-word match; inflected or misspelt names slip through.
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def tools(ws: Workspace) -> list[Tool]:
    """Knowledge's delegated action and reads, bound to the served workspace."""

    def record_knowledge(
        knower: str,
        fact: str,
        origin: dict[str, str],
        mode: str = "knows",
        date: str | None = None,
        event: str | None = None,
    ) -> Change:
        """Record that a knower knows, believes or suspects a fact (`mode`), learned on the
        campaign date `date` or at the event id `event` (its date when `date` is empty).
        `knower` is "party" for the party as a whole (never one PC), or the entity id of an NPC,
        a faction, or a place: a place's knowledge is the common knowledge of everyone living
        there, a faction's is inherited by its members. A never-true fact (a belief) can only be
        believed or suspected. `origin` as for record_fact; an observation captured from the
        VTT is located `observations/<session>.jsonl#<id>`, and only one the whole table saw
        (visibility players) can make the party know a fact."""
        admission.admit(ws, origin, knower=knower)  # ARC-16, CAP-08: only what the table saw
        rank = index.rank_of(origin, authenticated=False)
        if mode not in MODES:
            raise CanonError(f"mode must be one of {', '.join(MODES)}.")
        entities = {e["id"]: e for e in index.search_entities(ws)}
        facts = {f["id"]: f for f in index.search_facts(ws, include_retconned=True)}
        events = {e["id"]: e for e in index.search_events(ws)}
        if date is None:
            if event not in events:
                raise CanonError("Give the date the knower learned it, or a known event id.")
            date = events[event]["date"]
        record = {"knower": knower, "fact": fact, "mode": mode, "event": event}
        if problem := index.knowledge_problem(record, entities, facts, events):
            raise CanonError(problem)
        held = index.search_knowledge(ws, [knower])
        if any(k["fact"] == fact and k["mode"] == mode for k in held):
            raise CanonError(f"{knower} already {mode} {fact}.")
        knowledge_id = f"k-{secrets.token_hex(4)}"
        front = {
            "id": knowledge_id,
            "knower": knower,
            "fact": fact,
            "mode": mode,
            "date": ws.calendar.canonical(date, partial=True),
            "event": event,
            "rank": rank,
            "origin": origin,
        }
        return Change(
            path=f"{KNOWLEDGE_DIR}/{knowledge_id}.md",
            after=index.join_doc(front, ""),
            source=" ".join(f"{k}: {v}" for k, v in origin.items()),
        )

    def what_knows(knower: str, at: str | None = None) -> dict[str, dict[str, Any]]:
        """The facts `knower` ("party" or an entity id) knows, believes or suspects on the
        campaign date `at` (ever, when empty), each with its mode, the knower it holds it
        through (itself, one of its factions, or a place it lives in) and when it learned it."""
        return known(ws, knower, at)

    def check_audience_content(
        audience: str, text: str, cites: list[str], at: str | None = None
    ) -> dict[str, str]:
        """Check content before it reaches an audience ("party" or an NPC's entity id): an NPC
        line in an acting cue, a disclosure, an entity description. It must cite the ids of the
        facts it uses. Refused when a cited id is unknown, the audience does not hold a cited
        fact, or the text carries a canary or a name the audience holds no fact about. Returns
        the mode each cited fact is held in, so a belief is never voiced as established truth."""
        return guard(ws, audience, text, cites, at)

    def show_acting_cue(
        npc: str,
        goal: str,
        line: str,
        cites: list[str],
        knows: list[str] | None = None,
        does_not_know: list[str] | None = None,
        posture: str | None = None,
    ) -> dict[str, Any]:
        """Show the GM, on the Director's Desk, what they need to voice the NPC `npc` (its
        entity id) right now: its `goal`, a `line` it could say, written in the campaign
        language and citing in `cites` the ids of the facts it uses, the ids of further facts it
        `knows` and of facts it `does_not_know` that the GM must not let slip. Refused when the
        line fails the audience check (as for check_audience_content), a fact it knows is not
        held by the NPC, or a fact it does not know is. `posture`, optional, is a few words on the
        NPC's emotional state: GM-only direction shown under the goal, never audience content, so
        it is not checked as a line. It replaces the active cue and is shown
        whatever the NPC's delegation level, since it is a read."""
        return show_cue(ws, npc, goal, line, cites, knows, does_not_know, posture)

    return [
        Tool(fn=show_acting_cue, responsibility="npcs", delegated_action=False, reversible=True),
        Tool(fn=record_knowledge, responsibility="memory", delegated_action=True, reversible=True),
        Tool(fn=what_knows, responsibility="memory", delegated_action=False, reversible=True),
        Tool(
            fn=check_audience_content,
            responsibility="memory",
            delegated_action=False,
            reversible=True,
        ),
    ]
