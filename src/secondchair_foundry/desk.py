"""The Director's Desk, Core side (ARC-12, ARC-14, docs/contracts/foundry-bridge.md).

The Desk is an authenticated Surface (ARC-13): the `secondchair-foundry` module shows it only
to the GM whose client holds the bridge, which the token authenticates. It holds no state
(ARC-11): the Core sends it what to show (`state`) and takes the gestures it relays (`take`).
"""

import json

from secondchair.core import calls, canon, delegation, index
from secondchair.core.delegation import DelegationError
from secondchair.core.index import CanonError
from secondchair.core.workspace import Workspace, WorkspaceError

CHANNEL = "desk"
DETAIL = 400  # characters of a proposal's content shown on the Desk


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


def state(ws: Workspace) -> dict:
    """What the Desk shows, sent by the Core whenever it changes."""
    moment, _seq = delegation.current_moment(ws)
    return {
        "type": "desk",
        "moment": moment,
        "session": delegation.current_session(ws),
        "calls": due_now(ws),
        "decisions": decisions(ws),
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
        elif name == "end_session":
            delegation.end_session(ws)
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
