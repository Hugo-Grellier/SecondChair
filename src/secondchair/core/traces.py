"""Behaviour traces (TRC-01 to TRC-05; ADR 0012).

Raw traces are a Source on the GM's machine, outside the workspace: one JSON Lines file per
campaign and Foundry user, `$XDG_DATA_HOME/secondchair/traces/<campaign>/<user>.jsonl`, each
record tagged with the moment it arrived in. The workspace keeps only the per-moment friction
report, `frictions/<seq>.md`: the gaps (traces lost with nobody to relay them), each user's
frictions (frictions.py), GM effort and table friction.
"""

import json
import re
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import yaml

from secondchair.core import delegation, frictions
from secondchair.core.machine import data_dir
from secondchair.core.workspace import CONFIG_FILE, Workspace

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
    if not isinstance(message.get("gm", False), bool):
        return "gm is a boolean."
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
    refresh a moment's friction report when they note a gap, or when they are the user's first
    of a new moment: the previous moment's report is then complete."""
    # ponytail: records are tagged with the moment they arrive in, so a gap, or the last second
    # of records flushed after a moment change, lands in the next moment; tag on the client if
    # that skews reports.
    moment, seq = delegation.current_moment(ws)
    lines = [r | {"moment": moment, "seq": seq} for r in message["records"]]
    if lines:  # who sent them, once per message: the report names users and tells the GM apart
        lines[0] |= {"name": message["name"], "gm": message.get("gm") is True}
    file = directory(campaign) / f"{message['user']}.jsonl"
    with _lock:
        file.parent.mkdir(parents=True, exist_ok=True)
        before = file.read_bytes() if file.is_file() else b""
        last = _last(before)
        with file.open("a") as out:
            # A line cut short by a crash is skipped on reading; never glue the next one to it.
            out.write("\n" if before[-1:] not in (b"", b"\n") else "")
            out.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
    if lines and last and last["seq"] != seq:
        report(ws, campaign, last["seq"], str(last.get("moment")))
    if any(r["stream"] == "gap" for r in lines):
        report(ws, campaign, seq, moment)


def _last(data: bytes) -> dict | None:
    """The last whole record of a trace file, if any."""
    for line in reversed(data.splitlines()):
        try:
            found = json.loads(line)
        except ValueError:
            continue  # a line cut short by a crash
        if isinstance(found, dict) and type(found.get("seq")) is int:
            return found
    return None


def erase(ws: Workspace, campaign: str, user: object) -> None:
    """Delete every trace of `user` in this campaign, and rewrite the reports of every moment
    they have traces in, so their gaps and frictions leave them too (TRC-01)."""
    if not valid_user(user):
        return
    file = directory(campaign) / f"{user}.jsonl"
    with _lock:
        reported = {(r["seq"], r.get("moment")) for r in _read(file) if type(r.get("seq")) is int}
        file.unlink(missing_ok=True)
    for seq, moment in reported:
        report(ws, campaign, seq, str(moment))


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


def _iso_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def interactions(ws: Workspace, seq: int) -> int:
    """GM interactions with SecondChair in moment `seq` (DEL-27); a Director's Desk gesture is
    one, whatever the VTT writes it led to."""
    entries, _ = delegation.read_log(ws)
    return sum(e.get("kind") == "gm_interaction" and e.get("moment_seq") == seq for e in entries)


def report(ws: Workspace, campaign: str, seq: int, moment: str) -> Path:
    """Write the friction report of moment `seq` from the raw traces (TRC-03, TRC-04): its gaps,
    each user's frictions citing their trace span, GM effort and table friction."""
    # ponytail: rereads every trace file; fine per gap and moment change, index them if not.
    th = frictions.thresholds(yaml.safe_load((ws.root / CONFIG_FILE).read_text()) or {})
    gaps, found, acts = [], [], 0
    for file in sorted(directory(campaign).glob("*.jsonl")):
        records = [r for r in _read(file) if r.get("seq") == seq and _int(r.get("t"))]
        if not records:
            continue
        name = next((r["name"] for r in reversed(records) if "name" in r), file.stem)
        gm = any(r.get("gm") is True for r in records)
        gaps += [
            {
                "user": file.stem,
                "name": name,
                "from": _iso(r["from"]),
                "to": _iso(r["to"]),
                "lost": r["lost"],
            }
            for r in records
            if r.get("stream") == "gap"
        ]
        traced = [r for r in records if r.get("stream") in ("semantic", "input")]
        found += [
            {"detector": f["detector"], "user": file.stem, "name": name, "gm": gm}
            | {"from": f["from"], "to": f["to"]}
            for f in frictions.detect(traced, gm, moment, th)
        ]
        acts += frictions.manual_acts(traced) if gm else 0
    asked = interactions(ws, seq)
    table = [f for f in found if not f["gm"]]
    front = {
        "moment": moment,
        "seq": seq,
        "gaps": gaps,
        "gm_effort": {"interactions": asked, "manual_acts": acts},
        "table_friction": len(table),
        "frictions": found,
    }

    def line(f: dict) -> str:
        return f"- {f['detector']}: {f['name']}, {_iso_ms(f['from'])} to {_iso_ms(f['to'])}."

    body = [f"# Friction report: {moment} (moment {seq})", "", "## Trace gaps", ""]
    body += [
        f"- {g['name']}: {g['lost']} records lost from {g['from']} to {g['to']}, with no GM "
        "client to relay them (TRC-05)."
        for g in gaps
    ] or ["None."]
    body += [
        "",
        "## GM effort",
        "",
        f"{asked + acts}: {asked} interactions with SecondChair (a Director's Desk gesture counts "
        f"once) and {acts} manual acts in the VTT.",
        "",
        "## GM frictions",
        "",
        *([line(f) for f in found if f["gm"]] or ["None."]),
        "",
        "## Table friction",
        "",
        "Player frictions: watched over time, never part of GM effort.",
        "",
        *([line(f) for f in table] or ["None."]),
    ]
    path = ws.root / delegation.FRICTIONS_DIR / f"{seq:06d}.md"
    path.parent.mkdir(exist_ok=True)
    front_matter = yaml.safe_dump(front, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{front_matter}---\n\n" + "\n".join(body) + "\n")
    return path
