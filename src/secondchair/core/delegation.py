"""Delegation (03-delegation.md): the delegation table, the current moment, the action log,
approvals and undo. The Core wraps every delegated action here (ARC-04, DEL-18).

Workspace files (docs/contracts/workspace-layout.md): `delegation.yaml`, `moment.yaml` and one
YAML file per action log entry in `action-log/` (docs/contracts/action-log-entry.schema.json).
"""

import fcntl
import functools
import inspect
import secrets
import threading
from collections.abc import Callable, Generator
from concurrent.futures import Future
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import yaml
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.session import MODERN_PROTOCOL_VERSIONS

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
# DEL-08, VIS-01: a v4 setting, not an architectural constraint; no other responsibility is capped.
CAPS = {"narrative_direction": "propose"}
# ADR 0009: for a world-turn job, the class of its effects, not the tool, decides the
# responsibility that governs each of its actions.
JOB_GOVERNED = ("living_world", "narrative_direction")
_NEVER_DISCLOSES = (
    "The living world never discloses (LW-08): what reaches the party goes through disclosure."
)
TABLE_FILE = "delegation.yaml"
MOMENT_FILE = "moment.yaml"
LOG_DIR = "action-log"
JOBS_DIR = "jobs"
CALLS_DIR = "calls"
OBSERVATIONS_DIR = "observations"
OCCURRENCES_DIR = "occurrences"  # the world-turn's occurrences (world.py)
WORLD_FILE = "living-world.yaml"  # the world-turn's cursor
FRICTIONS_DIR = "frictions"

# The base profiles (DEL-06), in RESPONSIBILITIES order; every cell's deadline mode is auto and
# its irreversible hold set (DEL-09a).
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
        r: {"level": level, "deadline": "auto", "hold": True}
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
    from secondchair.core import calls, capture  # they build on this module

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
        capture.queue_wrap(ws, {"session": str(ended), **({"notes": notes} if notes else {})})
    return True


def start_session(ws: Workspace) -> int:
    """Start session (DEL-03): open live-session, refused while one is open (DEL-03b); the new
    session's id. Only an authenticated Surface may call this (DEL-03a)."""
    with locked(ws):  # two Surfaces starting at once: one is refused
        live = current_session(ws)
        if live is not None:
            raise DelegationError(f"Session {live} is already open; end it first.")
        change_moment(ws, "live-session")
        return last_session(ws)


def end_session(ws: Workspace, notes: str | None = None) -> int:
    """End session (DEL-03): open between-sessions, which queues "wrap a session" (DEL-04), given
    the GM's `notes` file if any; the ended session's id. Only an authenticated Surface may call
    this (DEL-03a)."""
    with locked(ws):
        live = current_session(ws)
        if live is None:
            raise DelegationError("No live session is open.")
        change_moment(ws, "between-sessions", notes)
        return live


def _write_moment(root: Path, moment: str, seq: int, session: int = 0) -> None:
    data = {"moment": moment, "seq": seq, "session": session}
    _write(root / MOMENT_FILE, yaml.safe_dump(data, sort_keys=False))


# Levels


def effective_level(
    ws: Workspace, responsibility: str, moment: str, reversible: bool, entity: str | None = None
) -> str:
    """The table cell for the moment, lowered by the acting entity's overrides (DEL-12). An
    irreversible action is held at propose while the cell's hold is set (DEL-09, DEL-09a), and
    narrative direction is held at propose (DEL-08)."""
    level = _cell(ws, moment, responsibility).get("level")
    if level not in LEVELS:
        raise WorkspaceError(
            f"{ws.root / TABLE_FILE}: {moment} / {responsibility} needs a level among "
            f"{', '.join(LEVELS)}."
        )
    hold = not reversible and held(ws, moment, responsibility)
    levels = [level, "propose"] if hold else [level]
    levels += [CAPS[responsibility]] if responsibility in CAPS else []
    levels += [
        o["level"]
        for o in overrides(ws)
        if entity is not None
        and (o["entity"], o["responsibility"]) == (entity, responsibility)
        and o["moment"] in (None, moment)
    ]
    return min(levels, key=LEVELS.index)


def held(ws: Workspace, moment: str, responsibility: str) -> bool:
    """Whether the cell holds irreversible actions at propose (DEL-09a); set when absent."""
    hold = _cell(ws, moment, responsibility).get("hold", True)
    if type(hold) is not bool:
        raise WorkspaceError(
            f"{ws.root / TABLE_FILE}: {moment} / {responsibility} hold must be true or false."
        )
    return hold


def set_hold(
    ws: Workspace,
    responsibility: str,
    moment: str,
    hold: bool,
    channel: str,
    authenticated: bool,
    quote: str | None = None,
) -> dict:
    """Restore (`hold` true) or lift a cell's irreversible hold (DEL-09a): restoring is accepted
    from any Surface, an agent relay quoting the GM included; lifting approves every future
    irreversible action of the cell, so only an authenticated Surface may. In force at once."""
    if responsibility not in RESPONSIBILITIES:
        raise DelegationError(
            f"Unknown responsibility {responsibility!r}; expected one of "
            f"{', '.join(RESPONSIBILITIES)}."
        )
    if moment not in MOMENTS:
        raise DelegationError(f"Unknown moment {moment!r}; expected one of {', '.join(MOMENTS)}.")
    if not hold and not authenticated:
        raise DelegationError(
            "Lifting the irreversible hold approves every future irreversible action of the "
            "cell: do it from an authenticated Surface (the CLI in an interactive terminal)."
        )
    if channel == "via agent" and not (quote and quote.strip()):
        raise DelegationError("A hold relayed by an agent must quote the GM's words.")
    with locked(ws):
        table = _read_yaml(ws.root / TABLE_FILE)
        cell = (table.get(moment) or {}).get(responsibility)
        if not isinstance(cell, dict):
            raise WorkspaceError(f"{ws.root / TABLE_FILE}: no {moment} / {responsibility} cell.")
        cell["hold"] = hold
        _write(ws.root / TABLE_FILE, yaml.safe_dump(table, sort_keys=False, allow_unicode=True))
        return _interaction(
            ws,
            "restore_hold" if hold else "lift_hold",
            None,
            channel,
            authenticated,
            quote,
            None,
            hold={"responsibility": responsibility, "moment": moment},
        )


def hold_tool(ws: Workspace) -> Callable[..., dict[str, Any]]:
    """The agent relay of a GM restoring the irreversible hold (DEL-09a). Lifting has none."""

    def restore_hold(responsibility: str, moment: str, gm_words: str) -> dict[str, Any]:
        """Hold every irreversible action (a disclosure, a public line) of one delegation-table
        cell at propose again, when the GM asked for it in conversation: quote the GM's exact
        words. `moment`: prep, live-session or between-sessions. In force at once. Only the GM
        can lift it, from an authenticated Surface."""
        with _for_agent():
            interaction = set_hold(ws, responsibility, moment, True, "via agent", False, gm_words)
        return {"entry": interaction["id"], "hold": interaction["hold"]}

    return restore_hold


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
        *args: Any,
        agent: str,
        ctx: Context | None = None,
        job: int | None = None,
        blocking: bool = False,
        **kwargs: Any,
    ) -> ActionResult:
        with _for_agent():
            job = session_job(ws, ctx, job)
            return act(ws, tool, agent, lambda: tool.fn(*args, **kwargs), job, blocking)

    added = [
        inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context),
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
    # The SDK finds the Context parameter from the annotations, and leaves it out of the schema.
    run.__annotations__ = {**tool.fn.__annotations__, "ctx": Context}
    run.__doc__ = (
        f"{inspect.getdoc(tool.fn) or ''}\n\n`agent`: your name as an agent, recorded in the "
        "action log for traceability only. `job`: the SecondChair job you are running, if any; "
        "the action is then bound by the delegation table of the job's moment. `blocking`: true "
        "when the table is waiting on this action to go on with the current turn or scene; a "
        "proposal then calls on the GM at once instead of at the next break."
    )
    return run


def session_job(ws: Workspace, ctx: Context | None, job: int | None) -> int | None:
    """The job an agent session's delegated action is for (ARC-23a). A client that keeps an MCP
    session (the handshake protocols) is bound to the job it starts, or first acts for, until
    that job ends: its actions are for that job whether or not they pass `job`, and refused for
    another one. A sessionless client (2026-07-28) has nothing to bind, so its actions without
    `job` are refused while a world-turn job is started."""
    from secondchair.core import jobs  # it builds on this module

    if _session_state(ctx) is None:
        started = [
            j["id"]
            for j in jobs.pending(ws)
            if j["status"] == "started" and j["responsibility"] in JOB_GOVERNED
        ]
        if job is None and started:
            raise DelegationError(
                f"World-turn job {started[0]} is started: pass `job` to every delegated action "
                "(none is taken outside a job meanwhile, ARC-23a)."
            )
        return job
    bound = bound_job(ws, ctx)
    if bound is None:
        if job is not None and jobs.read(ws, job)["status"] == "started":
            bind(ctx, job)
        return job
    if job is not None and job != bound:
        raise DelegationError(f"This session runs job {bound}: finish it before job {job}.")
    return bound


def bound_job(ws: Workspace, ctx: Context | None) -> int | None:
    """The started job this agent session is bound to, if it keeps a session and is bound."""
    from secondchair.core import jobs  # it builds on this module

    state = _session_state(ctx) or {}
    bound = state.get(_BOUND)
    if bound is not None and jobs.read(ws, bound)["status"] != "started":
        del state[_BOUND]
        bound = None
    return bound


def bind(ctx: Context | None, job: int) -> None:
    """Bind an agent session, if it keeps one, to the job it has just started."""
    if (state := _session_state(ctx)) is not None:
        state[_BOUND] = job


def _session_state(ctx: Context | None) -> dict[str, Any] | None:
    """The per-session state of the client's MCP connection, or None for a sessionless client
    (2026-07-28), whose every request gets a fresh connection, or a call outside MCP."""
    if ctx is None or ctx.session.protocol_version in MODERN_PROTOCOL_VERSIONS:
        return None
    return ctx.session._connection.state  # the SDK exposes it to tools only through the session


_BOUND = "secondchair.job"


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
    moment (ARC-23), logs the job's runner configuration (DEL-24) and blocks as the job does. A
    world-turn job's action is also governed by the job's responsibility, under which it is
    logged (ADR 0009), at the stricter of the two levels (DEL-23); a living-world action never
    discloses (LW-08). `hold` holds it at propose whatever the level, the call carrying it as
    its message (a wrap's contradiction or blocking question, CAP-10)."""
    from secondchair.core import calls

    with locked(ws):
        moment, seq = current_moment(ws)
        table_moment, runner_configuration = moment, None
        governing = [tool.responsibility]
        if job is not None:
            from secondchair.core import jobs  # it builds on this module

            record = jobs.read(ws, job)
            if record["status"] != "started":
                raise DelegationError(f"Job {job} is {record['status']}, not started.")
            table_moment = record["moment"]
            runner_configuration = record["attempts"][-1]["runner_configuration"]
            blocking = record.get("blocking", False)
            if record["responsibility"] in JOB_GOVERNED:
                governing.append(record["responsibility"])
            if record["playbook"] == "propose-narrative-direction" and occurrence is None:
                # its answer closes it (LW-19); a proposal from an observation has none (#177)
                occurrence = record["inputs"].get("occurrence")
        responsibility = governing[-1]

        def strictest(entity: str | None = None) -> tuple[str, str]:
            return min(
                (
                    (effective_level(ws, r, table_moment, tool.reversible, entity), r)
                    for r in governing
                ),
                key=lambda found: LEVELS.index(found[0]),
            )

        cell, which = strictest()
        if cell == "manual":
            raise DelegationError(
                f"{which} is at manual in {table_moment}: agents take no action, "
                "they only answer when asked."
            )
        if responsibility == "living_world" and tool.responsibility == "disclosure":
            raise DelegationError(_NEVER_DISCLOSES)
        try:
            change, refusal = describe(), None
        except Contradiction as c:  # logged: a Core-detected contradiction with canon (MET-01)
            change, refusal = Change(path=c.path, after=None), str(c)
        entity = getattr(change, "entity", None)
        if entity is not None and not isinstance(entity, str):
            raise DelegationError(f"{tool.name}: the acting entity must be an entity id")
        if responsibility == "living_world" and discloses(change):
            raise DelegationError(_NEVER_DISCLOSES)
        level, which = strictest(entity)
        lowered = level != cell
        if isinstance(change, VttAction) and change.hold is not None:
            hold = change.hold if hold is None else f"{hold} {change.hold}"
        if hold is not None:
            level = min(level, "propose", key=LEVELS.index)
        if level == "manual":
            raise DelegationError(
                f"An entity override sets {which} at manual for {entity}: agents "
                "take no action for it, they only answer when asked."
            )
        if isinstance(change, VttAction):
            # The VTT reports the state before; at propose it is known only once approved.
            effect = {"op": change.op, "target": change.target, "before": None}
            effect["after"] = change.params
            if change.cites is not None:
                effect["cites"] = _check_cites(ws, change.cites, entity)
            if change.whisper:  # held for the wrap of this session (CAP-08)
                effect.update(whisper=True, session=current_session(ws))
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
            "responsibility": responsibility,
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
        if entry["status"] == "applied" and "op" in entry:
            taking = _append(ws, {**entry, "status": "unknown"})  # until the VTT answers
        else:
            if entry["status"] == "applied":
                _apply(ws, entry, "after")
            logged = _append(ws, entry)
            if entry["status"] == "applied":
                _disclose(ws, logged)
            if entry["status"] == "pending":
                calls.open_call(
                    ws,
                    kind="proposal",
                    responsibility=responsibility,
                    table_moment=table_moment,
                    blocking=blocking,
                    entry=logged["id"],
                    job=job,
                    message=hold,
                )
                logged = read_entry(ws, logged["id"])  # a safe default may have rejected it
            return {"entry": logged["id"], "status": logged["status"]}
    taken = _take(ws, taking, table_moment, blocking)
    return {"entry": taken["id"], "status": taken["status"]}


# GM interactions (DEL-27): each is its own log entry.


def approve(
    ws: Workspace, entry_id: int, channel: str, authenticated: bool, quote: str | None = None
) -> dict:
    """Approve a pending action (DEL-28): from any Surface for a reversible one, "via agent" only
    with the GM's quoted words, and from an authenticated Surface for an irreversible one."""
    if channel == "via agent" and not (quote and quote.strip()):
        raise DelegationError("An approval relayed by an agent must quote the GM's words.")

    def approving(entry: dict) -> None:
        interaction = _interaction(ws, "approve", entry_id, channel, authenticated, quote, None)
        _answered(ws, entry_id)
        entry["approval"] = {
            "channel": channel,
            "authenticated": authenticated,
            "quote": quote,
            "interaction": interaction["id"],
        }

    with locked(ws):
        entry = _pending(ws, entry_id)
        if not entry["reversible"] and not authenticated:
            raise DelegationError(
                f"Entry {entry_id} is irreversible: approve it from an authenticated Surface "
                "(the CLI in an interactive terminal)."
            )
        if entry.get("cites"):  # canon may have changed since it was proposed
            _check_cites(ws, entry["cites"], entry.get("entity"))
        if "op" in entry:
            entry["status"] = "unknown"  # until the VTT answers
            _save(ws, entry)
        else:
            _apply(ws, entry, "after")
            approving(entry)
            entry["status"] = "applied"
            _save(ws, entry)
            _disclose(ws, entry)
            _narrative_answered(ws, entry)
            return entry
    # The GM is answering now: a ceiling refusal is held for the break.
    return _take(ws, entry, entry["moment"], False, approving)


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
        _narrative_answered(ws, entry)
        return entry


def _narrative_answered(ws: Workspace, entry: dict) -> None:
    from secondchair.core import world  # it builds on this module

    if entry.get("occurrence") is not None:
        world.proposal_answered(ws, entry)


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
    for call in calls.read_calls(ws):
        job = jobs.get(call["job"]) if call["job"] is not None else None
        if call["entry"] is not None:
            entity = read_entry(ws, call["entry"]).get("entity")
        else:
            entity = job.get("entity") if job else None
        moment = job["moment"] if job else call["moment"]
        if call["status"] == "open" and covered(entity, call["responsibility"], moment):
            calls._default(ws, call, interaction)


def _take(
    ws: Workspace,
    entry: dict,
    table_moment: str,
    blocking: bool,
    approving: Callable[[dict], None] | None = None,
) -> dict:
    """Have the VTT take an action logged `unknown`, outside the lock: the GM client may take a
    while to answer, and every other action, approval and gesture would wait behind it. Its
    outcome is recorded under the lock, with the GM's approval (`approving`) once the VTT took
    it or may have. One the VTT did not answer in time stays unknown until it does."""
    try:
        before, after = vtt.perform(
            entry["op"], entry["target"], entry["after"], entry["before"], entry["effective_level"]
        )
    except vtt.Unanswered as e:
        with locked(ws):
            if approving is not None:
                approving(entry)
            entry["error"] = str(e)
            _save(ws, entry)
        e.later.add_done_callback(functools.partial(_settle_later, ws, entry["id"]))
        raise DelegationError(
            f"Unknown outcome, logged as entry {entry['id']}: {e} The action may have been "
            "taken: its entry stays unknown until the VTT answers."
        ) from e
    except vtt.VttError as e:
        # A failed action (ARC-09): logged, counted, and reported to the agent.
        with locked(ws):
            entry.update(status="failed", error=str(e))
            _save(ws, entry)
            if approving is not None:
                _answered(ws, entry["id"])  # the GM answered; the action failed
            _call_if_ceiling(ws, entry, e, table_moment, blocking)
        raise DelegationError(f"Failed action, logged as entry {entry['id']}: {e}") from e
    with locked(ws):
        if approving is not None:
            approving(entry)
        entry.update(status="applied", before=before, after=after)  # as the VTT reports them
        _save(ws, entry)
        _disclose(ws, entry)
        if approving is not None:
            _narrative_answered(ws, entry)
    return entry


def _settle_later(ws: Workspace, entry_id: int, later: Future[tuple[dict, dict]]) -> None:
    """Settle an unknown action once the VTT answers, in a thread of its own: the answer comes
    on the connector's event loop, which the lock's holder may be waiting on."""
    if not later.cancelled():  # cancelled: the VTT left unanswered, and the action stays unknown
        threading.Thread(target=_settle, args=(ws, entry_id, later), daemon=True).start()


def _settle(ws: Workspace, entry_id: int, later: Future[tuple[dict, dict]]) -> None:
    with locked(ws):
        entry = _entry(ws, entry_id, "action")
        if entry["status"] != "unknown":
            return
        try:
            entry["before"], entry["after"] = later.result()
        except vtt.VttError as e:
            # ponytail: a late ceiling refusal opens no call; the ceiling answers at once.
            entry.update(status="failed", error=str(e))
            _save(ws, entry)
            return
        entry.pop("error", None)
        entry["status"] = "applied"
        _save(ws, entry)
        _disclose(ws, entry)


def _call_if_ceiling(
    ws: Workspace, entry: dict, error: vtt.VttError, table_moment: str, blocking: bool
) -> None:
    """A ceiling refusal is a failed action and a call on the GM (DEL-20). Callers hold the lock."""
    from secondchair.core import calls

    if isinstance(error, vtt.CeilingRefusal):
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


# Disclosures (CAN-16, CAN-17): what the players get to see marks its facts known by the party.


def _check_cites(ws: Workspace, cites: list[str], entity: str | None = None) -> list[str]:
    """A disclosure's cited facts: each in canon, true, free of canaries and, when an NPC
    discloses (`entity`, the acting entity), known by it; and a current date to learn them on.
    No other knower bounds a disclosure: the GM's approval, or a lifted hold, is the gate
    (CAN-16). Callers hold the lock."""
    from secondchair.core import capture, index, knowledge

    if not isinstance(cites, list) or not all(isinstance(c, str) for c in cites):
        raise DelegationError("A disclosure's `cites` must be a list of fact ids.")
    facts = {f["id"]: f for f in index.search_facts(ws)}
    reasons = []
    if unknown := [c for c in cites if c not in facts]:
        reasons.append(f"unknown fact ids {unknown}")
    if never := [c for c in cites if c in facts and facts[c]["never_true"]]:
        reasons.append(f"never-true facts {never}, which the party can only believe")
    if canaries := [
        c for c in cites if c in facts and knowledge.CANARY.search(facts[c]["statement"])
    ]:
        reasons.append(f"facts carrying a canary {canaries}")
    held = knowledge.known(ws, entity) if entity is not None else facts
    if unheld := [c for c in cites if c in facts and c not in held]:
        reasons.append(f"{entity} does not know {unheld}")
    if capture.time(ws)["current_date"] is None:
        reasons.append("no current campaign date to learn them on (time.yaml)")
    if reasons:
        raise DelegationError(f"Disclosure refused: {'; '.join(reasons)}.")
    return cites


def _disclose(ws: Workspace, disclosure: dict) -> None:
    """Mark the facts an applied disclosure cites as known by the party, on the current date and
    in the current session (null outside one): one irreversible action entry per knowledge
    record, approved as the disclosure was (CAN-17). A whisper marks none (CAP-08:
    `hold_whispers`). Callers hold the lock."""
    if not disclosure.get("cites") or disclosure.get("whisper"):
        return
    known = _known_to_party(ws)
    for fact in (f for f in dict.fromkeys(disclosure["cites"]) if f not in known):
        mark = _party_learns(ws, disclosure, fact, current_session(ws))
        _apply(ws, mark, "after")
        _append(ws, mark)


def hold_whispers(ws: Workspace, session: int) -> set[int]:
    """At the wrap, each fact an applied whisper of `session` (or of no session) cited that the
    party does not know yet becomes a call on the GM: its party knowledge record held at
    propose, which the GM approves if the player shared it (CAP-08). A fact is held once,
    however many whispers cited it, and never once it is no longer true. Returns the entries of
    every such record. Callers hold the lock."""
    from secondchair.core import calls, index

    entries, _ = read_log(ws)
    whispers = {
        f"whisper {LOG_DIR}/{e['id']:06d}.yaml": e
        for e in entries
        if e.get("whisper") and e.get("session") in (session, None) and e["status"] == "applied"
    }
    held = [e for e in entries if e.get("source") in whispers]
    marks = {e["id"] for e in held}
    asked = _known_to_party(ws) | {index.split_doc(e["after"])[0]["fact"] for e in held}
    moment, seq = current_moment(ws)
    for source, whisper in whispers.items():
        for fact in dict.fromkeys(whisper.get("cites") or []):
            try:
                _check_cites(ws, [fact])  # canon may have changed since it was whispered
            except DelegationError:
                continue
            if fact in asked:
                continue
            asked.add(fact)
            mark = _party_learns(ws, whisper, fact, whisper["session"])
            mark.update(
                moment=moment,
                moment_seq=seq,
                effective_level="propose",
                source=source,
                status="pending",
                approval=None,
            )
            logged = _append(ws, mark)
            marks.add(logged["id"])
            calls.open_call(
                ws,
                kind="proposal",
                responsibility=whisper["responsibility"],
                table_moment=moment,
                blocking=False,
                entry=logged["id"],
                message=f"Whispered to {whisper['target']}, not shown to the table (CAP-08): "
                f"approve if the party knows {fact} now.",
            )
    return marks


def _known_to_party(ws: Workspace) -> set[str]:
    from secondchair.core import index

    return {k["fact"] for k in index.search_knowledge(ws, [index.PARTY]) if k["mode"] == "knows"}


def _party_learns(ws: Workspace, disclosure: dict, fact: str, session: int | None) -> dict:
    """The irreversible action entry writing the party's knowledge of `fact`, learned from
    `disclosure` on the current date, logged as the disclosure was."""
    from secondchair.core import capture, index

    locator = f"{LOG_DIR}/{disclosure['id']:06d}.yaml"
    record = {
        "id": f"k-{secrets.token_hex(4)}",
        "knower": index.PARTY,
        "fact": fact,
        "mode": "knows",
        "date": capture.time(ws)["current_date"],
        "event": None,
        "rank": "played",  # said or shown in play, quoted by the disclosure's entry
        "origin": {
            "kind": "observation",
            "quote": f"{disclosure['tool']} {disclosure['target']}",
            "locator": locator,
        },
        "session": session,
    }
    return {
        **{k: disclosure[k] for k in ("kind", "moment", "moment_seq", "tool")},
        **{k: disclosure[k] for k in ("responsibility", "effective_level", "agent", "job")},
        "override_lowered": False,
        "entity": None,
        "reversible": False,
        "source": f"disclosure {locator}",
        "runner_configuration": disclosure["runner_configuration"],
        "target": f"{index.KNOWLEDGE_DIR}/{record['id']}.md",
        "before": None,
        "after": index.join_doc(record, ""),
        "status": "applied",
        "approval": disclosure["approval"],
    }


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


def core_states(entries: list[dict]) -> dict[str, str | None]:
    """Each target's content as the Core last left it, replaying writes in the order they hit
    the workspace: an action when applied (at its approval, if any), an undo, a confirmation,
    a hand edit."""
    return {target: content for target, (_, content) in last_writes(entries).items()}


def last_writes(entries: list[dict]) -> dict[str, tuple[dict, str | None]]:
    """Each target's last write the log knows, as `core_states`: the entry that made it (the
    action, the undo or confirmation interaction, the hand edit) and the content it left."""
    by_id = {e["id"]: e for e in entries}
    writes = []
    for e in entries:
        if e.get("kind") == "action" and "op" in e:
            continue  # a VTT action writes no workspace file
        if e.get("kind") == "action" and e.get("status") in ("applied", "undone"):
            when = e["approval"]["interaction"] if e.get("approval") else e["id"]
            writes.append((when, e.get("target"), e, e.get("after")))
        elif e.get("kind") == "hand_edit" or e.get("interaction") == "confirm":
            writes.append((e["id"], e.get("target"), e, e.get("after")))
        elif e.get("interaction") == "undo" and "op" not in by_id.get(e.get("entry"), {"op": 0}):
            undone = by_id[e["entry"]]
            writes.append((e["id"], undone.get("target"), e, undone.get("before")))
    writes.sort(key=lambda w: w[0])
    return {target: (e, content) for _, target, e, content in writes if isinstance(target, str)}


def log_hand_edits(ws: Workspace) -> list[dict]:
    """Log every canon file whose content differs from what the Core last wrote there, at the
    agent-proposal rank (CAN-11). The GM promotes one with `promote`."""
    with locked(ws):
        entries, _ = read_log(ws)
        # Only canon files: the Core's other targets (scenes/, prep/) are not read as canon.
        known = {t: c for t, c in core_states(entries).items() if t.startswith(f"{CANON_DIR}/")}
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
                effective_level(ws, responsibility, moment, reversible=False)
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


def discloses(change: object) -> bool:
    """Whether a change makes the party know a fact: a knowledge record whose knower is the
    party (CAN-17), which only disclosure writes (LW-08)."""
    from secondchair.core import index  # it builds on this module

    if not isinstance(change, Change) or change.after is None:
        return False
    if not change.path.startswith(f"{index.KNOWLEDGE_DIR}/"):
        return False
    return index.split_doc(change.after)[0].get("knower") == index.PARTY


# Top-level workspace paths no delegated action writes: the Core's, the GM's and the managed
# skills'.
CORE_PATHS = (
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
    # Written by other Core modules, which this one cannot import: the wrap's candidates and
    # dates, the house rules, the reference library, the Foundry binding, Source references.
    "capture",
    "time.yaml",
    "house-rules.yaml",
    "library.yaml",
    "foundry.yaml",
    "sources",
    # Written by the GM or by `secondchair campaign-skill`, never by an agent's action.
    "speakers.yaml",
    ".agents",
    ".claude",
    ".secondchair-skills.json",
    # Git's own: a hook written there would run code at the GM's next commit.
    ".git",
    ".gitignore",
)


def _target(ws: Workspace, relative: str) -> Path:
    path = (ws.root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(ws.root.resolve()):
        raise DelegationError(f"{relative!r} is outside the campaign workspace.")
    parts = path.relative_to(ws.root.resolve()).parts
    if parts and parts[0] in CORE_PATHS:
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
    except (DelegationError, WorkspaceError, ValueError, vtt.VttError) as e:
        raise ToolError(str(e)) from e


_held = threading.local()


@contextmanager
def locked(ws: Workspace | Path) -> Generator[None]:
    """One writer at a time across `serve` and the CLI; reentrant within a thread, since an
    action reads the index, which may log hand edits. A bare root for a workspace that does not
    load yet (an upgrade).
    ponytail: one workspace-wide lock; finer locks if agents ever queue behind it."""
    held: set[Path] = _held.__dict__.setdefault("roots", set())
    base = ws if isinstance(ws, Path) else ws.root
    root = base.resolve()
    if root in held:
        yield
        return
    lock = base / STATE_DIR / "delegation.lock"
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
