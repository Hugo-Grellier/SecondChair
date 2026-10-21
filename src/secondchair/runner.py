"""Playbooks and runners, outside the Core (ARC-20, ARC-21, ARC-24, ARC-26, ARC-27).

The Core queues jobs; a runner starts one in an agent host. The GM's machine configuration maps
each tier to an ordered list of runner configurations (host, model, effort); a host is a command
template. Model names live only there, never in the Core or a playbook (ARC-25).
"""

import json
import re
import subprocess
from pathlib import Path

from secondchair.core import jobs
from secondchair.core.playbooks import playbook, playbook_dirs, skills  # noqa: F401
from secondchair.core.workspace import Workspace

# The Core's playbooks: a Claude Code plugin whose `skills/` is also the Codex skill bundle
# (PKG-19). Each block ships its own the same way, registered under PLAYBOOK_GROUP (ARC-21).
PLAYBOOKS = Path(__file__).parent / "playbooks"

# Headless invocations; `{prompt}`, `{model}`, `{effort}`, `{playbooks}` and `{job}` are filled
# in, and an argument naming `{playbooks}` is repeated for each block's playbook directory. The
# machine configuration's `hosts` overrides or adds templates.
HOSTS: dict[str, list[str]] = {
    "claude": [
        "claude",
        "-p",
        "{prompt}",
        "--model",
        "{model}",
        "--effort",
        "{effort}",
        "--plugin-dir={playbooks}",
        "--allowedTools",
        "mcp__secondchair Read",
        # A job has no GM at hand: relaying the GM's approval is never a job's to do (DEL-27).
        # ponytail: only the built-in templates withhold it; a GM-defined host in the machine
        # configuration must do the same, until the Core refuses it to a job's session.
        "--disallowedTools",
        "mcp__secondchair__approve_proposal",
    ],
    "codex": [
        "codex",
        "exec",
        "--model",
        "{model}",
        "-c",
        'model_reasoning_effort="{effort}"',
        # `exec` never asks, so a tool needing approval is refused: the Core's delegation table,
        # not the host, decides what a SecondChair tool may do (ARC-04).
        "-c",
        'mcp_servers.secondchair.default_tools_approval_mode="approve"',
        "-c",
        'mcp_servers.secondchair.disabled_tools=["approve_proposal"]',
        "--skip-git-repo-check",
        "{prompt}",
    ],
}


class RunnerError(Exception):
    """A playbook, job or runner the runner cannot use, with a message for the GM."""


def queue(
    ws: Workspace,
    name: str,
    inputs: dict[str, str],
    tier: str | None = None,
    entities: list[str] | None = None,
) -> dict:
    """Queue a job for a playbook, at the playbook's tier unless the job overrides it, with the
    vocabulary of the given entities (default: the whole campaign vocabulary). An input the
    playbook declares with a trailing `?` is optional."""
    meta = playbook(name)
    declared = sorted(i.strip() for i in meta["inputs"].split(",") if i.strip())
    required = {i for i in declared if not i.endswith("?")}
    if not required <= set(inputs) <= {i.removesuffix("?") for i in declared}:
        raise RunnerError(f"Playbook {name} takes the inputs: {', '.join(declared)}.")
    return jobs.queue(
        ws,
        playbook=name,
        inputs=inputs,
        expected_output=meta["expected-output"],
        responsibility=meta["responsibility"],
        tier=tier or meta["tier"],
        entities=entities,
        writes=meta.get("writes") == "true",
    )


def prompt(ws: Workspace, job: dict) -> str:
    """What an agent host is asked to do for a job. A retried job lists the actions its earlier
    attempts already took, so the agent continues rather than redoes them (ARC-27, #171)."""
    contract = {k: v for k, v in job.items() if k not in ("status", "attempts", "at")}
    text = (
        f"Run SecondChair job {job['id']} with the `{job['playbook']}` playbook (skill). Pass "
        f"`job: {job['id']}` to every SecondChair delegated action, and call `finish_job` when "
        f"the playbook is complete. The job contract:\n{json.dumps(contract, ensure_ascii=False)}"
    )
    if taken := jobs.taken(ws, job["id"]):
        text += (
            "\nEarlier attempts failed or stopped before `finish_job`, after taking these actions "
            "(action log id: tool on target, status). Continue from there: do not take them "
            "again.\n" + taken
        )
    return text


def run(
    ws: Workspace, job_id: int, runners: dict[str, list[dict[str, str]]], hosts: dict[str, list]
) -> dict | None:
    """Start a queued job with the configurations for its tier, in order (ARC-27). Every attempt
    is logged with its configuration. None when no runner is configured for the tier: the job
    waits for the GM. When every configuration fails, the job stays queued, an exception is
    raised as a call on the GM, and `RunnerError` says so."""
    job = jobs.read(ws, job_id)
    while configs := runners.get(job["tier"], []):
        for config in configs:
            job = jobs.start(ws, job_id, config, manual=False)
            error = _launch(ws, job, config, hosts)
            job = jobs.read(ws, job_id)
            if job["status"] in (
                "done",
                "missed",
            ):  # finish_job, or a live deadline passed (ARC-28)
                return job
            # A clean exit is no proof the playbook is complete: only finish_job is (#171).
            jobs.end(ws, job_id, error or f"{config['host']} exited without calling finish_job")
        # The tier's list is exhausted: escalate one step, once, when a runner is configured there.
        up = jobs.TIERS[min(jobs.TIERS.index(job["tier"]) + 1, len(jobs.TIERS) - 1)]
        if not runners.get(up) or (escalated := jobs.escalate(ws, job_id)) is None:
            break
        job = escalated
    else:
        return None  # nothing configured for the job's first tier: the GM starts it
    call = jobs.raise_exception(
        ws,
        job_id,
        f"Every runner configuration for tier {job['tier']} failed; the job stays queued."
        + (
            f" Actions it already took stay logged:\n{taken}"
            if (taken := jobs.taken(ws, job_id))
            else ""
        ),
    )
    raise RunnerError(
        f"Job {job_id}: every runner configuration for tier {job['tier']} failed. It stays "
        f"queued; call {call['id']} waits for the break."
    )


def _launch(ws: Workspace, job: dict, config: dict[str, str], hosts: dict[str, list]) -> str | None:
    """Run the host's command for the job; the error, or None when it exits cleanly."""
    template = hosts.get(config["host"])
    if template is None:
        return f"no command template for agent host {config['host']!r}"
    values = {
        "prompt": prompt(ws, job),
        "model": config["model"],
        "effort": config["effort"],
        "job": str(job["id"]),
    }

    # One pass, so a value is never itself filled in; other braces stay as written.
    def fill(arg: str, playbooks: Path | None) -> str:
        filled = {**values, "playbooks": str(playbooks)}
        return re.sub(r"\{(\w+)\}", lambda m: filled.get(m[1], m[0]), arg)

    argv = [
        fill(arg, d)
        for arg in template
        for d in (playbook_dirs() if "{playbooks}" in arg else [None])
    ]
    try:
        proc = subprocess.Popen(
            argv, cwd=ws.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    except OSError as e:
        return f"{argv[0]}: {e.strerror or e}"
    while True:  # a live job's deadline caps it (ARC-28): stop the host once the job missed it
        try:
            stdout, stderr = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            if jobs.read(ws, job["id"])["status"] == "missed":
                proc.kill()
                proc.communicate()
                return f"job {job['id']} missed its deadline"
    if proc.returncode:
        tail = (stderr or stdout).strip()[-500:]
        return f"{argv[0]} exited with status {proc.returncode}: {tail}"
    return None
