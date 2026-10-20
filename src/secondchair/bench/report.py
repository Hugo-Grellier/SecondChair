"""The S0 report (MET-01, MET-03, MET-05, MET-05a, BEN-04), recomputed from the stored action
logs of a bench run without re-running any agent.

Each run's canon is replayed from its action log alone into a scratch copy of its workspace, then
scored with no LLM judge:

- GM effort: the GM interactions and hand edits the log records (BEN-02: counts, no durations);
- entity recall and precision against the gold set's named entities, by an exact shared name;
- leaks: a canary in any entity (names, aliases, player-facing description) and every leak of
  canon knowledge (`s0.leaks`);
- narrative direction, from the log's actions (`s0.narrative_direction`);
- the fact probes passed, from the agent's stored reply (`s0.score_answers`), and the continuity
  errors: refused contradictions, rejections and undos for `contradiction`, failed probes.

Only the two invariants gate (MET-05a): a run passes when it has no leak and no narrative breach.
Every metric is reported per table as median and min-max over the runs (BEN-04).
"""

import json
import shutil
import statistics
import tempfile
from pathlib import Path

import yaml

from secondchair.bench import s0
from secondchair.core import delegation, index, jobs, knowledge, workspace
from secondchair.core.workspace import STATE_DIR

TABLES = ("delegated", "baseline")
METRICS = (
    "gm_effort",
    "entity_recall",
    "entity_precision",
    "leaks",
    "narrative_direction",
    "fact_probes",
    "continuity_errors",
)
META_FILE = "bench.yaml"
REPLY_FILE = "probes-reply.txt"  # the agent's reply to the fact probes, beside the workspace
GOLD_FILE = "gold.yaml"


def score_run(stored: Path, gold: dict) -> dict:
    """One run's metrics, from the action log of its stored workspace."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "replay"
        ignore = shutil.ignore_patterns(delegation.CANON_DIR, STATE_DIR)
        shutil.copytree(stored, root, ignore=ignore)
        ws = workspace.load(root)
        entries, _ = delegation.read_log(ws)
        for target, content in delegation.core_states(entries).items():
            if content is not None:
                (root / target).parent.mkdir(parents=True, exist_ok=True)
                (root / target).write_text(content)
        entities = index.search_entities(ws)
        canaries = [
            f"{marker} in entity {e['id']}"
            for e in entities
            for marker in knowledge.CANARY.findall(
                "\n".join([*e["names"], *e["aliases"], e["description"]])
            )
        ]
        leaks = canaries + s0.leaks(ws, gold)
        actions = [e for e in entries if e.get("kind") == "action"]
        narrative = s0.narrative_direction(ws, actions)
        reply = stored.parent / REPLY_FILE
        answers = s0.parse_answers(reply.read_text()) if reply.is_file() else {}
        probes = s0.score_answers(ws, gold, answers, s0.FACT_PROBES)
    labels = {n: label for label, e in gold["entities"].items() for n in e["names"]}
    named = [e for e in entities if e["names"]]
    matching = [e for e in named if labels.keys() & set(e["names"])]
    found = {labels[n] for e in named for n in e["names"] if n in labels}
    return {
        "gm_effort": sum(e.get("kind") in ("gm_interaction", "hand_edit") for e in entries),
        "entity_recall": len(found) / len(set(labels.values())),
        "entity_precision": len(matching) / len(named) if named else 0.0,
        "leaks": leaks,
        "narrative_direction": narrative,
        "fact_probes": sum(probes["probes"].values()),
        "continuity_errors": probes["continuity_errors"]["total"],
        "probes": probes["probes"],
    }


def _spread(values: list[float]) -> dict:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def recompute(out: Path) -> dict:
    """Score every stored run of a bench output directory and write `report.json`, `report.md`
    and, when every run passes, the mapping in runner-configuration format (ARC-30)."""
    meta = yaml.safe_load((out / META_FILE).read_text())
    if meta["scenario"] == "S2":
        from secondchair.bench import s2  # through the harness, it imports this module

        return s2.recompute(out)
    gold = yaml.safe_load((out / GOLD_FILE).read_text())
    tables: dict[str, dict] = {}
    for table in TABLES:
        dirs = sorted((out / table).iterdir(), key=lambda d: int(d.name))
        runs = [score_run(d / "workspace", gold) for d in dirs]
        tables[table] = {
            m: _spread([len(r[m]) if isinstance(r[m], list) else r[m] for r in runs])
            for m in METRICS
        } | {"runs": runs}
    passed = all(
        not r["leaks"] and not r["narrative_direction"] for t in tables.values() for r in t["runs"]
    )
    effort = [tables[t]["gm_effort"]["median"] for t in TABLES]
    found = {
        "scenario": meta["scenario"],
        "runner_configuration": meta["runner_configuration"],
        "passed": passed,
        "gain": {"gm_effort": effort[0] < effort[1]},  # MET-05a: strictly below
        "tables": tables,
    }
    (out / "report.json").write_text(json.dumps(found, indent=2) + "\n")
    (out / "report.md").write_text(markdown(found))
    mapping = out / "mapping.yaml"
    if passed:
        # ponytail: one configuration compared, so it is the cheapest passing one; rank by cost
        # once the bench compares several (BEN-04's matrix).
        runners = {tier: [meta["runner_configuration"]] for tier in jobs.TIERS}
        mapping.write_text(yaml.safe_dump({"runners": runners}, sort_keys=False))
    else:
        mapping.unlink(missing_ok=True)
    return found


def markdown(found: dict) -> str:
    """The report for a person: one row per metric, median (min-max) per table."""
    config = "/".join(found["runner_configuration"][k] for k in jobs.CONFIG_KEYS)
    runs = len(found["tables"]["delegated"]["runs"])
    lines = [
        f"# S0 bench report: {'passed' if found['passed'] else 'FAILED'}",
        "",
        f"Runner configuration `{config}`, {runs} runs per table. Invariants (leaks, narrative "
        "direction) gate every run; every other metric is reported (MET-05a). No LLM judge.",
        "",
        "| Metric | Delegated | Baseline |",
        "|---|---|---|",
    ]
    for m in METRICS:
        cells = [
            "{median:.3g} ({min:.3g}-{max:.3g})".format(**found["tables"][t][m]) for t in TABLES
        ]
        lines.append(f"| {m} | {cells[0]} | {cells[1]} |")
    lines += ["", f"GM effort gain vs baseline: {'yes' if found['gain']['gm_effort'] else 'no'}."]
    for t in TABLES:
        for i, run in enumerate(found["tables"][t]["runs"], 1):
            lines += [f"- {t} run {i}: {msg}" for msg in run["leaks"] + run["narrative_direction"]]
    return "\n".join(lines) + "\n"
