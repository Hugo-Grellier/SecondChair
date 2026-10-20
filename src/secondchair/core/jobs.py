"""Jobs (ARC-23..29): work that needs a model, queued by the Core with an explicit contract.

The Core calls no model (ARC-20): it queues a job, records each start attempt with the runner
configuration used, and raises an exception as a call on the GM when every attempt failed.
Starting an agent host is a runner's work, outside the Core.

Workspace files (docs/contracts/workspace-layout.md): one YAML file per job in `jobs/`
(docs/contracts/job.schema.json), one per call on the GM in `calls/`.
"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from mcp.server.mcpserver import Context

from secondchair.core import canon, machine
from secondchair.core.delegation import (
    JOBS_DIR,
    DelegationError,
    _append,
    _for_agent,
    _read_yaml,
    _save,
    bind,
    bound_job,
    current_moment,
    locked,
)
from secondchair.core.tools import RESPONSIBILITIES
from secondchair.core.workspace import STATE_DIR, Workspace

TIERS = ("fast", "standard", "deep")  # ARC-25
PURCHASED_DIR = f"{STATE_DIR}/purchased"  # metadata indexes of purchased content (LIC-12)
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
    entity: str | None = None,
) -> dict:
    """Queue a job in the current moment; the Core starts nothing itself (ARC-23). A live job
    gets the deadline of the call it prepares as its latency cap (ARC-28); a blocking one forced
    to break misses it at once (DEL-31). Its vocabulary is that of the entity ids it is about, or
    the whole campaign vocabulary (CAN-22). `entity` is the acting entity the job works for,
    whose override withdraws it while queued (DEL-16)."""
    from secondchair.core import calls  # it builds on this module

    if tier not in TIERS:
        raise DelegationError(f"Tier {tier!r}: expected one of {', '.join(TIERS)}.")
    if responsibility not in RESPONSIBILITIES:
        raise DelegationError(f"Unknown responsibility {responsibility!r}.")
    inputs = _licensed(ws, inputs)
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
                "entity": entity,
                "deadline": due,
                "status": "queued",
                "attempts": [],
            },
            JOBS_DIR,
        )
        if at_once:
            calls._miss(ws, job)
        return job


def _licensed(ws: Workspace, inputs: dict[str, str]) -> dict[str, str]:
    """Purchased content is indexed by metadata by default (LIC-12): an input naming a path
    that is, or holds, purchased content the GM has not opted in to send to a model becomes the
    path of that path's metadata index, so none of its text reaches the job."""
    purchased = machine.purchased_content()
    found = {}
    for name, value in inputs.items():
        path = Path(value).expanduser()
        if path.is_absolute() and path.exists():
            path = path.resolve()
            if any(
                not opt_in and (path.is_relative_to(root) or root.is_relative_to(path))
                for root, opt_in in purchased
            ):
                value = str(_metadata_index(ws, path))
        found[name] = value
    return found


def _metadata_index(ws: Workspace, path: Path) -> Path:
    """A path's metadata index: its name and each file's relative path and size, no content."""
    # ponytail: lists every file under the path, slow for a huge directory such as a home
    # folder; cap the listing if a GM ever passes one.
    files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    index = {
        "purchased_content": path.name,
        "opt_in": False,
        "note": "Metadata only: the GM has not opted in to sending this purchased content to a "
        "model (LIC-12). Ask the GM for anything it does not list.",
        "files": [
            {
                "path": str(p.relative_to(path) if path.is_dir() else p.name),
                "bytes": p.stat().st_size,
            }
            for p in files
        ],
    }
    target = ws.root / PURCHASED_DIR / f"{hashlib.sha256(str(path).encode()).hexdigest()[:16]}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(index, sort_keys=False, allow_unicode=True))
    return target


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

    def start_job(job: int, host: str, model: str, effort: str, ctx: Context) -> dict[str, Any]:
        """Start a queued SecondChair job from this session, when the GM asks you to. Report the
        agent host, model and effort you run with: they are logged as the job's effective
        configuration. Returns the job contract; its tier is only a hint. Then follow its
        playbook and pass `job` to every delegated action. Until the job ends, every delegated
        action of this session is for it."""
        with _for_agent():
            if (running := bound_job(ws, ctx)) is not None:
                raise DelegationError(f"This session runs job {running}: finish it first.")
            record = start(ws, job, {"host": host, "model": model, "effort": effort}, manual=True)
            bind(ctx, job)
            return record

    def finish_job(job: int) -> dict[str, Any]:
        """Mark a started SecondChair job done once its playbook is complete."""
        with _for_agent():
            return end(ws, job)

    return [start_job, finish_job]


def _now() -> str:
    return datetime.now(UTC).isoformat()
