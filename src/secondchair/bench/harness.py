"""The S0 harness (BEN-01..04, ARC-30): the prep rebuild of the sample campaign, N times at the
delegated table and N times at the baseline, each run in its own workspace kept with its action
log, then the report recomputed from those logs (`report.recompute`).

- Delegated: the new campaign's seeded table. The bench queues the rebuild playbook and starts it
  with its own mapping (the reference runner configuration for every tier), then a scripted GM
  answers the open calls from the gold set (BEN-02).
- Baseline: every responsibility at manual (the `read` profile), so agents take no action and the
  scripted GM does each operation by hand, one hand edit per entity of the gold set (BEN-03).

At both tables an agent then answers the fact and knowledge probes from canon, in the GM view,
with structured answers in workspace entity ids (`ask_probes`).
"""

import shutil
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager, nullcontext, suppress
from pathlib import Path

import yaml

from secondchair import runner
from secondchair.bench import report, s0
from secondchair.core import calls, canon, delegation, index, jobs, workspace
from secondchair.core.workspace import Workspace

PLAYBOOK = "rebuild-entities-from-a-bible"
# The scripted fake agent host CI runs instead of a real one (BEN-06); `{model}` picks its script.
FAKE = "fake"
FAKE_HOST = [sys.executable, "-m", "secondchair.bench.fake", "{job}", "{model}"]
PROBE_PLAYBOOK = "answer-probes"
TEE = (
    "import subprocess, sys; "
    "sys.exit(subprocess.run(sys.argv[2:], stdout=open(sys.argv[1], 'w')).returncode)"
)
# The shape of each probe's answer, never its value: the gold set stays the evaluator's.
ANSWER_SHAPES = {
    "factions": "An object: each faction's entity id -> the entity ids of the NPCs who belong "
    "to it.",
    "hidden-name": '{"secret_name": the name as canon spells it, or null, "public_name": the '
    "same, or null}.",
    "mystery-structure": '{"conclusions": [...], "nodes": [...], "clues": [...]}: the '
    "mystery's own local ids, as check_mystery returns them.",
    "mystery-answer": '{"cause": what causes the bell, "money": where the repair money went, '
    'each in a few lowercase words joined by hyphens, "sabotage": true or false}.',
    "planned-treasure": "An object: each planned treasure, by its entity id or, when it has no "
    'entity, by the label canon gives it -> its holder\'s entity id, or "unclaimed"; and '
    '"party_owns": the planned treasures the party owns.',
    "situations": "An object: each active or available situation's entity id -> "
    '{"stage": "active" or "available", "deadline": its date (YYYY-MM-DD) or null}.',
    "edda-knowledge": '{"name": whether Edda knows the hidden maintainer\'s name, "cause": '
    'whether she knows what causes the bell, "diversion": whether she knows where the repair '
    "money went}: each true or false, on the campaign's start date.",
    "circle-knowledge": '{"name": whether the faction itself holds its hidden member\'s name, '
    '"cause": whether it holds what causes the bell}: each true or false.',
    # Canon has no ids for these facts: the shape names each by a term, never which side it is on.
    "common-knowledge": '{"both_know": [...], "both_do_not_know": [...]}: the terms, among '
    '"bell-ringing" (the bell is ringing), "council-controls-gate" (the council controls the '
    'gate) and "bell-cause" (what causes the bell), that both of them know, and that neither '
    "of them knows, on the campaign's start date.",
    "belief": '{"ever_true": true or false, "believers": the entity ids of those who believe it}.',
}


def run_s0(
    sample: Path, out: Path, config: dict[str, str], hosts: dict[str, list], n: int = 3
) -> dict:
    """Run S0 into the new directory `out` and return its report."""
    campaign = yaml.safe_load((sample / "campaign.yaml").read_text())
    gold = yaml.safe_load((sample / "gold.yaml").read_text())
    out.mkdir(parents=True)
    shutil.copy(sample / "gold.yaml", out / report.GOLD_FILE)
    meta = {"scenario": "S0", "runs": n, "runner_configuration": config}
    (out / report.META_FILE).write_text(yaml.safe_dump(meta, sort_keys=False))
    runners = {tier: [config] for tier in jobs.TIERS}
    hosts = {**hosts, FAKE: FAKE_HOST}
    for i in range(1, n + 1):
        for table in report.TABLES:
            run_dir = out / table / str(i)
            run_dir.mkdir(parents=True)
            ws = workspace.init(
                run_dir / "workspace", campaign["campaign_language"], campaign["calendar"]
            )
            with nullcontext() if config["host"] == FAKE else _serving(ws):
                if table == "baseline":
                    by_hand(ws, gold)
                else:
                    # The agent gets the bible alone, never the gold set (sample README).
                    bible = shutil.copy(sample / "bible.md", run_dir / "bible.md")
                    job = runner.queue(ws, PLAYBOOK, {"bible": str(bible)})
                    # A failure is logged in the job's attempts and raised as a call; scored.
                    with suppress(runner.RunnerError):
                        runner.run(ws, job["id"], runners, hosts)
                    answer_calls(ws, gold)
                ask_probes(ws, gold, run_dir, runners, hosts)
    return report.recompute(out)


def ask_probes(
    ws: Workspace, gold: dict, run_dir: Path, runners: dict, hosts: dict[str, list]
) -> None:
    """Ask the fact and knowledge probes in the GM view (sample README, step 3): an
    `answer-probes` job gets each question and the shape of its answer, never the expected one.
    The agent's reply is kept beside the workspace (`report.REPLY_FILE`), for the report to
    score."""
    probes = {
        p["id"]: {"question": p["question"], "answer": ANSWER_SHAPES[p["id"]]}
        for p in gold["probes"]
        if p["id"] in s0.PROBES
    }
    asked = run_dir / "probes.yaml"
    asked.write_text(yaml.safe_dump(probes, sort_keys=False, allow_unicode=True))
    job = runner.queue(ws, PROBE_PLAYBOOK, {"probes": str(asked)})
    reply = run_dir / report.REPLY_FILE
    # Each host's command, with its standard output (the agent's reply) written to the reply.
    teed = {name: [sys.executable, "-c", TEE, str(reply), *argv] for name, argv in hosts.items()}
    with suppress(runner.RunnerError):
        runner.run(ws, job["id"], runners, teed)


def by_hand(ws: Workspace, gold: dict) -> None:
    """The baseline: the read table, and the scripted GM creating each named gold entity by
    hand, which the Core logs as hand edits."""
    read = {moment: delegation.BASE_PROFILES["read"] for moment in delegation.MOMENTS}
    (ws.root / delegation.TABLE_FILE).write_text(yaml.safe_dump(read, sort_keys=False))
    for entity in gold["entities"].values():
        if entity["names"]:
            change = canon.create_entity(entity["names"])
            (ws.root / change.path).parent.mkdir(parents=True, exist_ok=True)
            (ws.root / change.path).write_text(change.after or "")
    delegation.log_hand_edits(ws)


def answer_calls(ws: Workspace, gold: dict) -> None:
    """The scripted GM (BEN-02, gold `scripted_gm`): approve a proposed entity the gold set
    names, reject every other proposal, take no action on an exception."""
    names = {n for e in gold["entities"].values() for n in e["names"]}
    for call in calls.read_calls(ws):
        if call["status"] != "open" or call["kind"] != "proposal":
            continue
        entry = delegation.read_entry(ws, call["entry"])
        proposed = entry["tool"] == "create_entity" and entry["after"]
        if proposed and names & set(index.split_doc(proposed)[0]["names"]):
            delegation.approve(ws, entry["id"], "cli", True)
        else:
            delegation.reject(ws, entry["id"], "other", "cli", True)


@contextmanager
def _serving(ws: Workspace) -> Generator[None]:
    """`secondchair serve` on the run's workspace, for a real agent host to reach over MCP at
    the configured port."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "secondchair.cli", "serve", str(ws.root)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        proc.stdout.readline()  # serving
        yield
    finally:
        proc.terminate()
        proc.wait(timeout=10)
