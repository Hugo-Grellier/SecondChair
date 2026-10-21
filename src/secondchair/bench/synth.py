"""The synthetic campaign generator (#195, docs/research/long-campaign-scaling.md): a seeded,
deterministic, fictional multi-session campaign written through the Core's own APIs (canon,
knowledge, sessions, the world-turn and the action log), so every invariant runs on the way in.

The setting is original (LIC-13): an inline calendar and invented names. The generator keeps its
own model of the truth (relationship histories, retcons, secrets and when the party learned them,
promises, rumours, fronts) and emits from it a gold set of temporal questions with their expected
answers, in the GM's view and in the party's. The recall bench (`recall.py`) scores the Core's
query functions against that gold set; the gold set is generated, so it is a tracked track and
not a MET-02 reference gold set.

Determinism: ids come from a counter, the clock from a fixed tick, every choice from one seeded
`random.Random`. Two runs with the same parameters give byte-identical workspaces, except for
the derived `.secondchair/` state.

Cost: the Core rebuilds its index after any write (#172), which makes writing N documents
O(N^2). While writing, the generator reads a stale index and refreshes it at three points of
each session, ordered so that nothing it reads is stale; the world-turn reads the real one.
"""

import copy
import itertools
import random
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import yaml

from secondchair.core import admission, canon, delegation, index, jobs, knowledge, workspace, world
from secondchair.core.workspace import STATE_DIR, Workspace

SIZES = {"S": 10, "M": 100, "L": 400}  # sessions
START = "1000-01-01"
AGENT = "synth"
PARTY = index.PARTY
PAIR_TYPES = ("allied_with", "opposes", "knows", "serves")
CALENDAR = {
    "months": [
        {"name": name, "days": 30}
        for name in (
            "Frostwane",
            "Thawmoot",
            "Seedlight",
            "Rainwatch",
            "Bloomtide",
            "Highsun",
            "Harvestgold",
            "Reapmoon",
            "Mistfall",
            "Emberdusk",
            "Deepdark",
            "Yearsend",
        )
    ],
    "week": {
        "days": ["Firstday", "Secondday", "Thirdday", "Fourthday", "Fifthday", "Restday"],
        "anchor": {"date": START, "weekday": 1},
    },
    "era": "Reckoning of the Lantern",
}
_PREFIX = "Bram Cael Dov Eld Fen Garr Hale Ivo Jory Kest Lorn Mira Nym Orla Perr Quill Rhee Sable"
_SUFFIX = "wick mere dane holt ford vale stow rin sey lowe bright thorn"
_SURNAME = (
    "Ashgrove Brightwater Cindermoor Dunmarrow Eastfold Fallowmere Gildcrest Hollowmere "
    "Ironbrook Juniper Kettleburn Larkspur Marrowby Netherby Oakenshaw Pennyroyal"
)
_PLACES = "Gildenmere Harrowfen Ironvale Kestrelwatch Lowtide Mournhollow Saltreach Thistledown"
_FACTIONS = ("Lantern Wardens", "Brass Concord", "Hollow Court", "Reedwater Guild")
_TASKS = (
    "guard the ferry at dusk",
    "return the borrowed ledger",
    "carry a letter to the harbour",
    "keep the bridge toll honest",
    "shelter the travelling players",
    "stay silent about the cellar",
)
_STATEMENT = {
    "allied_with": "{a} is allied with {b}.",
    "opposes": "{a} opposes {b}.",
    "knows": "{a} knows {b} well.",
    "serves": "{a} serves {b}.",
}


@dataclass
class Synth:
    """A generated campaign: its workspace, its model of the truth and its gold set."""

    ws: Workspace
    seed: int
    sessions: int
    final_date: str
    gold: list[dict[str, Any]]
    npcs: list[dict[str, str]]  # {"id", "name"}
    fronts: list[dict[str, Any]]  # the model: entity, anchor, every, capacity, step_at
    stats: dict[str, int] = field(default_factory=dict)


def _clock() -> SimpleNamespace:
    ticks, base = itertools.count(), datetime(2030, 1, 1, tzinfo=UTC)
    return SimpleNamespace(now=lambda tz=None: base + timedelta(seconds=next(ticks)))


@contextmanager
def frozen_index() -> Generator[None]:
    """Read the index as it is, without hashing the whole workspace on every query; refresh it
    with `index.rebuild`. For a run that changes nothing, or that refreshes on purpose."""

    def connect(ws: Workspace) -> sqlite3.Connection:
        path = ws.root / STATE_DIR / index.INDEX_FILE
        if not path.exists():
            index.rebuild(ws)
        return sqlite3.connect(path)

    with patch.object(index, "connect", connect):
        yield


def _cached_safe_load() -> Any:
    """`yaml.safe_load` remembering what it parsed: the Core re-reads every document on each
    index rebuild, and parsing is most of the generator's time. Callers get their own copy."""
    seen: dict[str, Any] = {}
    parse = yaml.safe_load

    def safe_load(stream: Any) -> Any:
        if not isinstance(stream, str):
            return parse(stream)
        if stream not in seen:
            seen[stream] = parse(stream)
        return copy.deepcopy(seen[stream])

    return safe_load


class _Campaign:
    def __init__(
        self,
        ws: Workspace,
        seed: int,
        sessions: int,
        npcs_per_session: int,
        plots_active: int,
        retcon_rate: float,
        contradiction_rate: float,
        calendar_jumps: int,
    ) -> None:
        self.ws, self.n, self.rng = ws, sessions, random.Random(seed)
        self.npcs_per_session, self.plots_active = npcs_per_session, plots_active
        self.retcon_rate, self.contradiction_rate = retcon_rate, contradiction_rate
        self.tools = {t.name: t for t in [*canon.tools(ws), *knowledge.tools(ws)]}
        self.names: dict[str, str] = {}  # entity id -> name
        self.npcs: list[dict[str, str]] = []
        self.places: list[dict[str, str]] = []
        self.factions: list[dict[str, str]] = []
        self.next_npcs: list[dict[str, str]] = []
        self.next_front: tuple[dict[str, str], dict[str, str]] | None = None
        self.fronts: list[dict[str, Any]] = []
        self.pairs: dict[tuple[str, str], list[dict]] = {}
        self.secrets: list[dict] = []
        self.promises: list[dict] = []
        self.rumours: list[dict] = []
        self.retcons: list[dict] = []
        self.tokens = itertools.count(1)  # unique, searchable words in statements
        # Session dates: strictly increasing, with a few long jumps.
        jumps = set(self.rng.sample(range(2, sessions + 1), min(calendar_jumps, sessions - 1)))
        self.dates = [START]
        for i in range(1, sessions + 1):
            days = self.rng.randint(90, 300) if i in jumps else self.rng.randint(3, 14)
            self.dates.append(ws.calendar.add(self.dates[-1], f"{days}d"))

    # Writing through the Core

    def do(self, tool: str, **args: Any) -> str:
        """One delegated action; the id of the document it wrote."""
        found = self.tools[tool]
        # ADR 0015: a synthetic history has no table to quote; composed as the Core would.
        with admission.under(admission.CORE):
            change = found.fn(**args)
        result = delegation.act(self.ws, found, AGENT, lambda: change)
        assert result["status"] == "applied", (tool, result)
        return Path(delegation.read_entry(self.ws, result["entry"])["target"]).stem

    def refresh(self) -> None:
        errors = index.rebuild(self.ws)
        assert not errors, errors

    def entity(self, name: str, kind: str) -> dict[str, str]:
        found = {"id": self.do("create_entity", names=[name], kind=kind), "name": name}
        self.names[found["id"]] = name
        return found

    def person(self) -> str:
        taken = set(self.names.values())
        while (
            name := f"{self.rng.choice(_PREFIX.split())}{self.rng.choice(_SUFFIX.split())} "
            f"{self.rng.choice(_SURNAME.split())}"
        ) in taken:
            pass  # ponytail: the pool is 2700 names; a campaign past that needs a bigger one
        return name

    def seen(self, session: int, quote: str) -> dict[str, str]:
        where = f"notes/session-{session:03d}.md:{self.rng.randint(1, 200)}"
        return {"kind": "observation", "quote": quote, "locator": where}

    def fact(self, session: int, statement: str, **fields: Any) -> str:
        origin = fields.pop("origin", None) or self.seen(session, statement)
        args = {"entities": [], **fields}
        return self.do("record_fact", statement=statement, origin=origin, **args)

    def event(self, session: int, text: str, date: str, **fields: Any) -> str:
        origin = fields.pop("origin", None) or self.seen(session, text)
        return self.do("record_event", description=text, date=date, origin=origin, **fields)

    def learn(self, session: int, who: str, fact: str, text: str, date: str, mode: str = "knows"):
        origin = self.seen(session, text)
        self.do("record_knowledge", knower=who, fact=fact, origin=origin, mode=mode, date=date)

    # Setup, in the prep moment

    def setup(self) -> None:
        self.factions = [self.entity(f"The {name}", "faction") for name in _FACTIONS]
        self.places = [self.entity(n, "place") for n in self.rng.sample(_PLACES.split(), 6)]
        opening = [self.front_entities() for _ in range(self.plots_active)]
        self.prepare_next(1)
        self.refresh()
        for entities in opening:
            self.add_front(START, *entities)
        self.refresh()

    def front_entities(self) -> tuple[dict[str, str], dict[str, str]]:
        number = next(self.tokens)
        front = self.entity(f"The Matter of the {number}th Bell", "other")
        return front, self.entity(f"Keepers of the {number}th Bell", "faction")

    def prepare_next(self, session: int) -> None:
        """What session `session` needs, created in the session before it."""
        self.next_npcs = [self.entity(self.person(), "npc") for _ in range(self.npcs_per_session)]
        self.next_front = self.front_entities() if session > 1 and session % 10 == 0 else None

    def add_front(self, anchor: str, front: dict[str, str], carrier: dict[str, str]) -> None:
        every, capacity = self.rng.choice((14, 21, 30)), self.rng.randint(4, 8)
        step_at = max(1, capacity // 2)
        rule = {"carrier": carrier["id"], "capacity": capacity, "every": f"{every}d"}
        gm = {"kind": "gm", "words": f"{front['name']} presses on."}
        for key, value in (
            ("front", {**rule, "anchor": anchor}),
            ("clock", 0),
            ("agenda", {"id": "turning-point", "when": {"clock_gte": step_at}}),
        ):
            state = {"of": front["id"], "key": key, "value": value}
            self.fact(0, f"{front['name']} has a {key}.", origin=gm, state=state)
        self.fronts.append(
            {
                "entity": front["id"],
                "anchor": anchor,
                "every": every,
                "capacity": capacity,
                "step_at": step_at,
            }
        )

    # The sessions

    def run(self) -> None:
        self.setup()
        for i in range(1, self.n + 1):
            delegation.start_session(self.ws)
            delegation.end_session(self.ws)  # the wrap is queued for a model's later work
            with frozen_index():
                self.session(i, self.dates[i])
            since = START if world.cursor(self.ws) is None else None
            world.world_turn(self.ws, self.dates[i], since=since)

    def label(self, pair: tuple[str, str]) -> str:
        return f"{self.names[pair[0]]} and {self.names[pair[1]]}"

    def relation(self, i: int, pair: tuple[str, str], kind: str, date: str | None) -> str:
        a, b = pair
        text = _STATEMENT[kind].format(a=self.names[a], b=self.names[b])
        relation = {"type": kind, "subject": a, "object": b}
        return self.fact(i, text, entities=[a, b], relation=relation, valid_from=date)

    def current(self, pair: tuple[str, str]) -> dict:
        return [s for s in self.pairs[pair] if not s["undone"]][-1]

    def session(self, i: int, date: str) -> None:
        rng = self.rng
        mine, front = self.next_npcs, self.next_front
        self.npcs += mine
        learn: list[tuple[str, Any]] = []  # (kind, record) the party or an NPC learns in stage C
        todo: dict[str, Any] = {}

        # Stage B: facts. Everything it reads is already indexed.
        if front:
            self.add_front(date, *front)
        for npc in mine:
            place = rng.choice(self.places)
            there = {"type": "lives_in", "subject": npc["id"], "object": place["id"]}
            self.fact(
                i,
                f"{npc['name']} lives in {place['name']}.",
                entities=[npc["id"]],
                relation=there,
                valid_from=date,
            )
            if rng.random() < 0.5:
                group = rng.choice(self.factions)
                member = {"type": "member_of", "subject": npc["id"], "object": group["id"]}
                self.fact(
                    i,
                    f"{npc['name']} belongs to {group['name']}.",
                    entities=[npc["id"]],
                    relation=member,
                    valid_from=date,
                )
        if len(self.npcs) >= 2:
            old = [p for p in self.pairs if self.current(p)["start"] != date]
            if old and rng.random() < 0.6:
                pair = rng.choice(old)
                kind = rng.choice([t for t in PAIR_TYPES if t != self.current(pair)["type"]])
                todo["transition"] = (pair, kind, self.relation(i, pair, kind, None))
            else:
                a, b = rng.sample(self.npcs, 2)
                pair = (min(a["id"], b["id"]), max(a["id"], b["id"]))
                if pair not in self.pairs:
                    kind = rng.choice(PAIR_TYPES)
                    seg = self.segment(kind, date, self.relation(i, pair, kind, date), None)
                    self.pairs[pair] = [seg]
                    learn.append(("segment", seg))
        for npc in mine:
            token = f"secret {next(self.tokens)}"
            text = f"{npc['name']} hides a secret ({token})."
            secret = {
                "token": token,
                "npc": npc["id"],
                "created": date,
                "fact": self.fact(i, text, entities=[npc["id"]], valid_from=date),
                "disclosed": None,
                "when": i + rng.randint(1, 8) if rng.random() < 0.7 else None,
            }
            self.secrets.append(secret)
            learn.append(("secret", secret))
        if len(self.npcs) >= 2 and i % 3 == 0:
            a, b = rng.sample(self.npcs, 2)
            token = f"oath {next(self.tokens)}"
            text = f"{a['name']} promises {b['name']} to {rng.choice(_TASKS)} ({token})."
            promise = {
                "token": token,
                "a": a["name"],
                "b": b["name"],
                "made": date,
                "ended": None,
                "outcome": None,
                "fact": self.fact(i, text, entities=[a["id"], b["id"]], valid_from=date),
            }
            self.promises.append(promise)
            learn.append(("promise", promise))
        if len(self.npcs) >= 2 and rng.random() < self.contradiction_rate:
            a, b = rng.sample(self.npcs, 2)
            token = f"rumour {next(self.tokens)}"
            text = f"Rumour has it that {a['name']} and {b['name']} are sworn foes ({token})."
            rumour = {
                "token": token,
                "npc": a["id"],
                "fact": self.fact(i, text, entities=[a["id"], b["id"]], never_true=True),
                "date": date,
            }
            self.rumours.append(rumour)
            learn.append(("rumour", rumour))
        self.refresh()

        # Stage C: events and knowledge.
        if "transition" in todo:
            pair, kind, fact = todo["transition"]
            before = self.current(pair)
            opened = self.event(
                i,
                f"{self.label(pair)} change.",
                date,
                kind="played",
                opens=[fact],
                closes=[before["fact"]],
            )
            before["end"] = date
            seg = self.segment(kind, date, fact, opened)
            self.pairs[pair].append(seg)
            learn.append(("segment", seg))
        open_promises = [p for p in self.promises if p["ended"] is None and p["made"] != date]
        if open_promises and rng.random() < 0.4:
            promise = rng.choice(open_promises)
            kept = rng.random() < 0.7
            text = f"{promise['a']} {'kept' if kept else 'broke'} the promise to {promise['b']}."
            self.event(
                i, f"{text} ({promise['token']})", date, kind="played", closes=[promise["fact"]]
            )
            promise.update(ended=date, outcome="kept" if kept else "broken")
        for kind, record in learn:
            self.record_learned(i, date, kind, record)
        for secret in self.secrets:
            if secret["when"] == i:
                secret["disclosed"] = date
                self.learn(i, PARTY, secret["fact"], f"The party learns {secret['token']}.", date)
        retconned = None
        eligible = [
            p
            for p, segs in self.pairs.items()
            if len([s for s in segs if not s["undone"]]) > 1
            and self.current(p)["event"]
            and self.current(p)["start"] != date
        ]
        if eligible and rng.random() < self.retcon_rate:
            retconned = rng.choice(eligible)
            words = {"kind": "gm", "words": f"{self.label(retconned)} never changed."}
            todo["retcon"] = self.event(
                i,
                words["words"],
                date,
                origin=words,
                kind="played",
                replaces=self.current(retconned)["event"],
            )
        self.refresh()

        # Stage D: the GM confirms the retcon; the next session's entities are made.
        if retconned:
            canon.confirm(self.ws, todo["retcon"], "synth", True)
            segs = [s for s in self.pairs[retconned] if not s["undone"]]
            segs[-1]["undone"] = True
            segs[-2]["end"] = None
            self.retcons.append(
                {
                    "pair": retconned,
                    "date": date,
                    "removed": segs[-1]["type"],
                }
            )
        if i < self.n:
            self.prepare_next(i + 1)
            self.refresh()

    def segment(self, kind: str, start: str, fact: str, event: str | None) -> dict:
        return {
            "type": kind,
            "start": start,
            "end": None,
            "fact": fact,
            "event": event,
            "undone": False,
            "learned": None,
        }

    def record_learned(self, i: int, date: str, kind: str, record: dict) -> None:
        """Who learns what the session made: the NPC its secret, the party a relationship or a
        promise (most of the time), an NPC a rumour as a belief."""
        rng = self.rng
        if kind == "secret":
            self.learn(i, record["npc"], record["fact"], f"{record['token']} is known.", date)
        elif kind == "rumour":
            self.learn(
                i,
                record["npc"],
                record["fact"],
                f"{record['token']} is believed.",
                date,
                "believes",
            )
            if rng.random() < 0.3:
                self.learn(
                    i, PARTY, record["fact"], f"{record['token']} is whispered.", date, "suspects"
                )
        elif kind == "promise" or rng.random() < 0.6:  # a segment: the party may never learn it
            self.learn(i, PARTY, record["fact"], "The party sees it.", date)
            record["learned"] = date


def generate(
    root: Path,
    size: str | int = "S",
    seed: int = 0,
    *,
    npcs_per_session: int = 1,
    plots_active: int = 3,
    retcon_rate: float = 0.1,
    contradiction_rate: float = 0.15,
    calendar_jumps: int | None = None,
) -> Synth:
    """Write a synthetic campaign of `size` (S, M, L, or a number of sessions) into the new
    directory `root`, and return it with its gold set."""
    sessions = SIZES[size] if isinstance(size, str) else size
    jumps = max(1, sessions // 25) if calendar_jumps is None else calendar_jumps
    root.mkdir(parents=True, exist_ok=True)
    ids = itertools.count(1)
    with (
        patch("secrets.token_hex", lambda n=32: f"{next(ids):0{2 * n}x}"),
        patch("yaml.safe_load", _cached_safe_load()),
        patch.object(delegation, "datetime", clock := _clock()),
        patch.object(jobs, "datetime", clock),
    ):
        ws = workspace.init(root, "en", CALENDAR)
        run = _Campaign(
            ws,
            seed,
            sessions,
            npcs_per_session,
            plots_active,
            retcon_rate,
            contradiction_rate,
            jumps,
        )
        run.run()
    from secondchair.bench import gold  # the gold set is a view of the model

    return Synth(
        ws=ws,
        seed=seed,
        sessions=sessions,
        final_date=run.dates[sessions],
        gold=gold.questions(run, random.Random(f"{seed}-gold")),
        npcs=run.npcs,
        fronts=run.fronts,
        stats={
            "pairs": len(run.pairs),
            "retcons": len(run.retcons),
            "secrets": len(run.secrets),
            "promises": len(run.promises),
            "rumours": len(run.rumours),
        },
    )
