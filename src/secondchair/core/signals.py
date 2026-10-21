"""`session_signals` (#185): the deterministic signals `propose-opportunities` rests on, as one
read. No model, no write: unused prep, the spotlight count, fulfilled dossier change triggers."""

from pathlib import Path
from typing import Any

import yaml

from secondchair.core import capture, index, mystery, prep
from secondchair.core.index import CanonError
from secondchair.core.tools import Tool
from secondchair.core.workspace import Workspace

NPCS_DIR = "notes/npcs"


def _front(path: Path) -> dict:
    try:
        return index.split_doc(path.read_text())[0]
    except CanonError, yaml.YAMLError, OSError, UnicodeDecodeError:
        return {}  # a note that does not parse is the notes validator's business


def _unused_prep(ws: Workspace, session: int) -> dict[str, Any]:
    path = f"session-{session}/handoff.md"
    if not (ws.root / prep.PREP_DIR / path).is_file():
        return {"handoff": None, "clues": [], "warnings": []}
    wanted = prep.index_block(prep.read_prep(ws, path)).get("clues") or []
    mysteries = {p.stem: _front(p) for p in sorted((ws.root / mystery.MYSTERIES_DIR).glob("*.md"))}
    clue_fact = {
        c["id"]: c.get("fact")
        for front in mysteries.values()
        for c in front.get("clues") or []
        if isinstance(c, dict) and "id" in c
    }
    played = {c["fact"] for c in capture.candidates(ws, session) if c["status"] == "applied"}
    played |= {  # a played fact that repeats the clue's fact is the clue, found at the table
        c["duplicate_of"]
        for c in capture.candidates(ws, session)
        if c["status"] == "duplicate" and c["duplicate_of"]
    }
    unused = [c for c in wanted if clue_fact.get(c) not in played]
    [check] = [t for t in mystery.tools(ws) if t.name == "check_mystery"]
    warnings = [
        {"mystery": m, **w}
        for m, front in mysteries.items()
        if any(isinstance(c, dict) and c.get("id") in wanted for c in front.get("clues") or [])
        for w in check.fn(m)["warnings"]
    ]
    return {"handoff": path, "clues": unused, "warnings": warnings}


def _fulfilled_triggers(ws: Workspace) -> list[dict[str, Any]]:
    """Dossier `triggers: [{if, facts: [f-...]}]`: fulfilled when every cited fact holds."""
    holding = {
        f["id"]
        for f in index.search_facts(ws, include_retconned=True)
        if f["status"] == "canon" and f["valid_to"] is None
    }
    found = []
    for path in sorted((ws.root / NPCS_DIR).glob("*.md")):
        front = _front(path)
        for t in front.get("triggers") or []:
            cited = t.get("facts") if isinstance(t, dict) else None
            if isinstance(cited, list) and cited and set(cited) <= holding:
                found.append(
                    {"note": path.stem, "id": front.get("id"), "if": t.get("if"), "facts": cited}
                )
    return found


def tools(ws: Workspace) -> list[Tool]:
    def session_signals(session: int) -> dict[str, Any]:
        """The deterministic signals for the opportunities of a session, as canon stands (no
        model, nothing written). `unused_prep`: the clue ids of the session's handoff index block
        (`prep/session-<n>/handoff.md`) that no admitted played fact of the session found, and the
        open `check_mystery` warnings of the mysteries they belong to. `spotlight`: per PC, how
        many admitted played facts cite it. `fulfilled_triggers`: the change triggers of the NPC
        dossiers (`triggers:` in the front matter of `notes/npcs/<id>.md`, each `{if, facts}`)
        whose cited facts all hold in canon now."""
        return {
            "session": session,
            "unused_prep": _unused_prep(ws, session),
            "spotlight": capture.spotlight(ws, session),
            "fulfilled_triggers": _fulfilled_triggers(ws),
        }

    return [
        Tool(fn=session_signals, responsibility="prep", delegated_action=False, reversible=True)
    ]
