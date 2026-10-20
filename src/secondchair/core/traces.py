"""Behaviour traces (TRC-01, TRC-02, TRC-04, TRC-05; ADR 0012).

Raw traces are a Source on the GM's machine, outside the workspace: one JSON Lines file per
campaign and Foundry user, `$XDG_DATA_HOME/secondchair/traces/<campaign>/<user>.jsonl`, each
record tagged with the moment it arrived in. The workspace keeps only the per-moment friction
report, `frictions/<seq>.md`, which so far lists the gaps: traces lost with nobody to relay them.
"""

import json
import re
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import yaml

from secondchair.core import delegation
from secondchair.core.machine import data_dir
from secondchair.core.workspace import Workspace

USER = re.compile(r"[A-Za-z0-9]{1,64}")  # a Foundry user id, and so a safe file name
STREAMS = ("semantic", "input", "gap")
_lock = threading.Lock()


def directory(campaign: str) -> Path:
    return data_dir() / "traces" / campaign


def valid_user(user: object) -> bool:
    return isinstance(user, str) and USER.fullmatch(user) is not None


def _int(value: object) -> bool:
    return type(value) is int and value >= 0


def problem(message: object) -> str | None:
    """Why a `traces` message is malformed, or None (the schema's checks that matter here)."""
    if not isinstance(message, dict) or not valid_user(message.get("user")):
        return "user must be a Foundry user id."
    records = message.get("records")
    if not isinstance(message.get("name"), str) or not isinstance(records, list):
        return "a traces message has a name and a list of records."
    for r in records:
        if not (isinstance(r, dict) and _int(r.get("t")) and r.get("stream") in STREAMS):
            return "each record has an integer t and a stream."
        if r["stream"] == "gap" and not (
            _int(r.get("from")) and _int(r.get("to")) and _int(r.get("lost"))
        ):
            return "a gap has integers from, to and lost."
    return None


def record(ws: Workspace, campaign: str, message: dict) -> None:
    """Append the records of a valid `traces` message, tagged with the current moment, and
    refresh that moment's report when they note a gap."""
    # ponytail: a gap is tagged with the moment it arrives in, not the one it was lost in.
    moment, seq = delegation.current_moment(ws)
    lines = [
        r
        | {"moment": moment, "seq": seq}
        | ({"name": message["name"]} if r["stream"] == "gap" else {})
        for r in message["records"]
    ]
    file = directory(campaign) / f"{message['user']}.jsonl"
    with _lock:
        file.parent.mkdir(parents=True, exist_ok=True)
        # A line cut short by a crash is skipped on reading; never glue the next one to it.
        torn = file.is_file() and file.read_bytes()[-1:] not in (b"", b"\n")
        with file.open("a") as out:
            out.write("\n" if torn else "")
            out.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
    if any(r["stream"] == "gap" for r in lines):
        report(ws, campaign, seq, moment)


def erase(ws: Workspace, campaign: str, user: object) -> None:
    """Delete every trace of `user` in this campaign, and their gaps from the reports (TRC-01)."""
    if not valid_user(user):
        return
    file = directory(campaign) / f"{user}.jsonl"
    with _lock:
        reported = {(r["seq"], r["moment"]) for r in _read(file) if r.get("stream") == "gap"}
        file.unlink(missing_ok=True)
    for seq, moment in reported:
        report(ws, campaign, seq, moment)


def _read(file: Path) -> Iterator[dict]:
    if not file.is_file():
        return
    for line in file.read_text().splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue  # a line cut short by a crash


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def report(ws: Workspace, campaign: str, seq: int, moment: str) -> Path:
    """Write the friction report of moment `seq` from the raw traces: so far, its gaps."""
    # ponytail: rereads every trace file per gap; gaps are rare, index them if that changes.
    gaps = [
        {
            "user": file.stem,
            "name": r.get("name", file.stem),
            "from": _iso(r["from"]),
            "to": _iso(r["to"]),
            "lost": r["lost"],
        }
        for file in sorted(directory(campaign).glob("*.jsonl"))
        for r in _read(file)
        if r.get("seq") == seq and r.get("stream") == "gap"
    ]
    front = {"moment": moment, "seq": seq, "gaps": gaps}
    body = [f"# Friction report: {moment} (moment {seq})", "", "## Trace gaps", ""]
    body += [
        f"- {g['name']}: {g['lost']} records lost from {g['from']} to {g['to']}, with no GM "
        "client to relay them (TRC-05)."
        for g in gaps
    ] or ["None."]
    path = ws.root / delegation.FRICTIONS_DIR / f"{seq:06d}.md"
    path.parent.mkdir(exist_ok=True)
    front_matter = yaml.safe_dump(front, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{front_matter}---\n\n" + "\n".join(body) + "\n")
    return path
