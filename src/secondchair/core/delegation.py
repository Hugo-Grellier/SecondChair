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

from secondchair.core import vtt
from secondchair.core.tools import (
    RESPONSIBILITIES,
    Change,
    Contradiction,
    RegistrationError,
    Tool,
    VttAction,
)
from secondchair.core.workspace import CONFIG_FILE, STATE_DIR, Workspace, WorkspaceError

LEVELS = ("manual", "propose", "act-then-review", "autonomous")  # DEL-02, loosest last
MOMENTS = ("prep", "live-session", "between-sessions")  # DEL-03
REASONS = ("contradiction", "rules", "tone", "other")  # DEL-26
OVERRIDABLE = ("rules_and_combat", "npcs", "disclosure")  # DEL-11

TABLE_FILE = "delegation.yaml"
MOMENT_FILE = "moment.yaml"
LOG_DIR = "action-log"
JOBS_DIR = "jobs"
CALLS_DIR = "calls"
OBSERVATIONS_DIR = "observations"
OCCURRENCES_DIR = "occurrences"  # the world-turn's occurrences (world.py)
WORLD_FILE = "living-world.yaml"  # the world-turn's cursor
FRICTIONS_DIR = "frictions"

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


def current_session(ws: Workspace) -> int | None:
    """The open live session's id (DEL-03), None outside a live session."""
    return last_session(ws) if current_moment(ws)[0] == "live-session" else None


def last_session(ws: Workspace) -> int:
    """The last live session's id, open or ended; 0 before the first."""
    return _read_yaml(ws.root / MOMENT_FILE).get("session", 0)


def current_moment(ws: Workspace) -> tuple[str, int]:
    """The current moment and its sequence number, which grows at every moment change."""
    data = _read_yaml(ws.root / MOMENT_FILE)
    if data.get("moment") not in MOMENTS or type(data.get("seq")) is not int:
        raise WorkspaceError(f"{ws.root / MOMENT_FILE}: expected a moment and an integer seq.")
    return data["moment"], data["seq"]


def change_moment(ws: Workspace, moment: str, notes: str | None = None) -> bool:
    """Open `moment`; False if it is already the current one. The end of a moment is the last
    deadline of its calls (DEL-30, DEL-32), then its log is frozen (DEL-25). Opening a live
    session gives it the next session id; ending one queues "wrap a session" (DEL-03, DEL-04).
    `notes`, the GM's notes for the session ending, become the wrap job's Source. Only an
    authenticated Surface may call this (DEL-03a)."""
    from secondchair.core import calls, capture, jobs  # they build on this module

    if moment not in MOMENTS:
        raise DelegationError(f"Unknown moment {moment!r}; expected one of {', '.join(MOMENTS)}.")
    with locked(ws):
        current, seq = current_moment(ws)
        if current == moment:
            return False
        if current == "live-session" and moment != "between-sessions":  # DEL-03b
            raise DelegationError("A live session is open; end it (between-sessions) first.")
        session = _read_yaml(ws.root / MOMENT_FILE).get("session", 0)
        calls.pass_deadline(ws, "end")
        ended = current_session(ws)
        _write_moment(ws.root, moment, seq + 1, session + (moment == "live-session"))
    if ended is not None:
        jobs.queue(
            ws,
            playbook=capture.PLAYBOOK,
            inputs={"session": str(ended), **({"notes": notes} if notes else {})},
            expected_output="The session's candidate facts consolidated into canon.",
            responsibility="memory",
            tier="standard",
        )
    return True


def _write_moment(root: Path, moment: str, seq: int, session: int = 0) -> None:
    data = {"moment": moment, "seq": seq, "session": session}
    _write(root / MOMENT_FILE, yaml.safe_dump(data, sort_keys=False))


# Levels


def effective_level(
    ws: Workspace, responsibility: str, moment: str, reversible: bool, entity: str | None = None
) -> str:
    """The table cell for the moment, lowered by the acting entity's overrides (DEL-12). An
    irreversible action is held at propose (DEL-09)."""
    level = _cell(ws, moment, responsibility).get("level")
    if level not in LEVELS:
        raise WorkspaceError(
            f"{ws.root / TABLE_FILE}: {moment} / {responsibility} needs a level among "
            f"{', '.join(LEVELS)}."
        )
    levels = [level] if reversible else [level, "propose"]
    levels += [
        o["level"]
        for o in overrides(ws)
        if entity is not None
        and (o["entity"], o["responsibility"]) == (entity, responsibility)
        and o["moment"] in (None, moment)
    ]
    return min(levels, key=LEVELS.index)


def _cell(ws: Workspace, moment: str, responsibility: str) -> dict:
    cell = _read_yaml(ws.root / TABLE_FILE).get(moment, {}).get(responsibility, {})
    return cell if isinstance(cell, dict) else {}


# Delegated actions


class ActionResult(TypedDict):
    entry: int
    status: str  # "applied", "pending", or "rejected" by a safe default at once (DEL-31)


def wrap(ws: Workspace, tool: Tool) -> Callable[..., ActionResult]:
    """The MCP function for a delegated action: the block's `fn` describes the change, the Core
    checks the effective level, logs it, then applies it or holds it for approval."""
    signature = inspect.signature(tool.fn)
    for reserved in ("agent", "job", "blocking"):
        if reserved in signature.parameters:
            raise RegistrationError(f"{tool.name}: `{reserved}` is reserved for the Core")

    @functools.wraps(tool.fn)
    def run(
        *args: Any, agent: str, job: int | None = None, blocking: bool = False, **kwargs: Any
    ) -> ActionResult:
        with _for_agent():
            return act(ws, tool, agent, lambda: tool.fn(*args, **kwargs), job, blocking)

    added = [
        inspect.Parameter("agent", inspect.Parameter.KEYWORD_ONLY, annotation=str),
        inspect.Parameter(
            "job", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=int | None
        ),
        inspect.Parameter(
            "blocking", inspect.Parameter.KEYWORD_ONLY, default=False, annotation=bool
        ),
    ]
    run.__signature__ = signature.replace(  # ty: ignore[unresolved-attribute]
        parameters=[*signature.parameters.values(), *added], return_annotation=ActionResult
    )
    del run.__wrapped__  # the MCP schema comes from __signature__, not from the block's fn
    run.__doc__ = (
        f"{inspect.getdoc(tool.fn) or ''}\n\n`agent`: your name as an agent, recorded in the "
        "action log for traceability only. `job`: the SecondChair job you are running, if any; "
        "the action is then bound by the delegation table of the job's moment. `blocking`: true "
        "when the table is waiting on this action to go on with the current turn or scene; a "
        "proposal then calls on the GM at once instead of at the next break."
    )
    return run


def wrap_read(fn: Callable[..., Any]) -> Callable[..., Any]:
    """The MCP function for a read: its refusals reach the agent with their message."""

    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> Any:
        with _for_agent():
            return fn(*args, **kwargs)

    return run


def act(
    ws: Workspace,
    tool: Tool,
    agent: str,
    describe: Callable[[], Change],
    job: int | None = None,
    blocking: bool = False,
    occurrence: str | None = None,
    hold: str | None = None,
) -> ActionResult:
    """Take one delegated action (ARC-04): refused at manual, held at propose as a call on the
    GM (DEL-30), applied above. An action for a started job is bound by the table of the job's
    moment (ARC-23), logs the job's runner configuration (DEL-24) and blocks as the job does.
    `hold` holds it at propose whatever the level, the call carrying it as its message (a
    wrap's contradiction or blocking question, CAP-10)."""
    from secondchair.core import calls

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
            blocking = record.get("blocking", False)
        cell = effective_level(ws, tool.responsibility, table_moment, tool.reversible)
        if cell == "manual":
            raise DelegationError(
                f"{tool.responsibility} is at manual in {table_moment}: agents take no action, "
                "they only answer when asked."
            )
        try:
            change, refusal = describe(), None
        except Contradiction as c:  # logged: a Core-detected contradiction with canon (MET-01)
            change, refusal = Change(path=c.path, after=None), str(c)
        entity = getattr(change, "entity", None)
        if entity is not None and not isinstance(entity, str):
            raise DelegationError(f"{tool.name}: the acting entity must be an entity id")
        level = effective_level(ws, tool.responsibility, table_moment, tool.reversible, entity)
        lowered = level != cell
        if hold is not None:
            level = min(level, "propose", key=LEVELS.index)
        if level == "manual":
            raise DelegationError(
                f"An entity override sets {tool.responsibility} at manual for {entity}: agents "
                "take no action for it, they only answer when asked."
            )
        if isinstance(change, VttAction):
            # The VTT reports the state before; at propose it is known only once approved.
            effect = {"op": change.op, "target": change.target, "before": None}
            effect["after"] = change.params
        elif isinstance(change, Change):
            path = _target(ws, change.path)
            effect = {"target": change.path, "before": path.read_text() if path.exists() else None}
            effect["after"] = change.after
        else:
            raise DelegationError(f"{tool.name} returned {change!r}, not a Change or a VttAction")
        entry = {
            "kind": "action",
            "moment": moment,
            "moment_seq": seq,
            "tool": tool.name,
            "responsibility": tool.responsibility,
            "effective_level": level,
            "override_lowered": lowered,
            "entity": entity,
            "reversible": tool.reversible,
            "agent": agent,
            "source": change.source,
            "job": job,
            "runner_configuration": runner_configuration,
            **effect,
            "status": "pending" if level == "propose" else "applied",
            "approval": None,
            **({"occurrence": occurrence} if occurrence is not None else {}),
        }
        if refusal is not None:
            entry.update(status="refused", refusal=refusal)
            logged = _append(ws, entry)["id"]
            raise DelegationError(f"Refused, it contradicts canon: {refusal} (entry {logged}).")
        if entry["status"] == "applied":
            try:
                _apply(ws, entry, "after")
            except DelegationError as e:
                if "op" not in entry:
                    raise
                # A failed action (ARC-09): logged, counted, and reported to the agent.
                failed = _append(ws, {**entry, "status": "failed", "error": str(e)})
                _call_if_ceiling(ws, failed, e, table_moment, blocking)
                raise DelegationError(f"Failed action, logged as entry {failed['id']}: {e}") from e
        logged = _append(ws, entry)
        if entry["status"] == "pending":
            calls.open_call(
                ws,
                kind="proposal",
                responsibility=tool.responsibility,
                table_moment=table_moment,
                blocking=blocking,
                entry=logged["id"],
                job=job,
                message=hold,
            )
            logged = read_entry(ws, logged["id"])  # a safe default may have rejected it at once
        return {"entry": logged["id"], "status": logged["status"]}


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
        try:
            _apply(ws, entry, "after")
        except DelegationError as e:
            if "op" not in entry:
                raise
            entry.update(status="failed", error=str(e))  # a failed action, as in `act`
            _save(ws, entry)
            _answered(ws, entry_id)  # the GM answered; the action failed
            # The GM is answering now: the refusal is held for the break.
            _call_if_ceiling(ws, entry, e, entry["moment"], False)
            raise DelegationError(f"Failed action, entry {entry_id}: {e}") from e
        interaction = _interaction(ws, "approve", entry_id, channel, authenticated, quote, None)
        _answered(ws, entry_id)
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
        _answered(ws, entry_id)
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


# Entity overrides (DEL-10..17), stored in the delegation table under `overrides`.


def overrides(ws: Workspace) -> list[dict]:
    """Every entity override: `entity`, `responsibility`, `level`, and `moment` (null for every
    moment)."""
    found = _read_yaml(ws.root / TABLE_FILE).get("overrides") or []
    if not isinstance(found, list) or not all(
        isinstance(o, dict)
        and sorted(o) == ["entity", "level", "moment", "responsibility"]
        and isinstance(o["entity"], str)
        and o["responsibility"] in OVERRIDABLE
        and o["level"] in LEVELS
        and o["moment"] in (None, *MOMENTS)
        for o in found
    ):
        raise WorkspaceError(
            f"{ws.root / TABLE_FILE}: overrides must be a list of {{entity, responsibility, "
            f"level, moment}}, the responsibility one of {', '.join(OVERRIDABLE)}."
        )
    return found


def add_override(
    ws: Workspace,
    entity: str,
    responsibility: str,
    level: str,
    moment: str | None,
    channel: str,
    authenticated: bool,
    quote: str | None = None,
) -> dict:
    """Tighten one acting entity's level (DEL-11..14): accepted from any Surface, an agent relay
    quoting the GM included, and in force at once. It never loosens: over an override of the
    same entity, responsibility and moment, the lower level stays. Pending calls and queued jobs
    of that entity for that responsibility are withdrawn with their safe default (DEL-16)."""
    if responsibility not in OVERRIDABLE:
        raise DelegationError(
            f"{responsibility} takes no entity override; only {', '.join(OVERRIDABLE)} do."
        )
    if level not in LEVELS:
        raise DelegationError(f"Level {level!r}: expected one of {', '.join(LEVELS)}.")
    if moment not in (None, *MOMENTS):
        raise DelegationError(f"Unknown moment {moment!r}; expected one of {', '.join(MOMENTS)}.")
    if channel == "via agent" and not (quote and quote.strip()):
        raise DelegationError("An override relayed by an agent must quote the GM's words.")
    with locked(ws):
        if entity not in {p.stem for p in (ws.root / CANON_DIR / "entities").glob("*.md")}:
            raise DelegationError(f"No entity {entity!r} in canon.")
        found = overrides(ws)
        key = (entity, responsibility, moment)
        same = [o for o in found if (o["entity"], o["responsibility"], o["moment"]) == key]
        override = {"entity": entity, "responsibility": responsibility, "level": level}
        override["moment"] = moment
        if same:
            override = min(same[0], override, key=lambda o: LEVELS.index(o["level"]))
            found.remove(same[0])
        _write_overrides(ws, [*found, override])
        interaction = _interaction(
            ws, "add_override", None, channel, authenticated, quote, None, override=override
        )
        _withdraw(ws, override, interaction["id"])
        return interaction


def remove_override(
    ws: Workspace,
    entity: str,
    responsibility: str,
    moment: str | None,
    channel: str,
    authenticated: bool,
) -> dict:
    """Loosen: remove an override, only from an authenticated Surface (DEL-14)."""
    if not authenticated:
        raise DelegationError(
            "Removing an entity override loosens a level: do it from an authenticated Surface "
            "(the CLI in an interactive terminal)."
        )
    with locked(ws):
        found = overrides(ws)
        key = (entity, responsibility, moment)
        same = [o for o in found if (o["entity"], o["responsibility"], o["moment"]) == key]
        if not same:
            where = f"in {moment}" if moment else "for every moment"
            raise DelegationError(f"No {responsibility} override for {entity} {where}.")
        found.remove(same[0])
        _write_overrides(ws, found)
        return _interaction(
            ws, "remove_override", None, channel, authenticated, None, None, override=same[0]
        )


def merge_overrides(ws: Workspace, survivor: str, merged: str) -> None:
    """Entities merged at the wrap: `merged`'s overrides follow `survivor`, and where both hold
    one for the same responsibility and moment, the most restrictive wins (DEL-17)."""
    with locked(ws):
        kept: dict[tuple, dict] = {}
        for found in overrides(ws):
            o = {**found, "entity": survivor} if found["entity"] == merged else found
            key = (o["entity"], o["responsibility"], o["moment"])
            kept[key] = min(kept.get(key, o), o, key=lambda x: LEVELS.index(x["level"]))
        _write_overrides(ws, list(kept.values()))


def override_tool(ws: Workspace) -> Callable[..., dict[str, Any]]:
    """The agent relay of a GM override (DEL-14), served by the Core next to block tools."""

    def add_entity_override(
        entity: str, responsibility: str, level: str, gm_words: str, moment: str | None = None
    ) -> dict[str, Any]:
        """Lower the delegation level for one acting entity (an NPC who speaks, a creature that
        strikes) on npcs, rules_and_combat or disclosure, when the GM asked for it in
        conversation: quote the GM's exact words. `level`: manual, propose, act-then-review or
        autonomous; it never raises the level. `moment`: prep, live-session or
        between-sessions to restrict it to one moment, else every moment. Only the GM can
        remove it, from an authenticated Surface."""
        with _for_agent():
            interaction = add_override(
                ws, entity, responsibility, level, moment, "via agent", False, gm_words
            )
        return {"entry": interaction["id"], "override": interaction["override"]}

    return add_entity_override


def _write_overrides(ws: Workspace, found: list[dict]) -> None:
    table = _read_yaml(ws.root / TABLE_FILE)
    table.pop("overrides", None)
    if found:
        table["overrides"] = found
    _write(ws.root / TABLE_FILE, yaml.safe_dump(table, sort_keys=False, allow_unicode=True))


def _withdraw(ws: Workspace, override: dict, interaction: int) -> None:
    """Withdraw the entity's open calls and queued jobs the override covers with their safe
    default, logged and not shown at the break (DEL-16). Callers hold the lock."""
    from secondchair.core import calls

    def covered(entity: str | None, responsibility: str, moment: str) -> bool:
        return (entity, responsibility) == (override["entity"], override["responsibility"]) and (
            override["moment"] in (None, moment)
        )

    jobs = {job["id"]: job for job in calls._jobs(ws)}
    for job in jobs.values():
        if job["status"] == "queued" and covered(
            job.get("entity"), job["responsibility"], job["moment"]
        ):
            job["status"] = "withdrawn"
            _save(ws, job, JOBS_DIR)
            calls._log_default(ws, None, None, job["id"], interaction)
    for call in calls._calls(ws):
        job = jobs.get(call["job"]) if call["job"] is not None else None
        if call["entry"] is not None:
            entity = read_entry(ws, call["entry"]).get("entity")
        else:
            entity = job.get("entity") if job else None
        moment = job["moment"] if job else call["moment"]
        if call["status"] == "open" and covered(entity, call["responsibility"], moment):
            calls._default(ws, call, interaction)


def _call_if_ceiling(
    ws: Workspace, entry: dict, error: DelegationError, table_moment: str, blocking: bool
) -> None:
    """A ceiling refusal is a failed action and a call on the GM (DEL-20). Callers hold the lock."""
    from secondchair.core import calls

    if isinstance(error.__cause__, vtt.CeilingRefusal):
        calls.open_call(
            ws,
            kind="ceiling_refusal",
            responsibility=entry["responsibility"],
            table_moment=table_moment,
            blocking=blocking,
            entry=entry["id"],
            job=entry.get("job"),
            message=str(error),
        )


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
    """One message per invalid delegation table, moment, action log, job, call, occurrence,
    candidate or time file."""
    from secondchair.core import calls, capture

    errors = read_log(ws)[1]
    for d in (JOBS_DIR, CALLS_DIR, OCCURRENCES_DIR, capture.CAPTURE_DIR):
        for p in sorted((ws.root / d).glob("*.yaml")):
            try:
                _read_yaml(p)
            except WorkspaceError as e:
                errors.append(str(e))
    if (ws.root / capture.TIME_FILE).exists():
        try:
            _read_yaml(ws.root / capture.TIME_FILE)
        except WorkspaceError as e:
            errors.append(str(e))
    try:
        current_moment(ws)
    except WorkspaceError as e:
        errors.append(str(e))
    try:
        overrides(ws)
        for moment in MOMENTS:
            for responsibility in RESPONSIBILITIES:
                effective_level(ws, responsibility, moment, reversible=True)
                calls.deadline(ws, responsibility, moment, blocking=False)
    except WorkspaceError as e:
        errors.append(str(e))
    return errors


def _answered(ws: Workspace, entry_id: int) -> None:
    from secondchair.core import calls

    calls.answered(ws, entry_id)


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
    entry_id: int | None,
    channel: str,
    authenticated: bool,
    quote: str | None,
    reason: str | None,
    **extra: Any,
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
            **extra,
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
        OBSERVATIONS_DIR,
        OCCURRENCES_DIR,
        WORLD_FILE,
        FRICTIONS_DIR,
        STATE_DIR,
    ):
        raise DelegationError(f"{relative!r} belongs to the Core; no delegated action writes it.")
    return path


def _apply(ws: Workspace, entry: dict, state: str) -> None:
    """Bring the target to the entry's `before` or `after` state, refusing if the file is no
    longer in the other state (a hand edit since, CAN-11): nothing is overwritten unseen."""
    if "op" in entry:  # a VTT action: the connector checks and takes it
        other = "after" if state == "before" else "before"
        try:
            # The undo is the GM's own gesture, which the VTT's ceiling does not bound (DEL-19).
            level = entry["effective_level"] if state == "after" else None
            before, after = vtt.perform(
                entry["op"], entry["target"], entry[state], entry[other], level
            )
        except vtt.VttError as e:
            raise DelegationError(str(e)) from e
        if state == "after":  # the state the VTT reports, not the one asked for
            entry["before"], entry["after"] = before, after
        return
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
