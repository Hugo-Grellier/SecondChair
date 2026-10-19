"""S0 probes (10-success-bench.md, BEN-07), continuity errors and leaks (MET-01, MET-03).

An agent answers each probe in the GM view with a structured answer, using the workspace's own
entity ids; this module scores the answers against the frozen gold set with no LLM judge. Entity
ids resolve to the gold labels through exact names (sample-campaign/README.md, step 2), and
bible facts through their cited paragraph (a `source` origin whose page is the gold label).

Leaks are read from canon alone: what each listed audience holds (knowledge.known) must carry no
canary, no forbidden string, and, for the party at start, none of the forbidden bible facts.
"""

import json
from typing import Any

import yaml

from secondchair.core import index, knowledge
from secondchair.core.delegation import LOG_DIR
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


def score_probes(ws: Workspace, gold: dict, answers: dict[str, Any]) -> dict:
    """Pass or fail per probe, the continuity errors (refused contradictions with canon,
    rejections and undos for `contradiction`, failed probes) and the leaks. `passed` is false on
    any leak, an invariant (10-success-bench.md); the rest is reported, not gated (MET-05a)."""
    labels = _labels(ws, gold)
    expected = {p["id"]: p["expected"] for p in gold["probes"]}
    probes = {
        p: p in answers and _norm(answers[p], labels) == _norm(expected[p], {}) for p in PROBES
    }
    refused = gm = 0
    for path in sorted((ws.root / LOG_DIR).glob("*.yaml")):
        entry = yaml.safe_load(path.read_text())
        refused += entry.get("status") == "refused"
        gm += entry.get("interaction") in ("reject", "undo") and entry["reason"] == "contradiction"
    failed = sum(not ok for ok in probes.values())
    found = leaks(ws, gold)
    return {
        "passed": not found,
        "leaks": found,
        "probes": probes,
        "continuity_errors": {
            "refused_contradictions": refused,
            "rejected_or_undone_for_contradiction": gm,
            "failed_probes": failed,
            "total": refused + gm + failed,
        },
    }


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
        if f["origin"].get("kind") == "source" and f["origin"]["source"].endswith("bible.md")
    }
    found += [
        f"{by_label[f]} known by party at start ({f})"
        for f in held("party", gold["start"]["date"])
        if by_label.get(f) in checks["forbidden_party_facts_at_start"]
    ]
    return found


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
