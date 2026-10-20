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
    JOBS_DIR,
    DelegationError,
    _append,
    _for_agent,
    _read_yaml,
    _save,
    current_moment,
    locked,
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
    blocking: bool = False,
    entities: list[str] | None = None,
) -> dict:
    """Queue a job in the current moment; the Core starts nothing itself (ARC-23). A live job
    gets the deadline of the call it prepares as its latency cap (ARC-28); a blocking one forced
    to break misses it at once (DEL-31). Its vocabulary is that of the entity ids it is about, or
    the whole campaign vocabulary (CAN-22)."""
    from secondchair.core import calls  # it builds on this module

    if tier not in TIERS:
        raise DelegationError(f"Tier {tier!r}: expected one of {', '.join(TIERS)}.")
    if responsibility not in RESPONSIBILITIES:
        raise DelegationError(f"Unknown responsibility {responsibility!r}.")
    with locked(ws):
        moment, _ = current_moment(ws)
        due, at_once = (
            calls.deadline(ws, responsibility, moment, blocking)
            if moment == "live-session"
            else (None, False)
        )
        job = _append(
            ws,
            {
                "playbook": playbook,
                "inputs": inputs,
                "expected_output": expected_output,
                "responsibility": responsibility,
                "moment": moment,
                "tier": tier,
                "campaign_language": ws.campaign_language,
                "vocabulary": canon.vocabulary(ws, entities),
                "blocking": blocking,
                "deadline": due,
                "status": "queued",
                "attempts": [],
            },
            JOBS_DIR,
        )
        if at_once:
            calls._miss(ws, job)
        return job


def read(ws: Workspace, job_id: int) -> dict:
    """A job record. Lock-free: `act` calls it while holding the lock."""
    path = ws.root / JOBS_DIR / f"{job_id:06d}.yaml"
    if not path.is_file():
        raise DelegationError(f"No job {job_id}.")
    return _read_yaml(path)


def pending(ws: Workspace) -> list[dict]:
    """Every job still to do (queued or started), oldest first."""
    jobs = [_read_yaml(p) for p in sorted((ws.root / JOBS_DIR).glob("*.yaml"))]
    return [job for job in jobs if job["status"] in ("queued", "started")]


def start(ws: Workspace, job_id: int, config: dict[str, str], manual: bool) -> dict:
    """Start a queued job with a runner configuration, logged as an attempt (ARC-27). On a
    manual start the configuration is what the GM's own session reports (ARC-29)."""
    if sorted(config) != sorted(CONFIG_KEYS) or not all(
        isinstance(v, str) and v.strip() for v in config.values()
    ):
        raise DelegationError(f"A runner configuration needs {', '.join(CONFIG_KEYS)}.")
    with locked(ws):
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
    with locked(ws):
        job = read(ws, job_id)
        if job["status"] != "started":
            raise DelegationError(f"Job {job_id} is {job['status']}, not started.")
        job["status"] = "queued" if error else "done"
        job["attempts"][-1].update(outcome="failed" if error else "done", error=error)
        _save(ws, job, JOBS_DIR)
        return job


def raise_exception(ws: Workspace, job_id: int, message: str) -> dict:
    """An exception as a call on the GM (ARC-27, DEL-30); the job stays queued."""
    from secondchair.core import calls

    return calls.raise_exception(ws, read(ws, job_id)["responsibility"], message, job=job_id)


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
