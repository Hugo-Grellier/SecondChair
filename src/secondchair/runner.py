"""Playbooks and runners, outside the Core (ARC-20, ARC-21, ARC-24, ARC-26, ARC-27).

The Core queues jobs; a runner starts one in an agent host. The GM's machine configuration maps
each tier to an ordered list of runner configurations (host, model, effort); a host is a command
template. Model names live only there, never in the Core or a playbook (ARC-25).
"""

import json
import re
import subprocess
from pathlib import Path

import yaml

from secondchair.core import jobs
from secondchair.core.workspace import Workspace

# The Core's playbooks: a Claude Code plugin whose `skills/` is also the Codex skill bundle
# (PKG-19). ponytail: Core playbooks only; other blocks register theirs when they ship one.
PLAYBOOKS = Path(__file__).parent / "playbooks"
SKILLS = PLAYBOOKS / "skills"

# Headless invocations; `{prompt}`, `{model}`, `{effort}`, `{playbooks}` and `{job}` are filled
# in. The machine configuration's `hosts` overrides or adds templates.
HOSTS: dict[str, list[str]] = {
    "claude": [
        "claude",
        "-p",
        "{prompt}",
        "--model",
        "{model}",
        "--effort",
        "{effort}",
        "--plugin-dir",
        "{playbooks}",
        "--allowedTools",
        "mcp__secondchair Read",
    ],
    "codex": [
        "codex",
        "exec",
        "--model",
        "{model}",
        "-c",
        'model_reasoning_effort="{effort}"',
        "--skip-git-repo-check",
        "{prompt}",
    ],
}


class RunnerError(Exception):
    """A playbook, job or runner the runner cannot use, with a message for the GM."""


def playbook(name: str) -> dict[str, str]:
    """A playbook's SecondChair metadata, from its Agent Skills front matter."""
    path = SKILLS / name / "SKILL.md"
    if not path.is_file():
        known = ", ".join(sorted(p.name for p in SKILLS.iterdir()))
        raise RunnerError(f"No playbook {name!r}; known playbooks: {known}.")
    front = yaml.safe_load(path.read_text().split("---", 2)[1])
    prefix = "secondchair-"
    return {k.removeprefix(prefix): v for k, v in front["metadata"].items() if k.startswith(prefix)}


def queue(ws: Workspace, name: str, inputs: dict[str, str], tier: str | None = None) -> dict:
    """Queue a job for a playbook, at the playbook's tier unless the job overrides it."""
    meta = playbook(name)
    expected = sorted(i.strip() for i in meta["inputs"].split(",") if i.strip())
    if sorted(inputs) != expected:
        raise RunnerError(f"Playbook {name} takes the inputs: {', '.join(expected)}.")
    return jobs.queue(
        ws,
        playbook=name,
        inputs=inputs,
        expected_output=meta["expected-output"],
        responsibility=meta["responsibility"],
        tier=tier or meta["tier"],
    )


def prompt(job: dict) -> str:
    """What an agent host is asked to do for a job."""
    contract = {k: v for k, v in job.items() if k not in ("status", "attempts", "at")}
    return (
        f"Run SecondChair job {job['id']} with the `{job['playbook']}` playbook (skill). Pass "
        f"`job: {job['id']}` to every SecondChair delegated action, and call `finish_job` when "
        f"the playbook is complete. The job contract:\n{json.dumps(contract, ensure_ascii=False)}"
    )


def run(
    ws: Workspace, job_id: int, runners: dict[str, list[dict[str, str]]], hosts: dict[str, list]
) -> dict | None:
    """Start a queued job with the configurations for its tier, in order (ARC-27). Every attempt
    is logged with its configuration. None when no runner is configured for the tier: the job
    waits for the GM. When every configuration fails, the job stays queued, an exception is
    raised as a call on the GM, and `RunnerError` says so."""
    job = jobs.read(ws, job_id)
    configs = runners.get(job["tier"], [])
    if not configs:
        return None
    for config in configs:
        job = jobs.start(ws, job_id, config, manual=False)
        error = _launch(ws, job, config, hosts)
        job = jobs.read(ws, job_id)
        if job["status"] in ("done", "missed"):  # finish_job, or a live deadline passed (ARC-28)
            return job
        if error is None:
            return jobs.end(ws, job_id)
        jobs.end(ws, job_id, error)
    call = jobs.raise_exception(
        ws,
        job_id,
        f"Every runner configuration for tier {job['tier']} failed; the job stays queued.",
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
        "prompt": prompt(job),
        "model": config["model"],
        "effort": config["effort"],
        "playbooks": str(PLAYBOOKS),
        "job": str(job["id"]),
    }
    # One pass, so a value is never itself filled in; other braces stay as written.
    argv = [re.sub(r"\{(\w+)\}", lambda m: values.get(m[1], m[0]), arg) for arg in template]
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
