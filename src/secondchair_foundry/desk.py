"""The Director's Desk, Core side (ARC-12, ARC-14, docs/contracts/foundry-bridge.md).

The Desk is an authenticated Surface (ARC-13): the `secondchair-foundry` module shows it only
to the GM whose client holds the bridge, which the token authenticates. It holds no state
(ARC-11): the Core sends it what to show (`state`) and takes the gestures it relays (`take`).
"""

import json
from datetime import UTC, datetime

import yaml

from secondchair.core import (
    calls,
    canon,
    capture,
    delegation,
    director,
    index,
    knowledge,
    observations,
    setup_check,
    snapshot,
    vtt,
)
from secondchair.core.delegation import DelegationError
from secondchair.core.index import CanonError
from secondchair.core.server import SERVE_FILE
from secondchair.core.workspace import STATE_DIR, Workspace, WorkspaceError
from secondchair_foundry import compendium

CHANNEL = "desk"
DETAIL = 400  # characters of a proposal's content shown on the Desk
VOICED = ("npcs", "disclosure")  # "I voice this one" sets these at manual (DEL-15)


def due_now(ws: Workspace) -> list[dict]:
    """The calls due now, still open (DEL-30)."""
    open_now = [c for c in calls.read_calls(ws) if c["status"] == "open" and c["deadline"] == "now"]
    return [_call(ws, c) for c in open_now]


def decisions(ws: Workspace) -> list[dict]:
    """Facts and events recorded from the GM's words, awaiting the GM's confirmation (DEL-29)."""
    found = [
        {"id": d["id"], "text": d["statement"], "words": d["origin"]["words"]}
        for d in index.search_facts(ws)  # a retconned fact is not offered
        if d["origin"].get("kind") == "gm" and d["rank"] != "gm_decision"
    ]
    return found + [
        {"id": d["id"], "text": d["description"], "words": d["origin"]["words"]}
        for d in index.search_events(ws)
        if d["origin"].get("kind") == "gm" and d["rank"] != "gm_decision"
    ]


def state(ws: Workspace, turn_driver: str | None = None, ready: dict | None = None) -> dict:
    """What the Desk shows, sent by the Core whenever it changes. While a turn driver is active
    (the last rules context names one), agents stay silent: the cue shows no agent's line
    (RUL-12, ADR 0013). The situation card the GM last pulled shows until play moves on.
    `ready` is this connection's readiness card, None until its checks ran."""
    moment, _seq = delegation.current_moment(ws)
    shown = cue(ws)
    if shown and turn_driver:
        shown["line"] = None
    return {
        "type": "desk",
        "moment": moment,
        "session": delegation.current_session(ws),
        "calls": due_now(ws),
        "decisions": decisions(ws),
        "cue": shown,
        "situation": director.current(ws),
        "wrap": wrap(ws),
        "readiness": ready,
        "turn_driver": turn_driver,
    }


def wrap(ws: Workspace) -> dict | None:
    """The wrap-state card (#196 S1, ARC-14): after End session, until the session is marked
    wrapped, where its wrap stands: `queued` or `running` (a wrap job of the last session), else
    `waiting` for the grouped round, which needs an interactive terminal (CAP-13): `secondchair
    wrap`. Only the last session is checked. It carries `as_of`, where play stood when it was sent
    (rebuilt at each read, so it follows the moment). A read of state, writing nothing; None during
    a live session, before any, once wrapped, and, failing closed like `director.current`, when a
    file it reads is damaged."""
    try:
        if delegation.current_moment(ws)[0] == "live-session":
            return None
        session = delegation.last_session(ws)
        if not session or capture.time(ws)["sessions"].get(session, {}).get("wrapped"):
            return None
        job_states = {
            j["status"]
            for j in calls._jobs(ws)
            if j["playbook"] == capture.PLAYBOOK and j["inputs"].get("session") == str(session)
        }
        as_of = observations.position(ws) | {"at": datetime.now(UTC).isoformat()}
    except WorkspaceError, OSError, KeyError, TypeError, AttributeError, ValueError:
        return None
    status = (
        "running" if "started" in job_states else "queued" if "queued" in job_states else "waiting"
    )
    return {"session": session, "status": status, "as_of": as_of}


LIBRARY, ADAPTER = "secondchair-foundry", "secondchair-foundry-pf2e"
HOST_FIX = "Run `secondchair host setup claude` (or `codex`) and follow it, then reload the world."


def readiness(ws: Workspace, world: str, context: object) -> dict | None:
    """The readiness card (#196 S3, D7, ARC-14): checks of this connection, run once after the
    welcome from the world it said hello with and the rules context it answered (None when no
    adapter answered). Each check fails closed: a damaged or unreadable file fails it, never
    passes it; None, as `wrap`, when where play stands cannot be read. A read: it writes nothing
    and calls no model. Its words are fixed or come from the GM client; it names no file outside
    the workspace and holds no token or host content."""
    modules = context.get("modules") if isinstance(context, dict) else None
    modules = modules if isinstance(modules, dict) else {}
    version, library = modules.get(ADAPTER), modules.get(LIBRARY)
    system = context.get("system") if isinstance(context, dict) else None
    try:
        bound = yaml.safe_load((ws.root / snapshot.BINDING).read_text())["world"] == world
    except OSError, ValueError, yaml.YAMLError, KeyError, TypeError:
        bound = False
    try:
        kept = compendium.version(ws) is not None
    except OSError, ValueError, KeyError, TypeError:
        kept = False
    try:
        port = json.loads((ws.root / STATE_DIR / SERVE_FILE).read_text())["port"]
        host = isinstance(port, int) and setup_check.core_registered(ws.root, port) is True
    except OSError, ValueError, KeyError, TypeError:
        host = False
    checks = [
        _check(
            "binding",
            bound,
            f"The campaign is bound to this world, {world!r}.",
            "The workspace's foundry.yaml no longer names this world.",
            "Reload the world: the Core checks the binding again at connect and says what to do.",
        ),
        _check(
            "adapter",
            isinstance(context, dict),
            "The PF2e adapter answered.",
            "No system adapter answered the rules context.",
            f"Enable the {ADAPTER} module in this world, then reload it.",
        ),
        _check(
            "adapter_version",
            isinstance(version, str) and version == library,
            f"{ADAPTER} {version} matches {LIBRARY} {library}.",
            f"{ADAPTER} {version or 'missing'} differs from {LIBRARY} {library or 'missing'}.",
            "Update both modules to the same version in Foundry's setup, then reload the world.",
        ),
        _check(
            "system",
            system == "pf2e",
            "The world's game system is pf2e.",
            f"The world's game system is {system or 'unknown'}, not pf2e.",
            "Open a pf2e world bound to this campaign.",
        ),
        _check(
            "snapshot",
            kept,
            "A compendium snapshot is kept.",
            "No compendium snapshot is kept yet.",
            "Reload the world and wait for the snapshot (up to two minutes); the serve "
            "console says why one was not kept.",
        ),
        _check(
            "agent_host",
            host,
            "An agent host registers the Core.",
            "No agent host on this machine is known to register the Core.",
            f"{HOST_FIX} `secondchair check-setup` says more.",
        ),
    ]
    try:
        as_of = observations.position(ws) | {"at": datetime.now(UTC).isoformat()}
    except WorkspaceError, OSError, KeyError, TypeError, AttributeError, ValueError:
        return None  # where play stands is unreadable: no card, as `wrap`
    return {"ready": all(c["ok"] for c in checks), "checks": checks, "as_of": as_of}


def _check(name: str, ok: bool, yes: str, no: str, fix: str) -> dict:
    return {"check": name, "ok": ok, "says": yes if ok else no, "fix": None if ok else fix}


def cue(ws: Workspace) -> dict | None:
    """The active NPC's acting cue, and whether the GM voices that NPC (DEL-15)."""
    found = knowledge.active_cue(ws)
    return found and found | {"voiced": set(VOICED) <= _voiced(ws, found["npc"])}


def _voiced(ws: Workspace, npc: str) -> set[str]:
    """The responsibilities "I voice this one" set at manual for `npc` that are still so."""
    return {
        o["responsibility"]
        for o in delegation.overrides(ws)
        if (o["entity"], o["level"], o["moment"]) == (npc, "manual", None)
    }


def take(ws: Workspace, message: dict) -> dict:
    """Take one GM gesture relayed by the Desk; the `result` message to answer it with."""
    result: dict = {"type": "result", "id": str(message.get("id")), "ok": True}
    name, entry = message.get("gesture"), message.get("entry")
    try:
        if name in ("approve", "reject"):
            if not isinstance(entry, int) or isinstance(entry, bool):
                raise DelegationError(f"A Desk {name} needs the entry it answers.")
            if name == "approve":
                delegation.approve(ws, entry, CHANNEL, True)
            else:
                delegation.reject(ws, entry, str(message.get("reason")), CHANNEL, True)
        elif name == "confirm":
            canon.confirm(ws, str(message.get("doc")), CHANNEL, True)
        elif name == "break":
            result["pile"] = [_call(ws, c) for c in calls.take_break(ws)]
        elif name == "start_session":
            delegation.start_session(ws)
            # The VTT follows: the current date pushed into its clock (CAL-11).
            if pushed := vtt.session_started():
                result["message"] = pushed
        elif name == "end_session":
            delegation.end_session(ws)
        elif name == "situation":  # a read: shown in the next desk message, never in the result
            director.pull(ws)
        elif name == "voice":  # tightening, in force at once; withdraws its calls (DEL-14, 16)
            for responsibility in VOICED:
                delegation.add_override(
                    ws, str(message.get("entity")), responsibility, "manual", None, CHANNEL, True
                )
        elif name == "hand_back":  # loosening, from this authenticated Surface (DEL-14)
            npc = str(message.get("entity"))
            # As the Desk shows it: voiced only with both at manual, so a lone override set
            # elsewhere is never removed from here.
            if set(VOICED) - _voiced(ws, npc):
                raise DelegationError(f"The GM does not voice {npc}.")
            for responsibility in VOICED:
                delegation.remove_override(ws, npc, responsibility, None, CHANNEL, True)
        else:
            raise DelegationError(f"Unknown Desk gesture {name!r}.")
    except (DelegationError, CanonError, WorkspaceError) as e:
        return result | {"ok": False, "error": str(e)}
    return result


def _call(ws: Workspace, call: dict) -> dict:
    """A call as the Desk shows it, with what its action entry would do."""
    shown = {k: call[k] for k in ("id", "kind", "responsibility", "deadline", "status", "entry")}
    shown |= {"message": call["message"], "detail": None, "reversible": None}
    if call["entry"] is not None:
        entry = delegation.read_entry(ws, call["entry"])
        what = entry["after"]
        if not isinstance(what, str):  # a VTT action's fields, or a file deleted
            what = "deletes it" if what is None else json.dumps(what)
        shown["detail"] = f"{entry['tool']} by {entry['agent']} on {entry['target']}: {what}"[
            :DETAIL
        ]
        shown["reversible"] = entry["reversible"]
    return shown
