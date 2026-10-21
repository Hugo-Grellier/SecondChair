"""Canon in the workspace (04-canon-memory-capture.md): entities (identity only, CAN-02), facts
(CAN-01, CAN-03, CAN-04, CAN-06..08) and events that open and close them, corrections and
retcons (CAN-05). Every write is a delegated action under memory; reads go through the index.
"""

import secrets
from typing import Any

import yaml

from secondchair.core import admission, delegation, index, world
from secondchair.core.index import EVENT_KINDS, EVENTS_DIR, FACTS_DIR, RANKS, CanonError
from secondchair.core.tools import Change, Contradiction, Tool
from secondchair.core.workspace import Workspace

ENTITIES_DIR = index.ENTITIES_DIR


def create_entity(
    names: list[str],
    aliases: list[str] | None = None,
    official_reference: dict[str, str | None] | None = None,
    description: str = "",
    kind: str | None = None,
) -> Change:
    """Create a canon entity: identity only (names, aliases, an optional kind, an optional
    official reference and a player-facing description with no truth value). What is true about
    it is stated by facts. `kind` is pc, npc, faction, place, item or other; a pc is never a
    knower.
    `official_reference` is {"key": the System extension's stable English key (PF2e: system.slug,
    else flags.babele.originalName), "pack": the compendium pack, only when the key collides};
    never the translated name, which goes in `names`."""
    if not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise ValueError("An entity needs at least one non-empty name.")
    entity_id = f"e-{secrets.token_hex(4)}"
    identity = {
        "id": entity_id,
        "names": names,
        "aliases": aliases or [],
        "kind": index.entity_kind(kind),
        "official_reference": (
            None if official_reference is None else index.official_reference(official_reference)
        ),
    }
    front = yaml.safe_dump(identity, sort_keys=False, allow_unicode=True)
    return Change(path=f"{ENTITIES_DIR}/{entity_id}.md", after=f"---\n{front}---\n{description}\n")


def confirm(ws: Workspace, doc_id: str, channel: str, authenticated: bool) -> dict:
    """Promote a fact or event recorded from the GM's words to the GM-decision rank (CAN-09,
    DEL-29): an agent prepared it as an agent proposal, the GM confirms it here. Returns the
    logged GM interaction."""
    found = [
        (FACTS_DIR, d) for d in index.search_facts(ws, include_retconned=True) if d["id"] == doc_id
    ] + [(EVENTS_DIR, d) for d in index.search_events(ws) if d["id"] == doc_id]
    if not found:
        raise CanonError(f"No fact or event {doc_id!r} in canon.")
    [(folder, doc)] = found

    def promote(text: str) -> tuple[str, int | None]:
        front, body = index.split_doc(text)
        if front.get("origin", {}).get("kind") != "gm":
            raise CanonError(f"{doc_id} is not the GM's words; only a decision can be confirmed.")
        if front["rank"] == "gm_decision":
            raise CanonError(f"{doc_id} is already a GM decision.")
        return index.join_doc({**front, "rank": "gm_decision"}, body), doc["admitted_by"]

    return delegation.confirm(ws, f"{folder}/{doc_id}.md", promote, channel, authenticated)


def _outranks(a: str, b: str) -> bool:
    return RANKS.index(a) < RANKS.index(b)


def _source(origin: dict) -> str:
    return " ".join(f"{k}: {v}" for k, v in origin.items())


def tools(ws: Workspace) -> list[Tool]:
    """Canon's delegated actions and reads, bound to the served workspace."""

    def fact_doc(
        fact_id: str,
        statement: str,
        entities: list[str],
        origin: dict[str, str],
        relation: dict[str, str] | None,
        valid_from: str | None,
        valid_to: str | None,
        never_true: bool = False,
        state: dict[str, Any] | None = None,
    ) -> str:
        if not statement.strip():
            raise CanonError("A fact needs a statement in the campaign language.")
        admission.admit(ws, origin)
        rank = index.rank_of(origin, authenticated=False)  # an agent never reaches gm_decision
        known = {e["id"] for e in index.search_entities(ws)}
        involved = list(entities)
        if relation is not None:
            if set(relation) != {"type", "subject", "object"}:
                raise CanonError("A relation has exactly type, subject and object.")
            if relation["type"] not in (types := index.relation_types()):
                raise CanonError(
                    f"Relation type {relation['type']!r} is not in the Core list and no System "
                    f"extension registers it; known: {', '.join(sorted(types))}."
                )
            involved += [relation["subject"], relation["object"]]
        if state is not None:
            state, refs = world.check_state(ws.calendar, state)
            involved += [state["of"], *refs]
        if unknown := [e for e in involved if e not in known]:
            raise CanonError(f"Unknown entities {unknown}; create them first.")
        if never_true and (valid_from or valid_to):
            raise CanonError("A never-true fact (a belief, CAN-15) has no validity dates.")
        dates = {}
        for key, value in (("valid_from", valid_from), ("valid_to", valid_to)):
            dates[key] = ws.calendar.canonical(value, partial=True) if value else None
        front = {
            "id": fact_id,
            "entities": list(dict.fromkeys(involved)),
            "relation": relation,
            **dates,
            "rank": rank,
            "origin": origin,
            **({"never_true": True} if never_true else {}),
            **({"state": state} if state is not None else {}),
        }
        return index.join_doc(front, statement.strip())

    def record_fact(
        statement: str,
        entities: list[str],
        origin: dict[str, str],
        relation: dict[str, str] | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        never_true: bool = False,
        state: dict[str, Any] | None = None,
    ) -> Change:
        """Record a fact: one statement in the campaign language about the given entity ids.
        `origin` is its provenance and sets its rank: {"kind": "observation", "quote", "locator"}
        for what was said or done at the table (played; the quote verbatim, located
        `observations/<session>.jsonl#<id>` or `<file>:<line>` in a Source of your job),
        {"kind": "source", "source", "page", optional "excerpt"} for an indexed page of the
        reference library (cited_source), {"kind": "job", "job"} for your own work, or
        {"kind": "gm", "words"} for the GM's words (an agent proposal until the GM confirms it
        with `secondchair confirm <id>` in a terminal).
        `relation` is optional: {"type", "subject", "object"} with a type from the Core list
        (member_of, leads, lives_in, located_in, owns, knows, allied_with, opposes, serves,
        kin_of) or one a System extension registers. `valid_from` / `valid_to` are campaign
        dates (YYYY-MM-DD, YYYY-MM or YYYY); leave them empty when an event opens or closes it.
        `never_true` records a false statement someone believes (a belief): it has no validity,
        no event opens it, and knowers can only believe or suspect it (record_knowledge).
        `state` makes it a living-world state fact (a front, a situation or a faction, read by
        the world-turn): {"of": entity id, "key": ..., "value": ...} with key and value one of
        "front" {carrier, participants, capacity, every (7d, 1w), ticks, anchor (date),
        unless (text or null), active}, "clock" (an integer), "agenda" {id, when: {date} or
        {clock_gte}, status: pending}, "situation" {stage: available|active|resolved|expired,
        deadline (date or null), participants}; on a faction, "intent" [1-3 {id, goal,
        pursues: [front or situation ids]}], "pool" {name: {value, income, cap}}, "capacity"
        (an integer >= 1) and "catalogue" [{id, cost: {pool: n}, duration, effect: {class:
        derived|narrative, does}, prerequisites: [{holds: fact id} or {front, clock_gte}],
        target (entity id or null), contest ({pool} or null)}], which only the GM writes in
        prep: draft them into notes/ instead. The statement says the same in words.
        The Core looks the origin's evidence up and refuses it when it cannot find it: record
        what it cannot find with a job origin, which may carry the same quote or page."""
        fact_id = f"f-{secrets.token_hex(4)}"
        after = fact_doc(
            fact_id, statement, entities, origin, relation, valid_from, valid_to, never_true, state
        )
        return Change(path=f"{FACTS_DIR}/{fact_id}.md", after=after, source=_source(origin))

    def correct_fact(
        fact: str,
        statement: str,
        entities: list[str],
        origin: dict[str, str],
        relation: dict[str, str] | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        never_true: bool = False,
        state: dict[str, Any] | None = None,
    ) -> Change:
        """Correct a wrongly recorded fact in place, with no event: the arguments are its whole
        new version, as for record_fact. Refused when the fact was played, or ranks above your
        correction: a change to what was played is a retcon, the GM's decision."""
        path = f"{FACTS_DIR}/{fact}.md"
        found = [f for f in index.search_facts(ws, include_retconned=True) if f["id"] == fact]
        if not found:
            raise CanonError(f"No fact {fact!r} in canon.")
        current = found[0]
        admission.admit(ws, origin)
        rank = index.rank_of(origin, authenticated=False)
        if current["rank"] == "played":
            raise Contradiction(path, f"{fact} was played; a correction cannot contradict play.")
        if _outranks(current["rank"], rank):
            raise Contradiction(path, f"{fact} ranks {current['rank']}, above this {rank}.")
        after = fact_doc(
            fact, statement, entities, origin, relation, valid_from, valid_to, never_true, state
        )
        return Change(path=path, after=after, source=_source(origin))

    def record_event(
        description: str,
        date: str,
        origin: dict[str, str],
        kind: str = "offscreen",
        opens: list[str] | None = None,
        closes: list[str] | None = None,
        replaces: str | None = None,
    ) -> Change:
        """Record an event, played at the table or offscreen, on a campaign date: the facts it
        opens start then and the facts it closes end then (an evolution closes the old fact and
        opens the new one). `origin` as for record_fact. A retcon is an event that `replaces` an
        earlier one, which stays on record; it needs the GM's words as origin and takes effect
        once the GM confirms it as a decision."""
        if kind not in EVENT_KINDS:
            raise CanonError(f"kind must be one of {', '.join(EVENT_KINDS)}.")
        if not description.strip():
            raise CanonError("An event needs a description in the campaign language.")
        admission.admit(ws, origin)
        rank = index.rank_of(origin, authenticated=False)
        event_id = f"v-{secrets.token_hex(4)}"
        path = f"{EVENTS_DIR}/{event_id}.md"
        date = ws.calendar.canonical(date, partial=True)
        facts = {f["id"]: f for f in index.search_facts(ws, include_retconned=True)}
        opens, closes = list(opens or []), list(closes or [])
        if unknown := [f for f in opens + closes if f not in facts]:
            raise CanonError(f"Unknown facts {unknown}.")
        if beliefs := [f for f in opens + closes if facts[f]["never_true"]]:
            raise CanonError(f"Facts {beliefs} are never true; no event opens or closes them.")
        if replaces is not None:
            if replaces not in {e["id"] for e in index.search_events(ws)}:
                raise CanonError(f"No event {replaces!r} in canon.")
            if origin.get("kind") != "gm":
                raise CanonError("A retcon is a GM decision: its origin must be the GM's words.")
        for f in (facts[i] for i in closes):
            if _outranks(f["rank"], rank):
                raise Contradiction(
                    path, f"{f['id']} ranks {f['rank']}; this {rank} event cannot close it."
                )
            if f["valid_to"] is not None:
                raise Contradiction(path, f"{f['id']} already ended on {f['valid_to']}.")
            if f["valid_from"] and index.date_key(ws.calendar, f["valid_from"]) > index.date_key(
                ws.calendar, date
            ):
                raise Contradiction(path, f"{f['id']} only starts on {f['valid_from']}.")
        front = {
            "id": event_id,
            "date": date,
            "kind": kind,
            "opens": opens,
            "closes": closes,
            "replaces": replaces,
            "rank": rank,
            "origin": origin,
        }
        return Change(
            path=path, after=index.join_doc(front, description.strip()), source=_source(origin)
        )

    def search_entities(text: str = "") -> list[dict[str, Any]]:
        """Entities whose names or aliases contain every word of `text` (all when empty)."""
        return index.search_entities(ws, text)

    def search_facts(
        text: str = "",
        entity: str | None = None,
        relation: str | None = None,
        at: str | None = None,
        include_retconned: bool = False,
    ) -> list[dict[str, Any]]:
        """Facts matching every word of `text`, about an entity id, of a relation type, and
        valid on the campaign date `at`, with their validity, rank and provenance. Facts undone
        by a retcon are left out unless `include_retconned`."""
        return index.search_facts(ws, text, entity, relation, at, include_retconned)

    def search_events(text: str = "", fact: str | None = None) -> list[dict[str, Any]]:
        """Events whose description contains every word of `text`, or that open or close the
        fact id `fact`, with their status (canon, replaced, pending_retcon)."""
        return index.search_events(ws, text, fact)

    def write(fn: Any) -> Tool:
        return Tool(fn=fn, responsibility="memory", delegated_action=True, reversible=True)

    def read(fn: Any) -> Tool:
        return Tool(fn=fn, responsibility="memory", delegated_action=False, reversible=True)

    return [
        write(create_entity),
        write(record_fact),
        write(correct_fact),
        write(record_event),
        read(search_entities),
        read(search_facts),
        read(search_events),
    ]


def vocabulary(ws: Workspace, entities: list[str] | None = None) -> list[str]:
    """The campaign vocabulary (CAN-22), sorted: the names and aliases of the given entity ids,
    or of every entity."""
    found = index.search_entities(ws)
    if entities is not None:
        if unknown := sorted(set(entities) - {e["id"] for e in found}):
            raise CanonError(f"Unknown entities {unknown}.")
        found = [e for e in found if e["id"] in entities]
    return sorted({w for e in found for w in e["names"] + e["aliases"]})
