"""The derived canon index (CAN-10, CAN-12): SQLite in `.secondchair/`, rebuilt from the
workspace's Markdown + YAML and its action log whenever they change. Deleting it loses nothing.

Search is structured plus full text (FTS5); no embeddings in v4.
"""

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from importlib.metadata import entry_points
from typing import Any

import yaml

from secondchair.core import delegation
from secondchair.core.calendar import Calendar, CalendarError
from secondchair.core.workspace import STATE_DIR, Workspace, WorkspaceError

ENTITIES_DIR = "canon/entities"
FACTS_DIR = "canon/facts"
EVENTS_DIR = "canon/events"
KNOWLEDGE_DIR = "canon/knowledge"
LOG_DIR = "action-log"
INDEX_FILE = "index.sqlite"

RANKS = ("played", "gm_decision", "cited_source", "agent_proposal")  # CAN-06, highest first
# CAN-03: the Core's closed relation list; System extensions add to it through this group.
CORE_RELATIONS = (
    "member_of",
    "leads",
    "lives_in",
    "located_in",
    "owns",
    "knows",
    "allied_with",
    "opposes",
    "serves",
    "kin_of",
)
RELATIONS_GROUP = "secondchair.relations"
# CAN-07: what each origin must carry.
ORIGIN_KEYS = {
    "observation": ("quote", "locator"),
    "gm": ("words",),
    "source": ("source", "page"),
    "job": ("job",),
    "rule": ("fact", "key"),  # a world-turn effect: the rule fact and its occurrence key
}
EVENT_KINDS = ("played", "offscreen")
# CAN-13, CAN-14: the party as a whole is a knower with this reserved id; every other knower is
# an entity (an NPC, a faction, or a place whose knowledge is its common knowledge).
PARTY = "party"
MODES = ("knows", "believes", "suspects")  # strongest first

_SCHEMA = """
create table meta(key text primary key, value text);
create table entities(id text primary key, names text, aliases text, official_reference text,
                      description text);
create table facts(id text primary key, statement text, entities text, relation text,
                   relation_type text, valid_from text, valid_to text, from_key int, to_key int,
                   rank text, origin text, status text, admitted_by int, never_true int,
                   state text);
create table fact_entities(fact text, entity text);
create table events(id text primary key, date text, kind text, description text, opens text,
                    closes text, replaces text, replaced_by text, status text, rank text,
                    origin text, admitted_by int);
create table knowledge(id text primary key, knower text, fact text, mode text, date text,
                       date_key int, event text, rank text, origin text, admitted_by int);
create virtual table entities_fts using fts5(id unindexed, names);
create virtual table facts_fts using fts5(id unindexed, statement);
create virtual table events_fts using fts5(id unindexed, description);
"""


class CanonError(ValueError):
    """A canon document or argument the Core cannot accept, with a message for the GM."""


def relation_types() -> set[str]:
    types = set(CORE_RELATIONS)
    for ep in entry_points(group=RELATIONS_GROUP):
        types.update(ep.load())
    return types


def rank_of(origin: Any, authenticated: bool) -> str:
    """The authority rank an origin gives (CAN-06..08, ADR 0008): a table quote is played, a
    cited Source is cited_source, the GM's words are a GM decision only from an authenticated
    Surface (DEL-29), anything else is an agent proposal."""
    if not isinstance(origin, dict) or origin.get("kind") not in ORIGIN_KEYS:
        raise CanonError(f"origin needs a kind among {', '.join(ORIGIN_KEYS)}.")
    if origin["kind"] == "rule" and not authenticated:
        raise CanonError("Only the world-turn writes a rule effect; cite your own origin.")
    for key in ORIGIN_KEYS[origin["kind"]]:
        if not (isinstance(origin.get(key), str) and origin[key].strip()):
            raise CanonError(f"A {origin['kind']} origin needs a non-empty {key!r}.")
    return {
        "observation": "played",
        "source": "cited_source",
        "gm": "gm_decision" if authenticated else "agent_proposal",
    }.get(origin["kind"], "agent_proposal")


def date_key(calendar: Calendar, value: str) -> int:
    """A sortable integer for a (partial) date; a partial date sorts at the start of its period."""
    year, month, day = calendar.parse(value, partial=True)
    return year * 10000 + month * 100 + day


def split_doc(text: str) -> tuple[dict, str]:
    """YAML front matter and body of a canon document."""
    if not text.startswith("---\n") or text.count("---\n") < 2:
        raise CanonError("expected YAML front matter between --- lines")
    _, front, body = text.split("---\n", 2)
    data = yaml.safe_load(front)
    if not isinstance(data, dict):
        raise CanonError("the front matter must be a YAML mapping")
    return data, body.removesuffix("\n")


def join_doc(front: dict, body: str) -> str:
    return f"---\n{yaml.safe_dump(front, sort_keys=False, allow_unicode=True)}---\n{body}\n"


# The index file


def connect(ws: Workspace) -> sqlite3.Connection:
    """A connection to an up-to-date index, rebuilt first if the workspace changed."""
    path = ws.root / STATE_DIR / INDEX_FILE
    stamp = _fingerprint(ws)
    if path.exists():
        conn = sqlite3.connect(path)
        try:
            row = conn.execute("select value from meta where key = 'fingerprint'").fetchone()
        except sqlite3.DatabaseError:
            row = None
        if row and row[0] == stamp:
            return conn
        conn.close()
    rebuild(ws)
    return sqlite3.connect(path)


def rebuild(ws: Workspace) -> list[str]:
    """Rebuild the index from the workspace, first logging any hand edit (CAN-11); one message
    per invalid file, which is skipped."""
    with delegation.locked(ws):  # no Core write lands half-logged while we look
        try:
            delegation.log_hand_edits(ws)
            errors = []
        except WorkspaceError as e:  # a broken moment.yaml; check names it
            errors = [str(e)]
        stamp = _fingerprint(ws)
        docs, load_errors = _load(ws)
    path = ws.root / STATE_DIR / INDEX_FILE
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_name(f"{INDEX_FILE}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(tmp)) as conn, conn:
        conn.executescript(_SCHEMA)
        _fill(ws.calendar, conn, *docs)
        conn.execute("insert into meta values ('fingerprint', ?)", (stamp,))
    tmp.replace(path)  # readers never see a half-built index
    return errors + load_errors


def _fingerprint(ws: Workspace) -> str:
    # ponytail: hashes every canon and log file on each query; mtimes if campaigns grow large.
    digest = hashlib.sha256((ws.root / "workspace.yaml").read_bytes())
    digest.update(_SCHEMA.encode())  # a newer Core with new columns rebuilds the index
    for top in ("canon", LOG_DIR):
        for p in sorted((ws.root / top).rglob("*")):
            if p.is_file():
                digest.update(p.relative_to(ws.root).as_posix().encode() + b"\0")
                digest.update(hashlib.sha256(p.read_bytes()).digest())
    return digest.hexdigest()


# Loading and validating documents


def _load(ws: Workspace) -> tuple[tuple[dict, dict, dict, dict], list[str]]:
    errors: list[str] = []
    admitted = _admitted(delegation.read_log(ws)[0])
    relations = relation_types()
    loaded: list[dict] = []
    for folder, check in (
        (ENTITIES_DIR, _entity),
        (FACTS_DIR, lambda d, b: _fact(ws.calendar, relations, d, b)),
        (EVENTS_DIR, lambda d, b: _event(ws.calendar, d, b)),
        (KNOWLEDGE_DIR, lambda d, b: _knowledge(ws.calendar, d)),
    ):
        found: dict[str, dict] = {}
        for p in sorted((ws.root / folder).glob("*.md")):
            relative = p.relative_to(ws.root).as_posix()
            try:
                text = p.read_text()
                doc = check(*split_doc(text))
                if doc["id"] != p.stem:
                    raise CanonError(f"id {doc['id']!r} does not match the file name")
            except (CanonError, CalendarError, yaml.YAMLError, KeyError, TypeError) as e:
                errors.append(f"{relative}: {e}")
                continue
            # The entry that wrote this very content. A hand edit ranks agent_proposal, or
            # gm_decision once promoted, whatever its front matter claims (CAN-11).
            doc["admitted_by"], hand_rank = admitted.get((relative, text), (None, None))
            if hand_rank and "rank" in doc:
                doc["rank"] = hand_rank
            found[doc["id"]] = doc
        loaded.append(found)
    entities, facts, events, knowledge = loaded
    for f in facts.values():
        for e in f["entities"]:
            if e not in entities:
                errors.append(f"{FACTS_DIR}/{f['id']}.md: unknown entity {e!r}")
    for ev in events.values():
        for key, among in (("opens", facts), ("closes", facts), ("replaces", events)):
            ids = ev[key] if isinstance(ev[key], list) else [ev[key]] if ev[key] else []
            for i in ids:
                if i not in among:
                    errors.append(f"{EVENTS_DIR}/{ev['id']}.md: {key} unknown {i!r}")
                elif key != "replaces" and among[i].get("never_true"):
                    errors.append(f"{EVENTS_DIR}/{ev['id']}.md: {i} is never true")
    for k in list(knowledge.values()):
        problem = knowledge_problem(k, entities, facts, events)
        if problem:
            errors.append(f"{KNOWLEDGE_DIR}/{k['id']}.md: {problem}")
            del knowledge[k["id"]]
    return (entities, facts, events, knowledge), errors


def knowledge_problem(k: dict, entities: dict, facts: dict, events: dict) -> str | None:
    """Why a knowledge record cannot stand against canon, or None (CAN-13..15)."""
    if k["knower"] != PARTY and k["knower"] not in entities:
        return f"knower {k['knower']!r} is neither {PARTY!r} nor an entity"
    if k["fact"] not in facts:
        return f"unknown fact {k['fact']!r}"
    if k.get("event") is not None and k["event"] not in events:
        return f"unknown event {k['event']!r}"
    if k["mode"] == "knows" and facts[k["fact"]].get("never_true"):
        return f"{k['fact']} is never true: it can be believed or suspected, not known"
    return None


def _admitted(entries: list[dict]) -> dict[tuple, tuple[int, str | None]]:
    """(target, content) -> the last entry that wrote it, and the rank a hand edit gives it."""
    found = {}
    for entry in entries:
        if entry.get("after") and (
            entry.get("status") == "applied"
            or entry.get("kind") == "hand_edit"
            or entry.get("interaction") == "confirm"
        ):
            found[(entry.get("target"), entry["after"])] = (entry["id"], entry.get("rank"))
    return found


def _strings(value: Any, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise CanonError(f"{what} must be a list of non-empty strings")
    return value


def _entity(front: dict, body: str) -> dict:
    _strings(front["names"], "names")
    _strings(front.get("aliases") or [], "aliases")
    if front.get("official_reference") is not None:
        official_reference(front["official_reference"])
    return {**front, "description": body}


def official_reference(value: Any) -> dict:
    """An official reference (CAN-19) as stored: the System extension's stable English key, plus
    its pack only when the key collides across packs, never the translated name."""
    if not isinstance(value, dict) or not set(value) <= {"key", "pack"}:
        raise CanonError("official_reference has a key and, on a collision, a pack; nothing else")
    key, pack = value.get("key"), value.get("pack")
    # ponytail: an ASCII slug-or-name check; a translation that happens to be ASCII gets through.
    if not isinstance(key, str) or not key.strip() or not key.isascii():
        raise CanonError(
            "official_reference key must be the System extension's stable English key (PF2e: "
            "system.slug, else flags.babele.originalName), never the translated name"
        )
    if pack is not None and (not isinstance(pack, str) or not pack.strip()):
        raise CanonError("official_reference pack must be a compendium pack id, or null")
    return {"key": key, "pack": pack}


def _fact(calendar: Calendar, relations: set[str], front: dict, body: str) -> dict:
    if not body.strip():
        raise CanonError("a fact needs a statement")
    _strings(front["entities"], "entities")
    relation = front.get("relation")
    if relation is not None:
        if not isinstance(relation, dict) or set(relation) != {"type", "subject", "object"}:
            raise CanonError("relation must have exactly type, subject and object")
        if relation["type"] not in relations:
            raise CanonError(
                f"relation type {relation['type']!r} is not in the Core list or registered by a "
                f"System extension ({', '.join(sorted(relations))})"
            )
    for key in ("valid_from", "valid_to"):
        if front.get(key) is not None:
            calendar.parse(front[key], partial=True)
    if front.get("rank") not in RANKS:
        raise CanonError(f"rank must be one of {', '.join(RANKS)}")
    rank_of(front["origin"], authenticated=True)
    if front.get("never_true", False) not in (True, False):
        raise CanonError("never_true must be true or false")
    if front.get("never_true") and (front.get("valid_from") or front.get("valid_to")):
        raise CanonError("a never-true fact (a belief, CAN-15) has no validity")
    state = front.get("state")
    if state is not None and (
        not isinstance(state, dict)
        or set(state) != {"of", "key", "value"}
        or state["of"] not in front["entities"]
    ):
        raise CanonError("state must have exactly of (one of its entities), key and value")
    return {**front, "statement": body}


def _event(calendar: Calendar, front: dict, body: str) -> dict:
    if not body.strip():
        raise CanonError("an event needs a description")
    calendar.parse(front["date"], partial=True)
    if front.get("kind") not in EVENT_KINDS:
        raise CanonError(f"kind must be one of {', '.join(EVENT_KINDS)}")
    _strings(front["opens"], "opens")
    _strings(front["closes"], "closes")
    if front.get("rank") not in RANKS:
        raise CanonError(f"rank must be one of {', '.join(RANKS)}")
    rank_of(front["origin"], authenticated=True)
    return {**front, "description": body}


def _knowledge(calendar: Calendar, front: dict) -> dict:
    if not isinstance(front["knower"], str) or not isinstance(front["fact"], str):
        raise CanonError("knower and fact must be ids")
    if front.get("mode") not in MODES:
        raise CanonError(f"mode must be one of {', '.join(MODES)}")
    calendar.parse(front["date"], partial=True)
    if front.get("rank") not in RANKS:
        raise CanonError(f"rank must be one of {', '.join(RANKS)}")
    rank_of(front["origin"], authenticated=True)
    return front


# Deriving validity from events (CAN-04, CAN-05)


def _fill(calendar: Calendar, conn: sqlite3.Connection, entities, facts, events, knowledge) -> None:
    # A retcon takes effect only at the GM-decision rank (CAN-05, CAN-09); below that it stays
    # on record, awaiting the GM's confirmation (#38).
    replaced_by = {
        ev["replaces"]: ev["id"]
        for ev in sorted(events.values(), key=lambda ev: ev["id"])
        if ev.get("replaces") in events and ev["rank"] == "gm_decision"
    }
    status = {}
    for ev in events.values():
        if ev["id"] in replaced_by:
            status[ev["id"]] = "replaced"
        elif ev.get("replaces") and ev["rank"] != "gm_decision":
            status[ev["id"]] = "pending_retcon"
        else:
            status[ev["id"]] = "canon"
    active = [ev for ev in events.values() if status[ev["id"]] == "canon"]

    def first(dates: list[str]) -> str | None:
        return min(dates, key=lambda d: date_key(calendar, d)) if dates else None

    for e in entities.values():
        names = e["names"] + (e.get("aliases") or [])
        conn.execute(
            "insert into entities values (?, ?, ?, ?, ?)",
            (
                e["id"],
                json.dumps(e["names"]),
                json.dumps(e.get("aliases") or []),
                json.dumps(e.get("official_reference")),
                e["description"],
            ),
        )
        conn.execute("insert into entities_fts values (?, ?)", (e["id"], " ".join(names)))
    for f in facts.values():
        openers = [ev for ev in events.values() if f["id"] in ev["opens"]]
        start = first([ev["date"] for ev in active if f["id"] in ev["opens"]])
        end = first([ev["date"] for ev in active if f["id"] in ev["closes"]])
        fact_status = "canon"
        if openers and start is None:
            replaced = any(status[ev["id"]] == "replaced" for ev in openers)
            fact_status = "retconned" if replaced else "pending_retcon"
        start = start or f.get("valid_from")
        end = end or f.get("valid_to")
        relation = f.get("relation")
        involved = list(
            dict.fromkeys(
                f["entities"] + ([relation["subject"], relation["object"]] if relation else [])
            )
        )
        conn.execute(
            "insert into facts values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f["id"],
                f["statement"],
                json.dumps(involved),
                json.dumps(relation),
                relation and relation["type"],
                start,
                end,
                start and date_key(calendar, start),
                end and date_key(calendar, end),
                f["rank"],
                json.dumps(f["origin"]),
                fact_status,
                f["admitted_by"],
                bool(f.get("never_true")),
                json.dumps(f.get("state")),
            ),
        )
        conn.executemany(
            "insert into fact_entities values (?, ?)", [(f["id"], e) for e in involved]
        )
        conn.execute("insert into facts_fts values (?, ?)", (f["id"], f["statement"]))
    for ev in events.values():
        conn.execute(
            "insert into events values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ev["id"],
                ev["date"],
                ev["kind"],
                ev["description"],
                json.dumps(ev["opens"]),
                json.dumps(ev["closes"]),
                ev.get("replaces"),
                replaced_by.get(ev["id"]),
                status[ev["id"]],
                ev["rank"],
                json.dumps(ev["origin"]),
                ev["admitted_by"],
            ),
        )
        conn.execute("insert into events_fts values (?, ?)", (ev["id"], ev["description"]))
    for k in knowledge.values():
        conn.execute(
            "insert into knowledge values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                k["id"],
                k["knower"],
                k["fact"],
                k["mode"],
                k["date"],
                date_key(calendar, k["date"]),
                k.get("event"),
                k["rank"],
                json.dumps(k["origin"]),
                k["admitted_by"],
            ),
        )


# Queries


def _match(text: str) -> str:
    """Every word must appear; words are quoted so no FTS syntax reaches SQLite."""
    return " ".join('"' + w.replace('"', '""') + '"' for w in text.split())


def _rows(conn: sqlite3.Connection, sql: str, args: list) -> list[dict]:
    with closing(conn), closing(conn.execute(sql, args)) as cur:
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _decode(row: dict, *keys: str) -> dict:
    # A null from an index built before a column held JSON decodes to None.
    return {**row, **{k: None if row[k] is None else json.loads(row[k]) for k in keys}}


def search_entities(ws: Workspace, text: str = "") -> list[dict]:
    sql, args = "select e.* from entities e", []
    if text.strip():
        sql += " join entities_fts t on t.id = e.id where entities_fts match ?"
        args.append(_match(text))
    rows = _rows(connect(ws), sql + " order by e.id", args)
    return [_decode(r, "names", "aliases", "official_reference") for r in rows]


def search_facts(
    ws: Workspace,
    text: str = "",
    entity: str | None = None,
    relation: str | None = None,
    at: str | None = None,
    include_retconned: bool = False,
) -> list[dict]:
    where, args = [], []
    sql = "select f.* from facts f"
    if text.strip():
        sql += " join facts_fts t on t.id = f.id"
        where.append("facts_fts match ?")
        args.append(_match(text))
    if entity:
        where.append("f.id in (select fact from fact_entities where entity = ?)")
        args.append(entity)
    if relation:
        where.append("f.relation_type = ?")
        args.append(relation)
    if at:
        key = date_key(ws.calendar, at)
        where.append(
            "(f.from_key is null or f.from_key <= ?) and (f.to_key is null or f.to_key > ?)"
        )
        args += [key, key]
        where.append("not f.never_true")  # a belief is never valid (CAN-15)
    if not include_retconned:
        where.append("f.status = 'canon'")
    if where:
        sql += " where " + " and ".join(where)
    rows = _rows(connect(ws), sql + " order by f.id", args)
    return [
        {
            **{
                k: v
                for k, v in _decode(r, "entities", "relation", "origin", "state").items()
                if k not in ("from_key", "to_key", "relation_type")
            },
            "never_true": bool(r["never_true"]),
        }
        for r in rows
    ]


def search_events(ws: Workspace, text: str = "", fact: str | None = None) -> list[dict]:
    where, args = [], []
    sql = "select e.* from events e"
    if text.strip():
        sql += " join events_fts t on t.id = e.id"
        where.append("events_fts match ?")
        args.append(_match(text))
    if fact:
        where.append(
            "(exists (select 1 from json_each(e.opens) where value = ?)"
            " or exists (select 1 from json_each(e.closes) where value = ?))"
        )
        args += [fact, fact]
    if where:
        sql += " where " + " and ".join(where)
    rows = _rows(connect(ws), sql + " order by e.id", args)
    return [_decode(r, "opens", "closes", "origin") for r in rows]


def counts(ws: Workspace) -> tuple[int, int, int]:
    with closing(connect(ws)) as conn:
        return tuple(
            conn.execute(f"select count(*) from {t}").fetchone()[0]
            for t in ("entities", "facts", "events")
        )


def search_knowledge(ws: Workspace, knowers: list[str], at: str | None = None) -> list[dict]:
    """Knowledge records of the given knowers about canon facts, learned on or before `at`."""
    marks = ", ".join("?" * len(knowers))
    sql = (
        "select k.*, f.statement, f.never_true from knowledge k join facts f on f.id = k.fact"
        f" where f.status = 'canon' and k.knower in ({marks})"
    )
    args: list = list(knowers)
    if at:
        sql += " and k.date_key <= ?"
        args.append(date_key(ws.calendar, at))
    rows = _rows(connect(ws), sql + " order by k.date_key, k.id", args)
    return [{**_decode(r, "origin"), "never_true": bool(r["never_true"])} for r in rows]
