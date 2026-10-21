"""Pilot of the `develop-campaign-direction` skill's deterministic obligations (#175): the notes
and primer it prescribes, written under a workspace, leave canon untouched and pass the guards.
No model runs; the fixtures are what a good run produces."""

import hashlib
import re
from pathlib import Path

import yaml
from test_canon import act, call, entity, fact
from test_knowledge import learn, ws  # noqa: F401

from secondchair.core.workspace import Workspace

SECTIONS = (
    "Strengths",
    "Weak points",
    "Hooks",
    "Factions",
    "Near-term beats",
    "Loose long-term possibilities",
    "Critique",
)
CHECKLIST = (
    "Clichés",
    "False choices",
    "PC relevance",
    "Pacing",
    "Accidental railroading",
    "Payoff without setup",
    "Unearned revelations",
)
PITCHES = {
    "d-1a2b3c4d": "The bell is a debt",
    "d-2b3c4d5e": "The council fractures",
    "d-3c4d5e6f": "The river remembers",
}


def snapshot(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def pitch(note_id: str, title: str, cites: list[str]) -> str:
    front = {"id": note_id, "status": "draft", "alternatives": "campaign-direction", "cites": cites}
    body = "\n".join(f"## {s}\n\n- {title}: stub.\n" for s in SECTIONS[:-1])
    flags = "\n".join(f"- {item}: no flag." for item in CHECKLIST)
    return f"---\n{yaml.safe_dump(front)}---\n# {title}\n\n{body}\n## Critique\n\n{flags}\n"


def test_a_pilot_run_writes_notes_and_a_guarded_primer_and_changes_no_canon(
    ws: Workspace,  # noqa: F811
) -> None:
    mira = entity(ws, "Mira Pell")
    gate = fact(ws, "Mira Pell controls the gate.", entities=[mira])
    learn(ws, "party", gate)
    canon_before = snapshot(ws.root / "canon")

    direction = ws.root / "notes/direction"
    direction.mkdir(parents=True)
    (direction / "brief.md").write_text("# Brief\n\nTone: wary river town. Level range: 1-4.\n")
    for note_id, title in PITCHES.items():
        (direction / f"{title.lower().replace(' ', '-')}.md").write_text(
            pitch(note_id, title, [mira, gate])
        )
    primer = "Mira Pell holds the key to the gate. Bring a character with a reason to cross."
    assert not call(
        ws, "check_audience_content", audience="party", text=primer, cites=[gate]
    ).is_error
    act(ws, "write_prep", path="campaign-primer.md", text=primer)

    assert snapshot(ws.root / "canon") == canon_before  # no fact changed
    assert (ws.root / "prep/campaign-primer.md").read_text().strip() == primer
    notes = [p for p in direction.glob("*.md") if p.name != "brief.md"]
    assert len(notes) == 3
    ids = set()
    for p in notes:
        front = yaml.safe_load(p.read_text().split("---\n", 2)[1])
        assert re.fullmatch(r"d-[0-9a-f]{8}", front["id"]) and front["status"] == "draft"
        assert front["alternatives"] == "campaign-direction" and set(front["cites"]) == {mira, gate}
        ids.add(front["id"])
        text = p.read_text()
        assert all(f"## {s}" in text for s in SECTIONS)
        assert all(f"- {item}:" in text for item in CHECKLIST)
    assert ids == PITCHES.keys()
    # ponytail: asserts the ADR 0017 shape directly; use `secondchair notes check` once on main.


def test_a_primer_that_leaks_a_secret_is_refused_by_the_party_guard(ws: Workspace) -> None:  # noqa: F811
    ilex = entity(ws, "Ilex Venn")
    secret = fact(ws, "Ilex Venn tends the relay.", entities=[ilex])
    result = call(
        ws,
        "check_audience_content",
        audience="party",
        text="Ilex Venn tends the relay.",
        cites=[secret],
    )
    assert result.is_error
