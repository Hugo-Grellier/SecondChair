"""Who knows what (04-canon-memory-capture.md, CAN-13..16, ADR 0007).

A knower is the party as a whole, an NPC or a faction; a place's knowledge is its common
knowledge. Knowledge is closed-world: a knower knows, believes or suspects only what is recorded
for it, plus what it inherits from the factions it is a member of and the places it lives in
(one level, never from its own members). Content written for an audience cites the facts it uses
and goes through `guard`.
"""

import re
import secrets
from typing import Any

from secondchair.core import index, observations
from secondchair.core.index import KNOWLEDGE_DIR, MODES, PARTY, CanonError
from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import Workspace

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


def _check_seen(ws: Workspace, knower: str, origin: dict[str, str]) -> None:
    """An origin quoting a VTT observation must resolve, and only an observation the whole
    table saw marks a fact as known by the party (ARC-16, CAP-08)."""
    where = origin.get("locator", "")
    if origin.get("kind") != "observation" or not where.startswith(f"{observations.DIR}/"):
        return
    seen = observations.find(ws, where)
    if seen is None:
        raise CanonError(f"No observation at {where}.")
    if knower == PARTY and seen["visibility"] != "players":
        raise CanonError(
            f"The observation {where} is {seen['visibility']}: the table did not see it, so it "
            "never marks a fact as known by the party. Hold it as a call for the wrap."
        )


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
        rank = index.rank_of(origin, authenticated=False)
        if mode not in MODES:
            raise CanonError(f"mode must be one of {', '.join(MODES)}.")
        _check_seen(ws, knower, origin)
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

    return [
        Tool(fn=record_knowledge, responsibility="memory", delegated_action=True, reversible=True),
        Tool(fn=what_knows, responsibility="memory", delegated_action=False, reversible=True),
        Tool(
            fn=check_audience_content,
            responsibility="memory",
            delegated_action=False,
            reversible=True,
        ),
    ]
