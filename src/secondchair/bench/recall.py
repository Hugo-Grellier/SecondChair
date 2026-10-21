"""The recall bench (#195): the Core's own query functions scored against a generated temporal
gold set (`gold.py`), with no model.

It asks `index.search_facts(at=...)`, `index.search_events` and `knowledge.known` the gold set's
questions, in the GM's view (canon) and in the party's (what it learned), and counts the answers
that match. Two groups are invariants, which must score 1.0 on every run: a party-view question
before a revelation is never answered yes (delayed revelation), and a retconned relationship is
never given as current (retcon). The rest are tracked scores, not floors: the gold set is
generated, so it is not a MET-02 reference gold set (docs/research/long-campaign-scaling.md).
"""

import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from secondchair.bench import synth
from secondchair.core import index, knowledge
from secondchair.core.workspace import Workspace

INVARIANT_KINDS = ("delayed_revelation", "retcon")
ASOF_KINDS = ("as_of_relation", "party_relation", "promise", "promise_in_force")


class _Asker:
    def __init__(self, ws: Workspace) -> None:
        self.ws = ws
        self.ids = {n: e["id"] for e in index.search_entities(ws) for n in e["names"]}
        self.facts: dict[str, str] = {}

    def fact(self, token: str) -> str:
        if token not in self.facts:
            [found] = index.search_facts(self.ws, text=token, include_retconned=True)
            self.facts[token] = found["id"]
        return self.facts[token]

    def relation(self, q: dict[str, Any]) -> str | None:
        a, b = self.ids[q["a"]], self.ids[q["b"]]
        held = knowledge.known(self.ws, "party", q["at"]) if q["view"] == "party" else None
        types = [
            f["relation"]["type"]
            for f in index.search_facts(self.ws, entity=a, at=q["at"])
            if f["relation"]
            and f["relation"]["type"] in synth.PAIR_TYPES
            and {f["relation"]["subject"], f["relation"]["object"]} == {a, b}
            and (held is None or f["id"] in held)
        ]
        return types[0] if len(types) == 1 else (None if not types else f"ambiguous {types}")

    def answer(self, q: dict[str, Any]) -> Any:
        kind, ws = q["kind"], self.ws
        if kind in ("current_relation", "as_of_relation", "party_relation"):
            return self.relation(q)
        if kind == "retcon":
            found = self.relation(q)
            return f"retconned {found}" if found == q["forbid"] else found
        if kind == "delayed_revelation":
            who = "party" if q["knower"] == "party" else self.ids[q["knower"]]
            return self.fact(q["token"]) in knowledge.known(ws, who, q["at"])
        if kind == "promise":
            [fact] = index.search_facts(ws, text=q["token"], include_retconned=True)
            ending = [e["description"] for e in index.search_events(ws, fact=fact["id"])]
            how = ending and ("kept" if "kept" in ending[-1] else "broken")
            return {"made": fact["valid_from"], "ended": fact["valid_to"], "outcome": how or None}
        if kind == "promise_in_force":
            fid = self.fact(q["token"])
            valid = fid in {f["id"] for f in index.search_facts(ws, text=q["token"], at=q["at"])}
            return valid and (q["view"] == "gm" or fid in knowledge.known(ws, "party", q["at"]))
        if kind == "belief":
            held = knowledge.known(ws, self.ids[q["knower"]], q["at"]).get(self.fact(q["token"]))
            valid = index.search_facts(ws, text=q["token"], at=q["at"])
            return held["mode"] if held and held["never_true"] and not valid else None
        raise ValueError(f"unknown question kind {kind!r}")


def score(ws: Workspace, questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Score `questions` against the Core's answers: {(kind, view): [asked, right]}, the
    failures, and whether the two invariants hold."""
    with synth.frozen_index():
        index.rebuild(ws)
        asker = _Asker(ws)
        tally: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        failures = []
        for q in questions:
            got = asker.answer(q)
            cell = tally[q["kind"], q["view"]]
            cell[0] += 1
            if got == q["expect"]:
                cell[1] += 1
            else:
                failures.append({**q, "got": got})
    kept = all(r == n for (k, _), (n, r) in tally.items() if k in INVARIANT_KINDS)
    return {"tally": dict(tally), "failures": failures, "invariants": kept}


def recall(tally: dict, kinds: tuple[str, ...]) -> str:
    asked = sum(n for (k, _), (n, _) in tally.items() if k in kinds)
    right = sum(r for (k, _), (_, r) in tally.items() if k in kinds)
    return f"{right / asked:.3f}" if asked else "n/a"


def run(sizes: list[str], seed: int = 0) -> tuple[bool, str]:
    """Generate and score each size: whether every invariant held, and the Markdown report."""
    rows, details, failed, passed = [], [], [], True
    for size in sizes:
        with tempfile.TemporaryDirectory(prefix="secondchair-recall-") as tmp:
            made = synth.generate(Path(tmp) / "workspace", size, seed)
            start = time.perf_counter()
            found = score(made.ws, made.gold)
            seconds = time.perf_counter() - start
        tally = found["tally"]
        passed &= found["invariants"]
        rows.append(
            f"| {size} | {made.sessions} | {len(made.gold)} "
            f"| {recall(tally, ('current_relation',))} | {recall(tally, ASOF_KINDS)} "
            f"| {recall(tally, ('delayed_revelation',))} | {recall(tally, ('retcon',))} "
            f"| {recall(tally, ('belief',))} | {seconds:.1f} |"
        )
        details += [
            f"| {size} | {kind} | {view} | {n} | {r} |"
            for (kind, view), (n, r) in sorted(tally.items())
        ]
        failed += [
            f"- {size} {f['kind']} ({f['view']}): {f['ask']} expected {f['expect']!r}, "
            f"got {f['got']!r}"
            for f in found["failures"][:5]
        ]
    return passed, "\n".join(
        [
            f"# Temporal recall bench (seed {seed}, no model)",
            "",
            "A generated gold set, so a tracked track and not a reference score. The two "
            "invariants (delayed revelation, retcon) must be 1.000.",
            "",
            "| Size | Sessions | Questions | Current | As-of | Delayed revelation (invariant) "
            "| Retcon (invariant) | Belief | Scoring (s) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *rows,
            "",
            f"Invariants: {'held' if passed else 'BROKEN'}.",
            "",
            "| Size | Kind | View | Asked | Right |",
            "| --- | --- | --- | ---: | ---: |",
            *details,
            *(["", "First failures:", *failed] if failed else []),
            "",
        ]
    )
