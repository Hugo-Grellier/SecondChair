"""Calls on the GM (ADR 0005, DEL-30..33, ARC-28, MET-06).

A call is a pending proposal, a surfaced exception or a ceiling refusal. The Core gives each one
a deadline, *now* when it blocks the current turn or scene, otherwise the next *break*; the
delegation table cell's deadline mode can force either. At its deadline an unanswered call takes
its safe default (a proposal is rejected, an exception takes no action), logged and shown again
at the break. A live job's deadline is that of the call it prepares (ARC-28).

Deadlines pass on GM gestures, never on a clock: `move_on` (the blocking turn or scene moved on),
`take_break` (a pause the GM signals) and the end of the moment (`delegation.change_moment`).

Workspace files (docs/contracts/workspace-layout.md): one YAML file per call in `calls/`
(docs/contracts/call.schema.json); every safe default is a `safe_default` action log entry.
"""

from secondchair.core.delegation import (
    CALLS_DIR,
    JOBS_DIR,
    LOG_DIR,
    _append,
    _cell,
    _read_yaml,
    _save,
    current_moment,
    current_session,
    locked,
    read_entry,
)
from secondchair.core.workspace import Workspace, WorkspaceError

DEADLINE_MODES = ("auto", "now", "break")  # DEL-07


def deadline(ws: Workspace, responsibility: str, moment: str, blocking: bool) -> tuple[str, bool]:
    """A call's deadline (DEL-30), and whether it takes its safe default at once: a blocking call
    forced to break does (DEL-31)."""
    mode = _cell(ws, moment, responsibility).get("deadline", "auto")
    if mode not in DEADLINE_MODES:
        raise WorkspaceError(
            f"{moment} / {responsibility}: deadline mode {mode!r}, expected one of "
            f"{', '.join(DEADLINE_MODES)}."
        )
    if mode == "auto":
        return ("now" if blocking else "break"), False
    return mode, mode == "break" and blocking


def open_call(
    ws: Workspace,
    *,
    kind: str,
    responsibility: str,
    table_moment: str,
    blocking: bool,
    entry: int | None = None,
    job: int | None = None,
    message: str | None = None,
) -> dict:
    """Record a call and schedule it. A job's call inherits the job's deadline when it has one
    (ARC-28). A call due now in a live session is an interruption (DEL-33). Callers hold the
    lock."""
    record = _job(ws, job) if job is not None else None
    if record is not None and record.get("deadline") is not None:
        due, at_once = record["deadline"], False
    else:
        due, at_once = deadline(ws, responsibility, table_moment, blocking)
    moment, seq = current_moment(ws)
    call = _append(
        ws,
        {
            "kind": kind,
            "moment": moment,
            "moment_seq": seq,
            "session": current_session(ws),
            "responsibility": responsibility,
            "blocking": blocking,
            "deadline": due,
            "interruption": moment == "live-session" and due == "now",
            "entry": entry,
            "job": job,
            "message": message,
            "status": "open",
            "shown": False,
        },
        CALLS_DIR,
    )
    if at_once:
        _default(ws, call)
    return call


def raise_exception(
    ws: Workspace, responsibility: str, message: str, job: int | None = None, blocking: bool = False
) -> dict:
    """Surface an exception as a call on the GM."""
    with locked(ws):
        return open_call(
            ws,
            kind="exception",
            responsibility=responsibility,
            table_moment=current_moment(ws)[0],
            blocking=blocking,
            job=job,
            message=message,
        )


def answered(ws: Workspace, entry_id: int) -> None:
    """Close the open call on a proposal the GM approved or rejected. Callers hold the lock."""
    for call in _calls(ws):
        if call["entry"] == entry_id and call["status"] == "open":
            call["status"] = "answered"
            _save(ws, call, CALLS_DIR)


def close(ws: Workspace, call_id: int) -> None:
    """Close an open call the GM answered by another gesture (a world-turn occurrence decided).
    Callers hold the lock."""
    call = _read_yaml(ws.root / CALLS_DIR / f"{call_id:06d}.yaml")
    if call["status"] == "open":
        call["status"] = "answered"
        _save(ws, call, CALLS_DIR)


def move_on(ws: Workspace) -> None:
    """The blocking turn or scene moved on: calls and live jobs due now take their safe default.
    ponytail: a Core gesture only; the VTT connector calls it on turn and scene changes."""
    with locked(ws):
        pass_deadline(ws, "now")


def take_break(ws: Workspace) -> list[dict]:
    """The GM signals a break: nothing blocks any more and live jobs due at the break are late.
    Returns the break pile: open calls due at the break, which stay open until answered or the
    moment ends, and every call defaulted since the last break, shown once again (DEL-32)."""
    with locked(ws):
        pass_deadline(ws, "break")
        pile = [
            c
            for c in _calls(ws)
            if (c["status"] == "open" and c["deadline"] == "break")
            or (c["status"] == "defaulted" and not c.get("shown"))
        ]
        for call in pile:
            if call["status"] == "defaulted":
                call["shown"] = True
                _save(ws, call, CALLS_DIR)
        return pile


def pass_deadline(ws: Workspace, gesture: str) -> None:
    """Apply the safe default to what `gesture` makes late: "now" (moving on) the calls and live
    jobs due now; "break" also the live jobs due at the break; "end" (of the moment) every open
    call and live job. Callers hold the lock."""
    late_calls = {"now": ("now",), "break": ("now",), "end": ("now", "break")}[gesture]
    late_jobs = {"now": ("now",), "break": ("now", "break"), "end": ("now", "break")}[gesture]
    for job in _jobs(ws):
        if job.get("deadline") in late_jobs and job["status"] in ("queued", "started"):
            _miss(ws, job)
    for call in _calls(ws):
        if call["status"] == "open" and call["deadline"] in late_calls:
            _default(ws, call)


def interruptions(ws: Workspace, session: int | None = None) -> dict:
    """Interruptions counted at the Core, the same whatever the Surface (MET-06): in total and
    per responsibility, for one live session or all of them."""
    by: dict[str, int] = {}
    for call in _calls(ws):
        if call.get("interruption") and session in (None, call.get("session")):
            by[call["responsibility"]] = by.get(call["responsibility"], 0) + 1
    return {"total": sum(by.values()), "by_responsibility": by}


def _default(ws: Workspace, call: dict, override: int | None = None) -> None:
    """The safe default (DEL-32): a pending proposal is rejected, never applied, so an
    irreversible action never takes effect by default; an exception takes no action. Withdrawn
    by an entity override (its `add_override` entry), the call is not shown at the break."""
    if call["entry"] is not None:
        entry = read_entry(ws, call["entry"])
        if entry["status"] == "pending":
            entry["status"] = "rejected"
            _save(ws, entry)
    call["status"] = "defaulted" if override is None else "withdrawn"
    _save(ws, call, CALLS_DIR)
    _log_default(ws, call["id"], call["entry"], call["job"], override)


def _miss(ws: Workspace, job: dict) -> None:
    """A live job missed its call's deadline (ARC-28): it takes no further action."""
    if job["status"] == "started":
        job["attempts"][-1].update(outcome="failed", error="missed its deadline")
    job["status"] = "missed"
    _save(ws, job, JOBS_DIR)
    _log_default(ws, None, None, job["id"])


def _log_default(
    ws: Workspace, call: int | None, entry: int | None, job: int | None, override: int | None = None
) -> None:
    moment, seq = current_moment(ws)
    _append(
        ws,
        {
            "kind": "safe_default",
            "moment": moment,
            "moment_seq": seq,
            "call": call,
            "entry": entry,
            "job": job,
            "override": override,
        },
        LOG_DIR,
    )


def _calls(ws: Workspace) -> list[dict]:
    return [_read_yaml(p) for p in sorted((ws.root / CALLS_DIR).glob("*.yaml"))]


def _jobs(ws: Workspace) -> list[dict]:
    return [_read_yaml(p) for p in sorted((ws.root / JOBS_DIR).glob("*.yaml"))]


def _job(ws: Workspace, job_id: int) -> dict:
    return _read_yaml(ws.root / JOBS_DIR / f"{job_id:06d}.yaml")
