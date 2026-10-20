"""Behaviour traces (TRC-01..TRC-05; ADR 0012).

Raw traces are a Source on the GM's machine, outside the workspace: one JSON Lines file per
campaign and Foundry user, `$XDG_DATA_HOME/secondchair/traces/<campaign>/<user>.jsonl`, each
record tagged with the moment it arrived in, and beside it `<user>.json`, the user's name and
whether they are a GM. The workspace keeps only the per-moment friction report,
`frictions/<seq>.md`: the frictions the detectors find (TRC-03), GM effort, table friction and
the gaps, traces lost with nobody to relay them. It is written when a gap arrives, when the
moment ends, and on demand (`secondchair frictions`).
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
    if not isinstance(message.get("gm", False), bool):
        return "gm, when given, is a boolean."
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
    record_lines(campaign, message["user"], message["name"], message.get("gm", False), lines)
    if any(r["stream"] == "gap" for r in lines):
        report(ws, campaign, seq, moment)


def record_lines(campaign: str, user: str, name: str, gm: bool, lines: list[dict]) -> None:
    """Append records already tagged with their moment, and keep who the user is."""
    file = directory(campaign) / f"{user}.jsonl"
    with _lock:
        file.parent.mkdir(parents=True, exist_ok=True)
        # A line cut short by a crash is skipped on reading; never glue the next one to it.
        torn = file.is_file() and file.read_bytes()[-1:] not in (b"", b"\n")
        with file.open("a") as out:
            out.write("\n" if torn else "")
            out.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
        file.with_suffix(".json").write_text(json.dumps({"name": name, "gm": gm}))


def erase(ws: Workspace, campaign: str, user: object) -> None:
    """Delete every trace of `user` in this campaign, and rewrite the reports they were in
    (TRC-01)."""
    if not valid_user(user):
        return
    file = directory(campaign) / f"{user}.jsonl"
    with _lock:
        moments = {(r["seq"], r["moment"]) for r in _read(file)}
        file.unlink(missing_ok=True)
        file.with_suffix(".json").unlink(missing_ok=True)
    for seq, moment in moments:
        if _report_path(ws, seq).is_file():
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


def _report_path(ws: Workspace, seq: int) -> Path:
    return ws.root / delegation.FRICTIONS_DIR / f"{seq:06d}.md"


def campaign_of(ws: Workspace) -> str | None:
    """The campaign id the Foundry connector bound this workspace to (foundry.yaml), if any."""
    path = ws.root / "foundry.yaml"
    data = yaml.safe_load(path.read_text()) if path.is_file() else None
    campaign = data.get("campaign") if isinstance(data, dict) else None
    return campaign if isinstance(campaign, str) else None


def report_moment(ws: Workspace, seq: int) -> Path | None:
    """Write moment `seq`'s friction report, or None when no traces were kept in it."""
    campaign = campaign_of(ws)
    if campaign is None:
        return None
    for file in sorted(directory(campaign).glob("*.jsonl")):
        for r in _read(file):
            if r.get("seq") == seq:
                return report(ws, campaign, seq, r["moment"])
    return None


def _user(file: Path) -> dict:
    try:
        meta = json.loads(file.with_suffix(".json").read_text())
    except OSError, ValueError:
        meta = {}
    return {"name": meta.get("name", file.stem), "gm": meta.get("gm") is True}


def report(ws: Workspace, campaign: str, seq: int, moment: str) -> Path:
    """Write the friction report of moment `seq` from the raw traces and the action log."""
    # ponytail: rereads every trace file; index them by moment if reports get slow.
    limits = frictions.thresholds(ws)
    gaps, found, acts = [], [], 0
    for file in sorted(directory(campaign).glob("*.jsonl")):
        user, who = file.stem, _user(file)
        records = [r for r in _read(file) if r.get("seq") == seq]
        gaps += [
            {
                "user": user,
                "name": r.get("name", who["name"]),
                "from": _iso(r["from"]),
                "to": _iso(r["to"]),
                "lost": r["lost"],
            }
            for r in records
            if r.get("stream") == "gap"
        ]
        role = "gm" if who["gm"] else "player"
        found += [
            {"detector": f["detector"], "user": user, "name": who["name"], "role": role}
            | {"from": f["from"], "to": f["to"]}
            for f in frictions.detect(records, user, who["gm"], moment, limits)
        ]
        acts += frictions.manual_acts(records) if who["gm"] else 0
    found.sort(key=lambda f: (f["from"], f["user"]))
    found = [{"id": n} | f for n, f in enumerate(found, 1)]
    entries, _ = delegation.read_log(ws)
    effort = {
        # Every GM interaction with SecondChair, a Director's Desk one included, counts once.
        "interactions": sum(
            e.get("moment_seq") == seq and e.get("kind") in ("gm_interaction", "hand_edit")
            for e in entries
        ),
        "manual_acts": acts,
        "frictions": sum(f["role"] == "gm" for f in found),
    }
    front = {
        "moment": moment,
        "seq": seq,
        "gm_effort": effort,
        "table_friction": sum(f["role"] == "player" for f in found),
        "frictions": found,
        "gaps": gaps,
    }

    def listed(role: str) -> list[str]:
        return [
            f"- {f['id']}. {f['name']}: {f['detector'].replace('_', ' ')}, from "
            f"{_iso(f['from'])} to {_iso(f['to'])}."
            for f in found
            if f["role"] == role
        ] or ["None."]

    body = [
        f"# Friction report: {moment} (moment {seq})",
        "",
        "## GM effort",
        "",
        f"- Interactions with SecondChair: {effort['interactions']}",
        f"- Manual acts in the VTT: {effort['manual_acts']}",
        f"- GM frictions: {effort['frictions']}",
        "",
        "## GM frictions",
        "",
        *listed("gm"),
        "",
        "## Table friction",
        "",
        "Player frictions, watched over time; never part of GM effort.",
        "",
        *listed("player"),
        "",
        "## Trace gaps",
        "",
    ]
    body += [
        f"- {g['name']}: {g['lost']} records lost from {g['from']} to {g['to']}, with no GM "
        "client to relay them (TRC-05)."
        for g in gaps
    ] or ["None."]
    path = _report_path(ws, seq)
    path.parent.mkdir(exist_ok=True)
    front_matter = yaml.safe_dump(front, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{front_matter}---\n\n" + "\n".join(body) + "\n")
    return path
