"""S0 fact probes (10-success-bench.md, BEN-07) and continuity errors (MET-01, MET-03).

An agent answers each probe in the GM view with a structured answer, using the workspace's own
entity ids; this module scores the answers against the frozen gold set with no LLM judge. Entity
ids resolve to the gold labels through exact names (sample-campaign/README.md, step 2).
"""

import json
from typing import Any

import yaml

from secondchair.core import index
from secondchair.core.delegation import LOG_DIR
from secondchair.core.workspace import Workspace

# Probes answered from facts, and from the mystery graph on facts (mystery-structure, answered
# with the mystery's own conclusion, node and clue ids). The knowledge and belief probes come
# with #39.
FACT_PROBES = (
    "factions",
    "hidden-name",
    "mystery-structure",
    "mystery-answer",
    "planned-treasure",
    "situations",
)


def score_fact_probes(ws: Workspace, gold: dict, answers: dict[str, Any]) -> dict:
    """Pass or fail per fact probe, and the continuity errors: refused contradictions with canon,
    rejections and undos for `contradiction`, and failed probes."""
    labels = _labels(ws, gold)
    expected = {p["id"]: p["expected"] for p in gold["probes"]}
    probes = {
        p: p in answers and _norm(answers[p], labels) == _norm(expected[p], {}) for p in FACT_PROBES
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
