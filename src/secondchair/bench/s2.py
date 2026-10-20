"""The S2 harness (BEN-01..05, MET-01, MET-05a): Beginner Box prep in a bench world.

A private scenario (BEN-06): its directory, kept outside the repository, holds
- `scenario.yaml`: `campaign_language`, `calendar`, `restore` (the command that restores the
  bench world from its snapshot: a fresh import of the Beginner Box module, bound to no campaign,
  never the players' world, BEN-05) and the `inputs` of the `calibrate-encounters` job, whose
  `adventure` is the module in the GM's install, so it reaches the job as its metadata index
  unless the GM opted in (LIC-12);
- `gold.yaml`: `keep`, the workspace files or VTT documents the scripted GM keeps; it rejects or
  undoes every other action of the job (BEN-02).

Each run restores the bench world first, then starts the job in a new workspace with `serve`
running for a real agent host (the bench world's GM client connects to it). The report is
recomputed from the stored action logs: prep GM effort (GM interactions and hand edits), failed
actions and acceptance rate, per responsibility and as median and min-max (BEN-04). The baseline
is the number of gold operations, each one hand operation (BEN-03). Only the narrative-direction
invariant gates (MET-05a).
"""

import json
import shutil
import statistics
import subprocess
from contextlib import nullcontext, suppress
from pathlib import Path

import yaml

from secondchair import runner
from secondchair.bench import harness, s0
from secondchair.core import delegation, jobs, workspace

PLAYBOOK = "calibrate-encounters"
SCENARIO_FILE = "scenario.yaml"
DECIDED = ("applied", "rejected", "undone")


class BenchError(Exception):
    """A bench run that cannot go on, with a message for the GM."""


def run_s2(
    scenario: Path, out: Path, config: dict[str, str], hosts: dict[str, list], n: int = 3
) -> dict:
    """Run S2 into the new directory `out` and return its report."""
    definition = yaml.safe_load((scenario / SCENARIO_FILE).read_text())
    gold = yaml.safe_load((scenario / "gold.yaml").read_text())
    out.mkdir(parents=True)
    shutil.copy(scenario / "gold.yaml", out / "gold.yaml")
    meta = {"scenario": "S2", "runs": n, "runner_configuration": config}
    (out / "bench.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    runners = {tier: [config] for tier in jobs.TIERS}
    hosts = {**hosts, harness.FAKE: harness.FAKE_HOST}
    for i in range(1, n + 1):
        restore = subprocess.run(definition["restore"], capture_output=True, text=True)
        if restore.returncode:
            raise BenchError(
                f"Run {i}: restoring the bench world failed (status {restore.returncode}): "
                f"{(restore.stderr or restore.stdout).strip()[-500:]}"
            )
        ws = workspace.init(
            out / "delegated" / str(i) / "workspace",
            definition["campaign_language"],
            definition["calendar"],
        )
        job = runner.queue(ws, PLAYBOOK, definition["inputs"])
        serving = nullcontext() if config["host"] == harness.FAKE else harness._serving(ws)
        with serving, suppress(runner.RunnerError):
            runner.run(ws, job["id"], runners, hosts)
        review(ws, gold)
    return recompute(out)


def review(ws: workspace.Workspace, gold: dict) -> None:
    """The scripted GM (BEN-02): keep what the gold set lists, reject every other proposal and
    undo every other reversible action applied."""
    entries, _ = delegation.read_log(ws)
    for e in entries:
        if e.get("kind") != "action" or e["target"] in gold["keep"]:
            continue
        if e["status"] == "pending":
            delegation.reject(ws, e["id"], "other", "cli", True)
        elif e["status"] == "applied" and e["reversible"]:
            delegation.undo(ws, e["id"], "other", "cli", True)


def score_run(stored: Path) -> dict:
    """One run's metrics, from its action log alone."""
    ws = workspace.load(stored)
    entries, _ = delegation.read_log(ws)
    actions = [e for e in entries if e.get("kind") == "action"]
    failed: dict[str, int] = {}
    decided: dict[str, list[bool]] = {}
    for e in actions:
        if e["status"] == "failed":
            failed[e["responsibility"]] = failed.get(e["responsibility"], 0) + 1
        elif e["status"] in DECIDED:
            decided.setdefault(e["responsibility"], []).append(e["status"] == "applied")
    kept = [k for found in decided.values() for k in found]
    return {
        "prep_gm_effort": sum(
            e.get("kind") in ("gm_interaction", "hand_edit") and e["moment"] == "prep"
            for e in entries
        ),
        "failed_actions": sum(failed.values()),
        "acceptance_rate": sum(kept) / len(kept) if kept else 0.0,
        "failed_by_responsibility": failed,
        "acceptance_by_responsibility": {r: sum(k) / len(k) for r, k in decided.items()},
        "narrative_direction": s0.narrative_direction(ws, actions),
    }


def recompute(out: Path) -> dict:
    """Score every stored run and write `report.json` and `report.md`."""
    meta = yaml.safe_load((out / "bench.yaml").read_text())
    gold = yaml.safe_load((out / "gold.yaml").read_text())
    dirs = sorted((out / "delegated").iterdir(), key=lambda d: int(d.name))
    runs = [score_run(d / "workspace") for d in dirs]

    def spread(metric: str) -> dict:
        values = [r[metric] for r in runs]
        return {"median": statistics.median(values), "min": min(values), "max": max(values)}

    effort = spread("prep_gm_effort")
    found = {
        "scenario": "S2",
        "runner_configuration": meta["runner_configuration"],
        "passed": not any(r["narrative_direction"] for r in runs),
        "prep_gm_effort": effort,
        "baseline_gm_effort": len(gold["keep"]),
        "gain": {"prep_gm_effort": effort["median"] < len(gold["keep"])},  # MET-05a
        "failed_actions": spread("failed_actions"),
        "acceptance_rate": spread("acceptance_rate"),
        "runs": runs,
    }
    (out / "report.json").write_text(json.dumps(found, indent=2) + "\n")
    (out / "report.md").write_text(markdown(found))
    return found


def markdown(found: dict) -> str:
    """The report for a person."""
    config = "/".join(found["runner_configuration"][k] for k in jobs.CONFIG_KEYS)
    lines = [
        f"# S2 bench report: {'passed' if found['passed'] else 'FAILED'}",
        "",
        f"Runner configuration `{config}`, {len(found['runs'])} runs, each in a bench world "
        "restored from its snapshot. The narrative-direction invariant gates every run; every "
        "other metric is reported (MET-05a). No LLM judge.",
        "",
        "| Metric | Median (min-max) |",
        "|---|---|",
    ]
    for m in ("prep_gm_effort", "failed_actions", "acceptance_rate"):
        lines.append(f"| {m} | " + "{median:.3g} ({min:.3g}-{max:.3g})".format(**found[m]) + " |")
    lines += [
        "",
        f"Baseline prep GM effort: {found['baseline_gm_effort']}; gain: "
        f"{'yes' if found['gain']['prep_gm_effort'] else 'no'}.",
    ]
    for i, run in enumerate(found["runs"], 1):
        lines.append(
            f"- run {i}: failed {run['failed_by_responsibility'] or 'none'}, acceptance "
            f"{ {r: round(v, 3) for r, v in run['acceptance_by_responsibility'].items()} }"
        )
        lines += [f"  - {msg}" for msg in run["narrative_direction"]]
    return "\n".join(lines) + "\n"
