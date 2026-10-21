"""The generated temporal gold set (#195): questions about a synthetic campaign with the answers
its generator knows, from its own model of the truth and not from the Core.

A question is `{kind, view, at, ask, ...}` plus the data its scorer needs (`recall.py`) and its
`expect`ed answer. The views are the GM's, who sees canon, and the party's, who sees what it
learned. Because the generator writes the answers, this is not a MET-02 gold set: it is a
tracked, non-reference track.
"""

import random
from typing import Any

from secondchair.core import index

KINDS = (
    "current_relation",  # GM: the relationship of two NPCs now
    "as_of_relation",  # GM: ... on a past date
    "party_relation",  # party: ... on a date, as far as the party had learned it
    "retcon",  # GM: after a retcon, the retconned relationship is never given as current
    "delayed_revelation",  # who knew a secret on a date, the party only once disclosed
    "promise",  # when a promise was made, ended, and how
    "promise_in_force",  # GM and party: whether it held on a date
    "belief",  # a rumour an NPC believes, which is never valid
)


def questions(run: Any, rng: random.Random) -> list[dict[str, Any]]:
    """The gold set of a generated campaign `run` (synth._Campaign), at most 25 + sessions / 2
    questions of each kind, chosen with `rng`."""
    cal, final = run.ws.calendar, run.dates[run.n]

    def before(date: str) -> str:
        return cal.add(date, "-1d")

    def holds(segs: list[dict], date: str) -> dict | None:
        on = index.date_key(cal, date)
        for s in segs:
            if s["undone"] or index.date_key(cal, s["start"]) > on:
                continue
            if s["end"] is None or index.date_key(cal, s["end"]) > on:
                return s
        return None

    by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}

    def add(kind: str, view: str, at: str, ask: str, **data: Any) -> None:
        by_kind[kind].append({"kind": kind, "view": view, "at": at, "ask": ask, **data})

    for pair, segs in run.pairs.items():
        a, b = run.names[pair[0]], run.names[pair[1]]
        live = [s for s in segs if not s["undone"]]
        dates = {final}
        for s in live:
            dates |= {s["start"], before(s["start"])} | ({s["end"]} if s["end"] else set())
        for date in sorted(dates):
            seg = holds(segs, date)
            who = {"a": a, "b": b}
            kind = "current_relation" if date == final else "as_of_relation"
            ask = f"On {date}, what is the relationship between {a} and {b}?"
            add(kind, "gm", date, ask, **who, expect=seg and seg["type"])
            learned = (
                seg
                and seg["learned"]
                and index.date_key(cal, seg["learned"]) <= index.date_key(cal, date)
            )
            add(
                "party_relation", "party", date, ask, **who, expect=seg["type"] if learned else None
            )
    for r in run.retcons:
        a, b = run.names[r["pair"][0]], run.names[r["pair"][1]]
        ask = f"The GM retconned a change between {a} and {b}: what holds on {r['date']}?"
        # What holds is what the final canon says: a later retcon of the same pair can restore
        # an earlier relationship, even the type this retcon removed.
        seg = holds(run.pairs[r["pair"]], r["date"])
        expect = seg and seg["type"]
        forbid = r["removed"] if r["removed"] != expect else None
        add("retcon", "gm", r["date"], ask, a=a, b=b, expect=expect, forbid=forbid)
    for s in run.secrets:
        who = run.names[s["npc"]]
        base = {"token": s["token"]}
        ask = f"On {{}}, does {{}} hold the fact {s['token']}?"
        add(
            "delayed_revelation",
            "gm",
            s["created"],
            ask.format(s["created"], who),
            **base,
            knower=who,
            expect=True,
        )
        add(
            "delayed_revelation",
            "party",
            s["created"],
            ask.format(s["created"], "the party"),
            **base,
            knower="party",
            expect=False,
        )
        if s["disclosed"]:
            day = before(s["disclosed"])
            add(
                "delayed_revelation",
                "party",
                day,
                ask.format(day, "the party"),
                **base,
                knower="party",
                expect=False,
            )
            add(
                "delayed_revelation",
                "party",
                s["disclosed"],
                ask.format(s["disclosed"], "the party"),
                **base,
                knower="party",
                expect=True,
            )
        else:
            add(
                "delayed_revelation",
                "party",
                final,
                ask.format(final, "the party"),
                **base,
                knower="party",
                expect=False,
            )
    for p in run.promises:
        ask = f"When was the promise {p['token']} made, when did it end and how?"
        add(
            "promise",
            "gm",
            final,
            ask,
            token=p["token"],
            expect={"made": p["made"], "ended": p["ended"], "outcome": p["outcome"]},
        )
        held = f"Was the promise {p['token']} in force on {{}}?"
        inside = [p["made"]] + ([before(p["ended"])] if p["ended"] else [])
        for date in [before(p["made"]), *inside, *([p["ended"]] if p["ended"] else [])]:
            on = index.date_key(cal, date)
            expect = index.date_key(cal, p["made"]) <= on and (
                p["ended"] is None or on < index.date_key(cal, p["ended"])
            )
            add("promise_in_force", "gm", date, held.format(date), token=p["token"], expect=expect)
            known = index.date_key(cal, p["made"]) <= on
            add(
                "promise_in_force",
                "party",
                date,
                held.format(date),
                token=p["token"],
                expect=expect and known,
            )
    for r in run.rumours:
        ask = f"On {r['date']}, does {run.names[r['npc']]} hold {r['token']} as a belief?"
        add(
            "belief",
            "gm",
            r["date"],
            ask,
            token=r["token"],
            knower=run.names[r["npc"]],
            expect="believes",
        )
    cap = 25 + run.n // 2
    return [
        q
        for kind in KINDS
        for q in (rng.sample(by_kind[kind], cap) if len(by_kind[kind]) > cap else by_kind[kind])
    ]
