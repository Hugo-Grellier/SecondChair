"""Delegation (03-delegation.md): the delegation table, the current moment, the action log,
approvals and undo. The Core wraps every delegated action here (ARC-04, DEL-18).

Workspace files (docs/contracts/workspace-layout.md): `delegation.yaml`, `moment.yaml` and one
YAML file per action log entry in `action-log/` (docs/contracts/action-log-entry.schema.json).
"""

import fcntl
import functools
import inspect
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
    with _locked(ws):
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
    if "agent" in signature.parameters:
        raise RegistrationError(f"{tool.name}: `agent` is reserved for the Core")

    @functools.wraps(tool.fn)
    def run(*args: Any, agent: str, **kwargs: Any) -> ActionResult:
        with _for_agent():
            return act(ws, tool, agent, lambda: tool.fn(*args, **kwargs))

    agent_param = inspect.Parameter("agent", inspect.Parameter.KEYWORD_ONLY, annotation=str)
    run.__signature__ = signature.replace(  # ty: ignore[unresolved-attribute]
        parameters=[*signature.parameters.values(), agent_param], return_annotation=ActionResult
    )
    del run.__wrapped__  # the MCP schema comes from __signature__, not from the block's fn
    run.__doc__ = (
        f"{inspect.getdoc(tool.fn) or ''}\n\n`agent`: your name as an agent, recorded in the "
        "action log for traceability only."
    )
    return run


def act(ws: Workspace, tool: Tool, agent: str, describe: Callable[[], Change]) -> ActionResult:
    """Take one delegated action (ARC-04): refused at manual, held at propose, applied above."""
    with _locked(ws):
        moment, seq = current_moment(ws)
        level = effective_level(ws, tool.responsibility, moment, tool.reversible)
        if level == "manual":
            raise DelegationError(
                f"{tool.responsibility} is at manual in {moment}: agents take no action, "
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
            "runner_configuration": None,  # job work comes with the runner (#32)
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
    with _locked(ws):
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
    with _locked(ws):
        entry = _pending(ws, entry_id)
        _interaction(ws, "reject", entry_id, channel, authenticated, None, reason)
        entry["status"] = "rejected"
        _save(ws, entry)
        return entry


def undo(ws: Workspace, entry_id: int, reason: str, channel: str, authenticated: bool) -> dict:
    """Undo an applied reversible action of the current moment (DEL-25, DEL-26)."""
    _check_reason(reason)
    with _locked(ws):
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


def approve_proposal(ws: Workspace) -> Callable[..., ActionResult]:
    """The agent relay of a GM approval (DEL-28), served by the Core next to block tools."""

    def approve_proposal(entry: int, gm_words: str) -> ActionResult:
        """Approve a pending reversible action on the GM's behalf. Only when the GM approved it
        in conversation: quote the GM's exact words. Logged as approved "via agent"."""
        with _for_agent():
            approve(ws, entry, "via agent", authenticated=False, quote=gm_words)
        return {"entry": entry, "status": "applied"}

    return approve_proposal


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
    if parts and parts[0] in (CONFIG_FILE, TABLE_FILE, MOMENT_FILE, LOG_DIR, STATE_DIR):
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


def _append(ws: Workspace, entry: dict) -> dict:
    """Give the entry the next id and its real time, and write it. Callers hold the lock."""
    (ws.root / LOG_DIR).mkdir(exist_ok=True)
    ids = [int(p.stem) for p in (ws.root / LOG_DIR).glob("*.yaml") if p.stem.isdigit()]
    entry = {"id": max(ids, default=0) + 1, "at": datetime.now(UTC).isoformat(), **entry}
    _save(ws, entry)
    return entry


def _save(ws: Workspace, entry: dict) -> None:
    _write(_log_path(ws, entry["id"]), yaml.safe_dump(entry, sort_keys=False, allow_unicode=True))


def _entry(ws: Workspace, entry_id: int, kind: str) -> dict:
    path = _log_path(ws, entry_id)
    if not path.is_file():
        raise DelegationError(f"No action log entry {entry_id}.")
    entry = _read_yaml(path)
    if entry.get("kind") != kind:
        raise DelegationError(f"Entry {entry_id} is not a delegated action.")
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


@contextmanager
def _locked(ws: Workspace) -> Generator[None]:
    """One writer at a time across `serve` and the CLI.
    ponytail: one workspace-wide lock; finer locks if agents ever queue behind it."""
    lock = ws.root / STATE_DIR / "delegation.lock"
    lock.parent.mkdir(exist_ok=True)
    with lock.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


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
