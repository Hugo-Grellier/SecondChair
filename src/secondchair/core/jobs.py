"""Jobs (ARC-23..29): work that needs a model, queued by the Core with an explicit contract.

The Core calls no model (ARC-20): it queues a job, records each start attempt with the runner
configuration used, and raises an exception as a call on the GM when every attempt failed.
Starting an agent host is a runner's work, outside the Core.

Workspace files (docs/contracts/workspace-layout.md): one YAML file per job in `jobs/`
(docs/contracts/job.schema.json), one per call on the GM in `calls/`.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from secondchair.core import canon
from secondchair.core.delegation import (
    CALLS_DIR,
    JOBS_DIR,
    DelegationError,
    _append,
    _for_agent,
    _locked,
    _read_yaml,
    _save,
    current_moment,
)
from secondchair.core.tools import RESPONSIBILITIES
from secondchair.core.workspace import Workspace

TIERS = ("fast", "standard", "deep")  # ARC-25
CONFIG_KEYS = ("host", "model", "effort")  # a runner configuration (ARC-26)


def queue(
    ws: Workspace,
    *,
    playbook: str,
    inputs: dict[str, str],
    expected_output: str,
    responsibility: str,
    tier: str,
) -> dict:
    """Queue a job in the current moment; the Core starts nothing itself (ARC-23)."""
    if tier not in TIERS:
        raise DelegationError(f"Tier {tier!r}: expected one of {', '.join(TIERS)}.")
    if responsibility not in RESPONSIBILITIES:
        raise DelegationError(f"Unknown responsibility {responsibility!r}.")
    with _locked(ws):
        moment, _ = current_moment(ws)
        return _append(
            ws,
            {
                "playbook": playbook,
                "inputs": inputs,
                "expected_output": expected_output,
                "responsibility": responsibility,
                "moment": moment,
                "tier": tier,
                "campaign_language": ws.campaign_language,
                # ponytail: the whole vocabulary; a narrower slice when a playbook needs one.
                "vocabulary": canon.vocabulary(ws),
                "status": "queued",
                "attempts": [],
            },
            JOBS_DIR,
        )


def read(ws: Workspace, job_id: int) -> dict:
    """A job record. Lock-free: `act` calls it while holding the lock."""
    path = ws.root / JOBS_DIR / f"{job_id:06d}.yaml"
    if not path.is_file():
        raise DelegationError(f"No job {job_id}.")
    return _read_yaml(path)


def pending(ws: Workspace) -> list[dict]:
    """Every job not done, oldest first."""
    jobs = [_read_yaml(p) for p in sorted((ws.root / JOBS_DIR).glob("*.yaml"))]
    return [job for job in jobs if job["status"] != "done"]


def start(ws: Workspace, job_id: int, config: dict[str, str], manual: bool) -> dict:
    """Start a queued job with a runner configuration, logged as an attempt (ARC-27). On a
    manual start the configuration is what the GM's own session reports (ARC-29)."""
    if sorted(config) != sorted(CONFIG_KEYS) or not all(
        isinstance(v, str) and v.strip() for v in config.values()
    ):
        raise DelegationError(f"A runner configuration needs {', '.join(CONFIG_KEYS)}.")
    with _locked(ws):
        job = read(ws, job_id)
        if job["status"] != "queued":
            raise DelegationError(f"Job {job_id} is {job['status']}, not queued.")
        job["status"] = "started"
        job["attempts"].append(
            {
                "at": _now(),
                "runner_configuration": dict(config),
                "manual": manual,
                "outcome": "started",
                "error": None,
            }
        )
        _save(ws, job, JOBS_DIR)
        return job


def end(ws: Workspace, job_id: int, error: str | None = None) -> dict:
    """End the started attempt: done, or failed with the job queued again for the next one."""
    with _locked(ws):
        job = read(ws, job_id)
        if job["status"] != "started":
            raise DelegationError(f"Job {job_id} is {job['status']}, not started.")
        job["status"] = "queued" if error else "done"
        job["attempts"][-1].update(outcome="failed" if error else "done", error=error)
        _save(ws, job, JOBS_DIR)
        return job


def raise_exception(ws: Workspace, job_id: int, message: str) -> dict:
    """An exception as a call on the GM, held for the break (ARC-27, DEL-30); the job stays
    queued. ponytail: a bare call record; #42 schedules calls and adds their deadlines."""
    with _locked(ws):
        job = read(ws, job_id)
        moment, seq = current_moment(ws)
        return _append(
            ws,
            {
                "kind": "exception",
                "moment": moment,
                "moment_seq": seq,
                "responsibility": job["responsibility"],
                "deadline": "break",
                "job": job_id,
                "message": message,
                "status": "open",
            },
            CALLS_DIR,
        )


def agent_tools(ws: Workspace) -> list[Callable[..., Any]]:
    """What an agent's session calls to take a job and close it, served by the Core."""

    def start_job(job: int, host: str, model: str, effort: str) -> dict[str, Any]:
        """Start a queued SecondChair job from this session, when the GM asks you to. Report the
        agent host, model and effort you run with: they are logged as the job's effective
        configuration. Returns the job contract; its tier is only a hint. Then follow its
        playbook and pass `job` to every delegated action."""
        with _for_agent():
            return start(ws, job, {"host": host, "model": model, "effort": effort}, manual=True)

    def finish_job(job: int) -> dict[str, Any]:
        """Mark a started SecondChair job done once its playbook is complete."""
        with _for_agent():
            return end(ws, job)

    return [start_job, finish_job]


def _now() -> str:
    return datetime.now(UTC).isoformat()
