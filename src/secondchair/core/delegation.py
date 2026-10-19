"""Delegation (03-delegation.md): the delegation table, the current moment, the action log,
approvals and undo. The Core wraps every delegated action here (ARC-04, DEL-18).

Workspace files (docs/contracts/workspace-layout.md): `delegation.yaml`, `moment.yaml` and one
YAML file per action log entry in `action-log/` (docs/contracts/action-log-entry.schema.json).
"""

import fcntl
import functools
import inspect
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import yaml
from mcp.server.mcpserver.exceptions import ToolError

from secondchair.core.tools import (
    RESPONSIBILITIES,
    Change,
    Contradiction,
    RegistrationError,
    Tool,
)
from secondchair.core.workspace import CONFIG_FILE, STATE_DIR, Workspace, WorkspaceError

LEVELS = ("manual", "propose", "act-then-review", "autonomous")  # DEL-02, loosest last
MOMENTS = ("prep", "live-session", "between-sessions")  # DEL-03
REASONS = ("contradiction", "rules", "tone", "other")  # DEL-26

TABLE_FILE = "delegation.yaml"
MOMENT_FILE = "moment.yaml"
LOG_DIR = "action-log"
JOBS_DIR = "jobs"
CALLS_DIR = "calls"

# The base profiles (DEL-06), in RESPONSIBILITIES order; every cell's deadline mode is auto.
_PROFILE_LEVELS = {
    "read": ("manual",) * 8,
    "prep": (
        "act-then-review",
        "act-then-review",
        "act-then-review",
        "manual",
        "act-then-review",
        "propose",
        "propose",
        "propose",
    ),
    "play": (
        "propose",
        "propose",
        "act-then-review",
        "act-then-review",
        "act-then-review",
        "propose",
        "propose",
        "propose",
    ),
}
BASE_PROFILES = {
    name: {
        r: {"level": level, "deadline": "auto"}
        for r, level in zip(RESPONSIBILITIES, levels, strict=True)
    }
    for name, levels in _PROFILE_LEVELS.items()
}
# A new campaign's table (DEL-06a).
SEED = {"prep": "prep", "live-session": "play", "between-sessions": "prep"}


class DelegationError(Exception):
    """A delegated action, approval, undo or moment change the Core refuses."""


def seed(root: Path) -> None:
    """Write a new campaign's delegation table and its first moment, prep."""
    table = {moment: BASE_PROFILES[profile] for moment, profile in SEED.items()}
    (root / TABLE_FILE).write_text(yaml.safe_dump(table, sort_keys=False))
    _write_moment(root, "prep", 1)


# The current moment


def current_moment(ws: Workspace) -> tuple[str, int]:
    """The current moment and its sequence number, which grows at every moment change."""
    data = _read_yaml(ws.root / MOMENT_FILE)
    if data.get("moment") not in MOMENTS or type(data.get("seq")) is not int:
        raise WorkspaceError(f"{ws.root / MOMENT_FILE}: expected a moment and an integer seq.")
    return data["moment"], data["seq"]


def change_moment(ws: Workspace, moment: str) -> bool:
    """Open `moment`; False if it is already the current one. Freezes the previous moment's log
    (DEL-25). Only an authenticated Surface may call this (DEL-03a)."""
    if moment not in MOMENTS:
        raise DelegationError(f"Unknown moment {moment!r}; expected one of {', '.join(MOMENTS)}.")
    with locked(ws):
        current, seq = current_moment(ws)
        if current == moment:
            return False
        if current == "live-session" and moment != "between-sessions":  # DEL-03b
            raise DelegationError("A live session is open; end it (between-sessions) first.")
        _write_moment(ws.root, moment, seq + 1)
        return True


def _write_moment(root: Path, moment: str, seq: int) -> None:
    _write(root / MOMENT_FILE, yaml.safe_dump({"moment": moment, "seq": seq}, sort_keys=False))


# Levels


def effective_level(ws: Workspace, responsibility: str, moment: str, reversible: bool) -> str:
    """The table cell for the moment (DEL-12; no entity override yet). An irreversible action is
    held at propose (DEL-09)."""
    cell = _read_yaml(ws.root / TABLE_FILE).get(moment, {}).get(responsibility, {})
    level = cell.get("level") if isinstance(cell, dict) else None
    if level not in LEVELS:
        raise WorkspaceError(
            f"{ws.root / TABLE_FILE}: {moment} / {responsibility} needs a level among "
            f"{', '.join(LEVELS)}."
        )
    return level if reversible else min(level, "propose", key=LEVELS.index)


# Delegated actions


class ActionResult(TypedDict):
    entry: int
    status: str  # "applied" or "pending"


def wrap(ws: Workspace, tool: Tool) -> Callable[..., ActionResult]:
    """The MCP function for a delegated action: the block's `fn` describes the change, the Core
    checks the effective level, logs it, then applies it or holds it for approval."""
    signature = inspect.signature(tool.fn)
    for reserved in ("agent", "job"):
        if reserved in signature.parameters:
            raise RegistrationError(f"{tool.name}: `{reserved}` is reserved for the Core")

    @functools.wraps(tool.fn)
    def run(*args: Any, agent: str, job: int | None = None, **kwargs: Any) -> ActionResult:
        with _for_agent():
            return act(ws, tool, agent, lambda: tool.fn(*args, **kwargs), job)

    added = [
        inspect.Parameter("agent", inspect.Parameter.KEYWORD_ONLY, annotation=str),
        inspect.Parameter(
            "job", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=int | None
        ),
    ]
    run.__signature__ = signature.replace(  # ty: ignore[unresolved-attribute]
        parameters=[*signature.parameters.values(), *added], return_annotation=ActionResult
    )
    del run.__wrapped__  # the MCP schema comes from __signature__, not from the block's fn
    run.__doc__ = (
        f"{inspect.getdoc(tool.fn) or ''}\n\n`agent`: your name as an agent, recorded in the "
        "action log for traceability only. `job`: the SecondChair job you are running, if any; "
        "the action is then bound by the delegation table of the job's moment."
    )
    return run


def act(
    ws: Workspace,
    tool: Tool,
    agent: str,
    describe: Callable[[], Change],
    job: int | None = None,
) -> ActionResult:
    """Take one delegated action (ARC-04): refused at manual, held at propose, applied above.
    An action for a started job is bound by the table of the job's moment (ARC-23) and logs the
    job's runner configuration (DEL-24)."""
    with locked(ws):
        moment, seq = current_moment(ws)
        table_moment, runner_configuration = moment, None
        if job is not None:
            from secondchair.core import jobs  # it builds on this module

            record = jobs.read(ws, job)
            if record["status"] != "started":
                raise DelegationError(f"Job {job} is {record['status']}, not started.")
            table_moment = record["moment"]
            runner_configuration = record["attempts"][-1]["runner_configuration"]
        level = effective_level(ws, tool.responsibility, table_moment, tool.reversible)
        if level == "manual":
            raise DelegationError(
                f"{tool.responsibility} is at manual in {table_moment}: agents take no action, "
                "they only answer when asked."
            )
        try:
            change, refusal = describe(), None
        except Contradiction as c:  # logged: a Core-detected contradiction with canon (MET-01)
            change, refusal = Change(path=c.path, after=None), str(c)
        if not isinstance(change, Change):
            raise DelegationError(f"{tool.name} returned {change!r}, not a Change")
        path = _target(ws, change.path)
        entry = {
            "kind": "action",
            "moment": moment,
            "moment_seq": seq,
            "tool": tool.name,
            "responsibility": tool.responsibility,
            "effective_level": level,
            "override_lowered": False,  # no entity override yet (DEL-10..17)
            "reversible": tool.reversible,
            "agent": agent,
            "source": change.source,
            "job": job,
            "runner_configuration": runner_configuration,
            "target": change.path,
            "before": path.read_text() if path.exists() else None,
            "after": change.after,
            "status": "pending" if level == "propose" else "applied",
            "approval": None,
        }
        if refusal is not None:
            entry.update(status="refused", refusal=refusal)
            logged = _append(ws, entry)["id"]
            raise DelegationError(f"Refused, it contradicts canon: {refusal} (entry {logged}).")
        if entry["status"] == "applied":
            _apply(ws, entry, "after")
        return {"entry": _append(ws, entry)["id"], "status": entry["status"]}


# GM interactions (DEL-27): each is its own log entry.


def approve(
    ws: Workspace, entry_id: int, channel: str, authenticated: bool, quote: str | None = None
) -> dict:
    """Approve a pending action (DEL-28): from any Surface for a reversible one, "via agent" only
    with the GM's quoted words, and from an authenticated Surface for an irreversible one."""
    if channel == "via agent" and not (quote and quote.strip()):
        raise DelegationError("An approval relayed by an agent must quote the GM's words.")
    with locked(ws):
        entry = _pending(ws, entry_id)
        if not entry["reversible"] and not authenticated:
            raise DelegationError(
                f"Entry {entry_id} is irreversible: approve it from an authenticated Surface "
                "(the CLI in an interactive terminal)."
            )
        _apply(ws, entry, "after")
        interaction = _interaction(ws, "approve", entry_id, channel, authenticated, quote, None)
        entry["status"] = "applied"
        entry["approval"] = {
            "channel": channel,
            "authenticated": authenticated,
            "quote": quote,
            "interaction": interaction["id"],
        }
        _save(ws, entry)
        return entry


def reject(ws: Workspace, entry_id: int, reason: str, channel: str, authenticated: bool) -> dict:
    """Reject a pending action with a rejection reason (DEL-26)."""
    _check_reason(reason)
    with locked(ws):
        entry = _pending(ws, entry_id)
        _interaction(ws, "reject", entry_id, channel, authenticated, None, reason)
        entry["status"] = "rejected"
        _save(ws, entry)
        return entry


def undo(ws: Workspace, entry_id: int, reason: str, channel: str, authenticated: bool) -> dict:
    """Undo an applied reversible action of the current moment (DEL-25, DEL-26)."""
    _check_reason(reason)
    with locked(ws):
        entry = _entry(ws, entry_id, "action")
        if entry["status"] != "applied":
            raise DelegationError(f"Entry {entry_id} is {entry['status']}, not applied.")
        if not entry["reversible"]:
            raise DelegationError(f"Entry {entry_id} is irreversible and cannot be undone.")
        _check_not_frozen(ws, entry)
        _apply(ws, entry, "before")
        _interaction(ws, "undo", entry_id, channel, authenticated, None, reason)
        entry["status"] = "undone"
        _save(ws, entry)
        return entry


def confirm(
    ws: Workspace,
    target: str,
    promote: Callable[[str], tuple[str, int | None]],
    channel: str,
    authenticated: bool,
) -> dict:
    """Confirm a decision into canon at the GM-decision rank (DEL-29): only from an authenticated
    Surface. `promote` turns the target's content into its confirmed version and names the action
    entry that wrote it; the rewrite is logged as a GM interaction carrying before and after."""
    if not authenticated:
        raise DelegationError(
            "Confirming a GM decision needs an authenticated Surface (an interactive terminal)."
        )
    with locked(ws):
        path = _target(ws, target)
        before = path.read_text()
        after, entry_id = promote(before)
        _write(path, after)
        moment, seq = current_moment(ws)
        return _append(
            ws,
            {
                "kind": "gm_interaction",
                "moment": moment,
                "moment_seq": seq,
                "interaction": "confirm",
                "entry": entry_id,
                "channel": channel,
                "authenticated": authenticated,
                "quote": None,
                "reason": None,
                "target": target,
                "before": before,
                "after": after,
            },
        )


def approve_proposal(ws: Workspace) -> Callable[..., ActionResult]:
    """The agent relay of a GM approval (DEL-28), served by the Core next to block tools."""

    def approve_proposal(entry: int, gm_words: str) -> ActionResult:
        """Approve a pending reversible action on the GM's behalf. Only when the GM approved it
        in conversation: quote the GM's exact words. Logged as approved "via agent"."""
        with _for_agent():
            approve(ws, entry, "via agent", authenticated=False, quote=gm_words)
        return {"entry": entry, "status": "applied"}

    return approve_proposal


# Hand edits (CAN-11): a canon file changed outside the Core.

CANON_DIR = "canon"


def read_log(ws: Workspace) -> tuple[list[dict], list[str]]:
    """The action log entries in id order, and one message per file that is not one."""
    entries, errors = [], []
    for p in sorted((ws.root / LOG_DIR).glob("*.yaml")):
        try:
            entry = _read_yaml(p)
        except WorkspaceError as e:
            errors.append(str(e))
            continue
        if entry.get("id") != (int(p.stem) if p.stem.isdigit() else None):
            errors.append(f"{p}: id {entry.get('id')!r} does not match the file name.")
            continue
        entries.append(entry)
    return entries, errors


def _core_states(entries: list[dict]) -> dict[str, str | None]:
    """Each target's content as the Core last left it, replaying writes in the order they hit
    the workspace: an action when applied (at its approval, if any), an undo, a confirmation,
    a hand edit."""
    by_id = {e["id"]: e for e in entries}
    writes = []
    for e in entries:
        if e.get("kind") == "action" and e.get("status") in ("applied", "undone"):
            when = e["approval"]["interaction"] if e.get("approval") else e["id"]
            writes.append((when, e.get("target"), e.get("after")))
        elif e.get("kind") == "hand_edit" or e.get("interaction") == "confirm":
            writes.append((e["id"], e.get("target"), e.get("after")))
        elif e.get("interaction") == "undo" and e.get("entry") in by_id:
            undone = by_id[e["entry"]]
            writes.append((e["id"], undone.get("target"), undone.get("before")))
    writes.sort(key=lambda w: w[0])
    return {target: content for _, target, content in writes if isinstance(target, str)}


def log_hand_edits(ws: Workspace) -> list[dict]:
    """Log every canon file whose content differs from what the Core last wrote there, at the
    agent-proposal rank (CAN-11). The GM promotes one with `promote`."""
    with locked(ws):
        entries, _ = read_log(ws)
        known = _core_states(entries)
        current = {
            p.relative_to(ws.root).as_posix(): p.read_text()
            for p in sorted((ws.root / CANON_DIR).rglob("*.md"))
            if p.is_file()
        }
        changed = [
            target
            for target in sorted(current.keys() | {t for t, c in known.items() if c is not None})
            if current.get(target) != known.get(target)
        ]
        if not changed:
            return []
        moment, seq = current_moment(ws)
        return [
            _append(
                ws,
                {
                    "kind": "hand_edit",
                    "moment": moment,
                    "moment_seq": seq,
                    "target": target,
                    "before": known.get(target),
                    "after": current.get(target),
                    "rank": "agent_proposal",
                    "promotion": None,
                },
            )
            for target in changed
        ]


def promote(ws: Workspace, entry_id: int, channel: str, authenticated: bool) -> dict:
    """Make a hand edit a GM decision: one gesture on an authenticated Surface (CAN-11, DEL-29).
    Refused once the file changed again: the newer hand edit is the one to promote."""
    if not authenticated:
        raise DelegationError(
            "Promoting a hand edit to a GM decision needs an authenticated Surface "
            "(the CLI in an interactive terminal)."
        )
    with locked(ws):
        entry = _entry(ws, entry_id, "hand_edit")
        if entry["rank"] == "gm_decision":
            raise DelegationError(f"Entry {entry_id} is already a GM decision.")
        path = ws.root / entry["target"]
        if (path.read_text() if path.exists() else None) != entry["after"]:
            raise DelegationError(
                f"{entry['target']} changed since entry {entry_id}; promote the newer hand edit."
            )
        interaction = _interaction(ws, "promote", entry_id, channel, authenticated, None, None)
        entry["rank"] = "gm_decision"
        entry["promotion"] = interaction["id"]
        _save(ws, entry)
        return entry


def check(ws: Workspace) -> list[str]:
    """One message per invalid delegation table, moment or action log file."""
    errors = read_log(ws)[1]
    try:
        current_moment(ws)
    except WorkspaceError as e:
        errors.append(str(e))
    try:
        for moment in MOMENTS:
            for responsibility in RESPONSIBILITIES:
                effective_level(ws, responsibility, moment, reversible=True)
    except WorkspaceError as e:
        errors.append(str(e))
    return errors


def _check_reason(reason: str) -> None:
    if reason not in REASONS:
        raise DelegationError(f"Rejection reason {reason!r}: expected one of {', '.join(REASONS)}.")


def _pending(ws: Workspace, entry_id: int) -> dict:
    entry = _entry(ws, entry_id, "action")
    if entry["status"] != "pending":
        raise DelegationError(f"Entry {entry_id} is {entry['status']}, not pending.")
    _check_not_frozen(ws, entry)
    return entry


def _check_not_frozen(ws: Workspace, entry: dict) -> None:
    if entry["moment_seq"] != current_moment(ws)[1]:
        raise DelegationError(
            f"Entry {entry['id']} belongs to an earlier {entry['moment']} moment, whose log is "
            "frozen: only a correction or a retcon can change it now."
        )


def _interaction(
    ws: Workspace,
    interaction: str,
    entry_id: int,
    channel: str,
    authenticated: bool,
    quote: str | None,
    reason: str | None,
) -> dict:
    moment, seq = current_moment(ws)
    return _append(
        ws,
        {
            "kind": "gm_interaction",
            "moment": moment,
            "moment_seq": seq,
            "interaction": interaction,
            "entry": entry_id,
            "channel": channel,
            "authenticated": authenticated,
            "quote": quote,
            "reason": reason,
        },
    )


# Workspace effects and the log files


def _target(ws: Workspace, relative: str) -> Path:
    path = (ws.root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(ws.root.resolve()):
        raise DelegationError(f"{relative!r} is outside the campaign workspace.")
    parts = path.relative_to(ws.root.resolve()).parts
    if parts and parts[0] in (
        CONFIG_FILE,
        TABLE_FILE,
        MOMENT_FILE,
        LOG_DIR,
        JOBS_DIR,
        CALLS_DIR,
        STATE_DIR,
    ):
        raise DelegationError(f"{relative!r} belongs to the Core; no delegated action writes it.")
    return path


def _apply(ws: Workspace, entry: dict, state: str) -> None:
    """Bring the target to the entry's `before` or `after` state, refusing if the file is no
    longer in the other state (a hand edit since, CAN-11): nothing is overwritten unseen."""
    path = _target(ws, entry["target"])
    expected = entry["after" if state == "before" else "before"]
    current = path.read_text() if path.exists() else None
    if current != expected:
        raise DelegationError(
            f"{entry['target']} changed since entry {entry.get('id')} was logged; "
            "nothing was written."
        )
    content = entry[state]
    if content is None:
        path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, content)


def _log_path(ws: Workspace, entry_id: int) -> Path:
    return ws.root / LOG_DIR / f"{entry_id:06d}.yaml"


def _append(ws: Workspace, entry: dict, directory: str = LOG_DIR) -> dict:
    """Give the record the next id in `directory` (the action log by default) and its real
    time, and write it. Callers hold the lock."""
    (ws.root / directory).mkdir(exist_ok=True)
    ids = [int(p.stem) for p in (ws.root / directory).glob("*.yaml") if p.stem.isdigit()]
    entry = {"id": max(ids, default=0) + 1, "at": datetime.now(UTC).isoformat(), **entry}
    _save(ws, entry, directory)
    return entry


def _save(ws: Workspace, entry: dict, directory: str = LOG_DIR) -> None:
    path = ws.root / directory / f"{entry['id']:06d}.yaml"
    _write(path, yaml.safe_dump(entry, sort_keys=False, allow_unicode=True))


def _entry(ws: Workspace, entry_id: int, kind: str) -> dict:
    path = _log_path(ws, entry_id)
    if not path.is_file():
        raise DelegationError(f"No action log entry {entry_id}.")
    entry = _read_yaml(path)
    if entry.get("kind") != kind:
        what = "a delegated action" if kind == "action" else "a hand edit"
        raise DelegationError(f"Entry {entry_id} is not {what}.")
    return entry


def read_entry(ws: Workspace, entry_id: int) -> dict:
    return _read_yaml(_log_path(ws, entry_id))


@contextmanager
def _for_agent() -> Generator[None]:
    """Refusals reach the agent with their message, not as a crash (whose text MCP hides)."""
    try:
        yield
    except (DelegationError, WorkspaceError, ValueError) as e:
        raise ToolError(str(e)) from e


_held = threading.local()


@contextmanager
def locked(ws: Workspace) -> Generator[None]:
    """One writer at a time across `serve` and the CLI; reentrant within a thread, since an
    action reads the index, which may log hand edits.
    ponytail: one workspace-wide lock; finer locks if agents ever queue behind it."""
    held: set[Path] = _held.__dict__.setdefault("roots", set())
    root = ws.root.resolve()
    if root in held:
        yield
        return
    lock = ws.root / STATE_DIR / "delegation.lock"
    lock.parent.mkdir(exist_ok=True)
    with lock.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        held.add(root)
        try:
            yield
        finally:
            held.discard(root)


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise WorkspaceError(f"{path} is missing.")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise WorkspaceError(f"{path} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise WorkspaceError(f"{path} must be a YAML mapping.")
    return data
