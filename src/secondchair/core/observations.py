"""Observations: what the VTT connector captures live, in the event envelope (ARC-16, CAP-03).

One JSON Lines file per live session, `observations/<session>.jsonl`, appended to as the
connector sends envelopes (docs/contracts/event-envelope.schema.json). Never canon by itself:
capture quotes it, with the locator `observations/<session>.jsonl#<id>`.
"""

import json
import os
import re
import threading
from datetime import datetime

from secondchair.core import delegation
from secondchair.core.workspace import Workspace

DIR = delegation.OBSERVATIONS_DIR
KIND = re.compile(r"[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)*")
VISIBILITIES = ("players", "gm", "blind")  # only players attests what the party knows
FIELDS = ("id", "session", "at", "scene", "actor", "kind", "visibility", "payload")
_lock = threading.Lock()


OUTSIDE = f"{DIR}/outside-sessions.jsonl"  # session null: captured outside a live session


def path(session: int | None) -> str:
    return OUTSIDE if session is None else f"{DIR}/{session:06d}.jsonl"


def locator(envelope: dict) -> str:
    return f"{path(envelope['session'])}#{envelope['id']}"


def problem(envelope: object) -> str | None:
    """Why `envelope` is not a valid event envelope, or None (the schema's checks, by hand)."""
    if not isinstance(envelope, dict) or set(envelope) != set(FIELDS):
        return f"An envelope has exactly the fields {', '.join(FIELDS)}."
    e = envelope
    if not (isinstance(e["id"], str) and 0 < len(e["id"]) <= 200):
        return "id must be a non-empty string."
    if e["session"] is not None and (type(e["session"]) is not int or e["session"] < 1):
        return "session must be a positive integer, or null outside a live session."
    try:
        if datetime.fromisoformat(e["at"]).tzinfo is None:
            return "at needs a UTC offset."
    except TypeError, ValueError:
        return "at must be an ISO 8601 date-time."
    if not all(isinstance(e[k], str | None) for k in ("scene", "actor")):
        return "scene and actor are strings or null."
    if not (isinstance(e["kind"], str) and KIND.fullmatch(e["kind"])):
        return "kind must be a lowercase name, prefixed by a system id for a system's kinds."
    if e["visibility"] not in VISIBILITIES:
        return f"visibility must be one of {', '.join(VISIBILITIES)}."
    if not isinstance(e["payload"], dict):
        return "payload must be an object."
    return None


def record(ws: Workspace, envelope: object) -> str | None:
    """Append `envelope` to its session's file, once per id. Returns why it is refused, or None
    when it is recorded (or already was). An observation of a session not opened yet is refused;
    one of an ended session is still recorded: it was captured live and delivered late."""
    if reason := problem(envelope):
        return reason
    assert isinstance(envelope, dict)
    opened = delegation.last_session(ws)
    if envelope["session"] is not None and envelope["session"] > opened:
        return f"session {envelope['session']} has not been opened (the last is {opened})."
    with _lock:
        if find(ws, locator(envelope)) is not None:
            return None
        file = ws.root / path(envelope["session"])
        file.parent.mkdir(exist_ok=True)
        # A line cut short by a crash is skipped on reading; never glue the next one to it.
        torn = file.is_file() and file.read_bytes()[-1:] not in (b"", b"\n")
        with file.open("a") as out:
            out.write(("\n" if torn else "") + json.dumps(envelope, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())
    return None


def find(ws: Workspace, locator: str) -> dict | None:
    """The observation at `locator` (`observations/<session>.jsonl#<id>`), or None."""
    name, _, id_ = locator.partition("#")
    file = ws.root / name
    if not (file.parent.resolve() == (ws.root / DIR).resolve() and file.is_file()):
        return None
    # ponytail: scans the session file per lookup; index ids if sessions grow past ~10k lines.
    for line in file.read_text().splitlines():
        try:
            observation = json.loads(line)
        except ValueError:
            continue  # a line cut short by a crash
        if isinstance(observation, dict) and observation.get("id") == id_:
            return observation
    return None
