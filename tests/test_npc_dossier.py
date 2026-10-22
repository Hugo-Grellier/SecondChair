"""Pilot of the `write-an-npc-dossier` skill's deterministic obligations: the note it prescribes,
written under `notes/npcs/`, passes `notes check`, a bad cite is reported, and canon is untouched.
No model runs; the fixtures are what a good run produces."""

import yaml
from test_campaign_direction import snapshot
from test_canon import entity, fact
from test_knowledge import learn, ws  # noqa: F401

from secondchair.core import notes
from secondchair.core.workspace import Workspace


def dossier(workspace: Workspace, cites: list[str]) -> None:
    front = {"id": "d-4a1c7e02", "status": "draft", "cites": cites}
    path = workspace.root / "notes/npcs/npc-dossier.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{yaml.safe_dump(front)}---\n# Dossier\n\n- Secret: {cites[-1]}.\n")


def test_a_dossier_draft_passes_notes_check_and_changes_no_canon(ws: Workspace) -> None:  # noqa: F811
    mira = entity(ws, "Mira Pell")
    secret = fact(ws, "Mira Pell hid the ledger.", entities=[mira])
    learn(ws, mira, secret)
    before = snapshot(ws.root / "canon")
    dossier(ws, [mira, secret])
    assert notes.check(ws) == []
    assert snapshot(ws.root / "canon") == before


def test_a_dossier_citing_an_unknown_id_is_reported(ws: Workspace) -> None:  # noqa: F811
    mira = entity(ws, "Mira Pell")
    dossier(ws, [mira, "f-deadbeef"])
    [problem] = notes.check(ws)
    assert "f-deadbeef" in problem
