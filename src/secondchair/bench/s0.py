"""S0 probes (10-success-bench.md, BEN-07), continuity errors and leaks (MET-01, MET-03).

An agent answers each probe in the GM view with a structured answer, using the workspace's own
entity ids; this module scores the answers against the frozen gold set with no LLM judge. Entity
ids resolve to the gold labels through exact names (sample-campaign/README.md, step 2), and
bible facts through their cited paragraph (an origin carrying the bible as `source` and the gold
label as `page`).

Living-world probes (BEN-07) are read from the workspace after a world-turn case: clocks, agenda
steps and who knows them, situation stages, what stays queued and why.

Leaks are read from canon alone: what each listed audience holds (knowledge.known) must carry no
canary, no forbidden string, and, for the party at start, none of the forbidden bible facts.

The narrative-direction invariant and the drift ratio are read from the action log alone.
"""

import json
from contextlib import suppress
from typing import Any

import py3langid
import yaml

from secondchair.bench import paraphrase
from secondchair.core import calls, capture, delegation, index, knowledge, world
from secondchair.core.delegation import LOG_DIR
from secondchair.core.tools import Change
from secondchair.core.workspace import Workspace

# Probes answered from facts, and from the mystery graph on facts (mystery-structure, answered
# with the mystery's own conclusion, node and clue ids).
FACT_PROBES = (
    "factions",
    "hidden-name",
    "mystery-structure",
    "mystery-answer",
    "planned-treasure",
    "situations",
)
KNOWLEDGE_PROBES = ("edda-knowledge", "circle-knowledge", "common-knowledge", "belief")
PROBES = FACT_PROBES + KNOWLEDGE_PROBES


def language_drift(ws: Workspace) -> dict:
    """Language drift (10-success-bench.md; VIS-05): the share, in characters, of the generated
    text in canon (fact statements, event descriptions, entity descriptions) that a deterministic
    language detector does not find in the campaign language. Measured, never blocked (CAN-23)."""
    expected = ws.campaign_language.split("-")[0].lower()
    texts = [(f["id"], f["statement"]) for f in index.search_facts(ws, include_retconned=True)]
    texts += [(e["id"], e["description"]) for e in index.search_events(ws)]
    texts += [(e["id"], e["description"]) for e in index.search_entities(ws)]
    total = off = 0
    drifted = []
    for doc_id, text in texts:
        if not text.strip():
            continue
        found, _ = py3langid.classify(text)
        total += len(text)
        if found != expected:
            off += len(text)
            drifted.append({"id": doc_id, "language": found})
    return {"share": off / total if total else 0.0, "drifted": drifted}


def score_probes(ws: Workspace, gold: dict, answers: dict[str, Any]) -> dict:
    """Pass or fail per probe, the continuity errors (refused contradictions with canon,
    rejections and undos for `contradiction`, failed probes), the leaks, the narrative-direction
    breaches, the drift ratio and the language drift. `passed` is false on any leak or narrative
    breach, the invariants (10-success-bench.md); the rest is reported, not gated (MET-05a)."""
    actions = _actions(ws)
    found, narrative = leaks(ws, gold), narrative_direction(ws, actions)
    return {
        "passed": not found and not narrative,
        "leaks": found,
        "narrative_direction": narrative,
        "drift_ratio": drift_ratio(ws, actions),
        **score_answers(ws, gold, answers),
        "language_drift": language_drift(ws),
        "capture_coverage": capture_coverage(ws, gold),
    }


def score_answers(
    ws: Workspace, gold: dict, answers: dict[str, Any], asked: tuple[str, ...] = PROBES
) -> dict:
    """Pass or fail per asked probe (no answer fails) and the continuity errors: refused
    contradictions with canon, rejections and undos for `contradiction`, failed probes."""
    labels = _labels(ws, gold)
    expected = {p["id"]: p["expected"] for p in gold["probes"]}
    probes = {
        p: p in answers and _norm(answers[p], labels) == _norm(expected[p], {}) for p in asked
    }
    refused = gm = 0
    for path in sorted((ws.root / LOG_DIR).glob("*.yaml")):
        entry = yaml.safe_load(path.read_text())
        refused += entry.get("status") == "refused"
        gm += entry.get("interaction") in ("reject", "undo") and entry["reason"] == "contradiction"
    failed = sum(not ok for ok in probes.values())
    return {
        "probes": probes,
        "continuity_errors": {
            "refused_contradictions": refused,
            "rejected_or_undone_for_contradiction": gm,
            "failed_probes": failed,
            "total": refused + gm + failed,
        },
    }


def parse_answers(reply: str) -> dict[str, Any]:
    """The structured answers an agent replied to the probes with: the last JSON object of its
    reply. A reply with none answers nothing, so every probe fails."""
    end = reply.rfind("}")
    for start in reversed([i for i, c in enumerate(reply[:end]) if c == "{"]):
        with suppress(ValueError):
            found = json.loads(reply[start : end + 1])
            if isinstance(found, dict):
                return found
    return {}


def capture_coverage(ws: Workspace, gold: dict) -> dict:
    """Capture coverage (10-success-bench.md; the protocol's step 4): recall and precision of the
    candidate facts captured from the session notes against the gold set's units. A unit is a
    Source and quote; it matches when its quote, date and knowers (known_by and learned_by, by
    gold label) all match. Several candidates on one quote are one unit. Dropped candidates are
    never stored, so they never count.
    ponytail: the gold's evaluator fields (fact, clue, amount) have no workspace form; the quote
    stands for them until capture emits structured answers."""
    labels = _labels(ws, gold) | {index.PARTY: "party"}
    units: dict[tuple[str, str], dict] = {}
    for c in capture.candidates(ws):
        unit = units.setdefault((c["source"], c["quote"]), {"dates": set(), "knowers": set()})
        unit["dates"].add(c["date"])
        unit["knowers"] |= {labels.get(k, k) for k in c["known_by"]}
    matched, missed = [], []
    for g in gold["capture"]["candidates"]:
        learned = g["expected"].get("learned_by", [])
        knowers = {*g["expected"].get("known_by", []), *_as_list(learned)}
        hit = any(
            source.endswith(g["source"])
            and quote == g["quote"]
            and u["dates"] == {g["date"]}
            and u["knowers"] == knowers
            for (source, quote), u in units.items()
        )
        (matched if hit else missed).append(g["id"])
    total = len(gold["capture"]["candidates"])
    return {
        "recall": len(matched) / total,
        "precision": len(matched) / len(units) if units else 0.0,
        "matched": matched,
        "missed": missed,
        "proposed_units": len(units),
    }


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else [value]


_TAKEN = ("pending", "applied", "undone", "rejected")  # proposed, whatever came of it


def _actions(ws: Workspace) -> list[dict]:
    return [e for e in delegation.read_log(ws)[0] if e.get("kind") == "action"]


def narrative_direction(ws: Workspace, actions: list[dict] | None = None) -> list[str]:
    """The narrative-direction invariant, read from the action log (DEL-08, LW-08): every
    narrative-direction action applied only with the GM's approval, and no living-world action
    making the party know a fact. One message per breach."""
    found = []
    for e in _actions(ws) if actions is None else actions:
        if e["status"] not in ("applied", "undone"):
            continue
        if e["responsibility"] == "narrative_direction" and e["approval"] is None:
            found.append(
                f"entry {e['id']}: narrative direction at {e['effective_level']}, applied "
                "without the GM's approval"
            )
        if e["responsibility"] == "living_world" and delegation.discloses(
            Change(e["target"], e["after"])
        ):
            found.append(f"entry {e['id']}: the living world disclosed to the party")
    return found


def drift_ratio(ws: Workspace, actions: list[dict] | None = None) -> dict:
    """Agent-initiated vs GM-initiated narrative decisions (10-success-bench.md): narrative
    direction and living-world consequences agents proposed, an `unless` settled by citing facts
    included, against the GM's own living-world gestures (a pause, a resume). One decision per
    occurrence key, else per log entry: a consequence written as several files counts several
    times. Watched for a rise, never gated."""
    agent = {r["key"] for r in world.occurrences(ws) if r["cites"]}  # whoever then accepted it
    gm = set()
    for e in _actions(ws) if actions is None else actions:
        if e["status"] not in _TAKEN or e["responsibility"] not in delegation.JOB_GOVERNED:
            continue
        if e["agent"] == "gm" and e.get("occurrence"):  # only the Core logs one (world.set_active)
            gm.add(e["occurrence"])
        elif e["job"] is not None or e["responsibility"] == "narrative_direction":
            agent.add(e.get("occurrence") or e["id"])
    return {"agent": len(agent), "gm": len(gm), "ratio": len(agent) / len(gm) if gm else None}


def score_world_turn(ws: Workspace, gold: dict, case: str) -> dict:
    """Pass or fail per expected field of one `world_turn_probes` case, read from the workspace
    after its world-turn; `unscored` lists the expected fields this harness cannot read yet."""
    [expected] = [c["expected"] for c in gold["world_turn_probes"] if c["id"] == case]
    labels = _labels(ws, gold) | {
        f["id"]: f["origin"]["page"]
        for f in index.search_facts(ws, include_retconned=True)
        if "page" in f["origin"]
    }
    seen = world_observations(ws, labels)
    return {
        "probes": {
            k: _norm(seen[k], labels) == _norm(v, {}) for k, v in expected.items() if k in seen
        },
        "unscored": sorted(set(expected) - set(seen)),
    }


def world_observations(ws: Workspace, labels: dict[str, str]) -> dict[str, Any]:
    """What the living world shows now, in the vocabulary of the gold world-turn cases."""
    now, records = world.state(ws), world.occurrences(ws)
    label = {v: k for k, v in labels.items()}
    holders = index.search_knowledge(ws, [*labels, index.PARTY])

    def knowers(fact: str) -> list[str]:
        return [k["knower"] for k in holders if k["fact"] == fact]

    def learns(knower: str | None) -> list[str]:  # from a world-turn effect, never disclosed
        return [
            k["fact"] for k in holders if k["knower"] == knower and k["origin"]["kind"] == "rule"
        ]

    done: dict[str, str] = {}  # agenda step id -> the fact recording it done
    for f in index.search_facts(ws):
        state = f.get("state") or {}
        if state.get("key") == "agenda" and state["value"]["status"] == "done":
            done[state["value"]["id"]] = f["id"]
    queued = [r for r in records if r["status"] == "queued"]
    open_calls = {c["id"]: c for c in calls.read_calls(ws) if c["status"] == "open"}
    deadlines = {
        open_calls[r["call"]]["deadline"]
        for r in queued
        if r["call"] in open_calls and open_calls[r["call"]]["kind"] == "exception"
    }
    seen: dict[str, Any] = {
        "clocks": {e: f["clock"] for e, f in now["fronts"].items()},
        "agenda_steps": list(done),
        "agenda_knowers": {step: knowers(f) for step, f in done.items()},
        "queued_ticks": sorted({r["entity"] for r in queued if r["kind"] == "tick"}),
        "narrative_pending": [r["entity"] for r in queued if r["class"] == "narrative"],
        "suppressed_tick_dates": [r["date"] for r in records if r["status"] == "suppressed"],
        "unless_evidence": sorted({c for r in records for c in r["cites"]}),
        "party_learns": learns(index.PARTY),
        "edda_learns": learns(label.get("npc-edda")),
    }
    if len(deadlines) == 1:
        [seen["exception_deadline"]] = deadlines
    if ferry := label.get("situation-ferry"):
        situation = now["situations"].get(ferry, {})
        seen["situation_ferry_stage"] = situation.get("stage")
        expiry = [r for r in records if r["key"] == f"{ferry}/deadline@{situation.get('deadline')}"]
        expired = [f["id"] for f in index.search_facts(ws, entity=ferry) if f["valid_to"] is None]
        seen["ferry_expiry_knowers"] = (
            [k for f in expired for k in knowers(f)]
            if expiry and expiry[0]["status"] == "applied"
            else []
        )
    return seen


def leaks(ws: Workspace, gold: dict) -> list[str]:
    """Every leak in canon, one message each: a canary reaching any canary audience, a forbidden
    string reaching the party, the secret name reaching a forbidden audience, a forbidden bible
    fact held by the party at start."""
    checks = gold["leak_checks"]
    knower = {label: i for i, label in _labels(ws, gold).items()} | {"party": index.PARTY}
    secret_names = gold["entities"]["npc-hidden"]["names"]
    found = []

    def held(audience: str, at: str | None = None) -> dict[str, dict]:
        return knowledge.known(ws, knower[audience], at) if audience in knower else {}

    for audience in checks["canary_audiences"]:
        for f, h in held(audience).items():
            found += [
                f"{m} reaches {audience} ({f})" for m in knowledge.CANARY.findall(h["statement"])
            ]
    for f, h in held("party").items():
        found += [
            f"{s!r} reaches party ({f})"
            for s in checks["forbidden_party_strings"]
            if s in h["statement"] and not knowledge.CANARY.fullmatch(s)  # canaries counted above
        ]
    for audience in checks["forbidden_name_audiences"]:
        for f, h in held(audience).items():
            found += [
                f"{n!r} reaches {audience} ({f})" for n in secret_names if n in h["statement"]
            ]
    by_label = {
        f["id"]: f["origin"]["page"]
        for f in index.search_facts(ws)
        if str(f["origin"].get("source", "")).endswith("bible.md") and "page" in f["origin"]
    }
    found += [
        f"{by_label[f]} known by party at start ({f})"
        for f in held("party", gold["start"]["date"])
        if by_label.get(f) in checks["forbidden_party_facts_at_start"]
    ]
    return found


def paraphrase_leaks(ws: Workspace, gold: dict) -> list[str]:
    """REPORTED ONLY (#198 G2, never a gate): party-held statements and entity descriptions that
    reword a forbidden bible fact, through `paraphrase.leaks`. Exact leaks are `leaks`."""
    forbidden = set(gold["leak_checks"]["forbidden_party_facts_at_start"])
    secrets = {
        f["origin"]["page"]: f["statement"]
        for f in index.search_facts(ws)
        if str(f["origin"].get("source", "")).endswith("bible.md")
        and f["origin"].get("page") in forbidden
    }
    held = knowledge.known(ws, index.PARTY)
    texts = {f: h["statement"] for f, h in held.items()} | {
        e["id"]: e["description"] for e in index.search_entities(ws) if e["description"]
    }
    return paraphrase.leaks(secrets, texts)


def _labels(ws: Workspace, gold: dict) -> dict[str, str]:
    """Workspace entity id -> gold label, by an exact shared name."""
    by_name = {n: label for label, e in gold["entities"].items() for n in e["names"]}
    return {
        e["id"]: by_name[name]
        for e in index.search_entities(ws)
        for name in e["names"]
        if name in by_name
    }


def _norm(value: Any, labels: dict[str, str]) -> Any:
    """Ids resolved to labels; list order is immaterial."""
    if isinstance(value, dict):
        return {_norm(k, labels): _norm(v, labels) for k, v in value.items()}
    if isinstance(value, list):
        return sorted((_norm(v, labels) for v in value), key=json.dumps)
    if isinstance(value, str):
        return labels.get(value, value)
    return value
