"""The opportunities loop (#185): wrap -> `propose-opportunities` -> the GM adopts -> prep reads it,
over three synthetic sessions. The skill's note is a fixture (no model); the Core is real."""

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml
from test_canon import act, entity, fact
from test_capture import ws  # noqa: F401  (a fixture)

from secondchair import runner
from secondchair.core import capture, delegation, index, jobs, tools, workspace
from secondchair.core.knowledge import AudienceRefused, guard
from secondchair.core.workspace import Workspace

SAMPLE = Path(__file__).parents[1] / "sample-campaign/sessions"
# One played line per session: two from the sample campaign, one synthetic.
LINES = {
    1: "The party inspected the dry gauge at the Weir and saw it stay at zero while the bell rang.",
    2: "The party opened the bypass at the Weir on 0302-05-01.",
    3: "The party carried a lantern to the Cistern door and found it barred.",
}
SECRET = "Sable keeps the Cistern key and has told only Edda."
NOTE = """---
id: d-{n:08x}
status: draft
cites: [{fact}]
---
# Opportunities after session {n}

## The lit door
The barred door may tempt the party back. (Sable's key stays a GM-only fact: {secret_id}.)
**Because**: {fact} ("{quote}").
**Touches**: d-0000beef.
**For**: the whole party.
**Cost of ignoring it**: nothing changes.
"""


def front(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---")[1])


def copy_sessions(tmp: Path) -> dict[int, Path]:
    """A tmp copy of the sample campaign's session notes, plus a third synthetic one."""
    sessions = tmp / "sessions"
    shutil.copytree(SAMPLE, sessions)
    (sessions / "03-lantern.md").write_text(f"- **S3-01**: {LINES[3]}\n")
    paths = sorted(sessions.glob("0*.md"))
    return dict(enumerate(paths, 1))


def wrap(ws: Workspace, n: int, notes: Path, duplicate_of: str | None = None) -> str:  # noqa: F811
    job = jobs.queue(
        ws,
        playbook="wrap-a-session",
        inputs={"session": str(n), "notes": str(notes)},
        expected_output="",
        responsibility="memory",
        tier="standard",
    )["id"]
    jobs.start(ws, job, {"host": "h", "model": "m", "effort": "e"}, manual=True)
    capture.capture(
        ws,
        job,
        source=str(notes),
        locator=f"{notes.name}:1",
        quote=LINES[n],
        statement=LINES[n],
        date="4726-01-02",
        known_by=["party"],
        classification="duplicate" if duplicate_of else "certain",
        reason="repeats a prepared clue" if duplicate_of else None,
        duplicate_of=duplicate_of,
    )
    capture.consolidate(ws, job)
    return next((f["id"] for f in index.search_facts(ws) if f["statement"] == LINES[n]), "")


def run_loop(ws: Workspace, tmp: Path) -> dict[str, str]:  # noqa: F811
    """Three sessions. Returns every file the loop wrote, by relative path."""
    notes = copy_sessions(tmp)
    sable = entity(ws, "Sable")
    secret = fact(ws, SECRET, entities=[sable])  # known to nobody: the party never hears it
    opportunities = ws.root / "notes/opportunities"
    opportunities.mkdir(parents=True)
    for n in (1, 2, 3):
        played = wrap(ws, n, notes[n])
        path = opportunities / f"session-{n}.md"
        path.write_text(NOTE.format(n=n, fact=played, quote=LINES[n], secret_id=secret))
        # The GM adopts sessions 1 and 2, rejects 3.
        status = "adopted" if n < 3 else "rejected"
        path.write_text(path.read_text().replace("status: draft", f"status: {status}"))
        adopted = [p for p in sorted(opportunities.glob("*.md")) if front(p)["status"] == "adopted"]
        assert [front(p)["id"] for p in adopted] == [f"d-{i:08x}" for i in range(1, min(n, 2) + 1)]
        line = f"The Cistern door is barred. ({LINES[n]})"
        guard(
            ws, "party", LINES[n], [played]
        )  # a player-facing line from played, party-known facts
        with pytest.raises(AudienceRefused):  # the guard is live: the secret does not pass
            guard(ws, "party", f"Sable has the key. {line}", [played])
        done = act(
            ws, "write_prep", path=f"session-{n + 1}/handoff.md", text=f"# Handoff\n{line}\n"
        )
        assert done["status"] == "applied"
    return {
        str(p.relative_to(ws.root)): p.read_text()
        for p in sorted(ws.root.glob("[np][or]*/**/*.md"))
    }


def test_three_sessions_keep_opportunities_out_of_canon_and_secrets_out_of_party_text(
    ws: Workspace,  # noqa: F811
    tmp_path: Path,
) -> None:
    files = run_loop(ws, tmp_path)

    statements = " ".join(f["statement"] for f in index.search_facts(ws))
    assert "lit door" not in statements and "Opportunities after" not in statements
    assert index.search_facts(ws, text="lit door") == []
    assert not any("lit door" in p.read_text() for p in (ws.root / "canon").rglob("*.md"))
    assert not any("Sable" in text for path, text in files.items() if path.startswith("prep/"))
    assert sorted(files) == [f"notes/opportunities/session-{n}.md" for n in (1, 2, 3)] + [
        f"prep/session-{n}/handoff.md" for n in (2, 3, 4)
    ]


def test_the_loop_is_repeatable(tmp_path: Path) -> None:
    runs = []
    for name in ("a", "b"):
        w = workspace.init(tmp_path / name / "campaign", "en", "absalom")
        delegation.change_moment(w, "between-sessions")
        files = run_loop(w, tmp_path / name)
        # Ids are minted per workspace: compare the files with them masked.
        [signals] = [t for t in tools.load_tools(w) if t.name == "session_signals"]
        files["signals"] = json.dumps([signals.fn(n) for n in (1, 2, 3)], sort_keys=True)
        runs.append({p: re.sub(r"\b[fe]-[0-9a-f]+", "<id>", t) for p, t in files.items()})
    assert runs[0] == runs[1]


def test_the_skill_is_registered_on_the_standard_tier() -> None:
    meta = runner.playbook("propose-opportunities")
    assert (meta["tier"], meta["responsibility"], meta["inputs"]) == ("standard", "prep", "session")


def test_session_signals_report_unused_prep_spotlight_and_triggers(
    ws: Workspace,  # noqa: F811
    tmp_path: Path,
) -> None:
    [signals] = [t for t in tools.load_tools(ws) if t.name == "session_signals"]
    assert signals.fn(1) == {
        "session": 1,
        "unused_prep": {"handoff": None, "clues": [], "warnings": []},
        "spotlight": {},
        "fulfilled_triggers": [],
    }  # a session with nothing

    notes = copy_sessions(tmp_path)
    inn, brand, _guild, who = (entity(ws, n) for n in ("Inn", "Brand", "Guild", "Who"))
    seen = fact(ws, "The gauge stays at zero while the bell rings.")
    unseen = fact(ws, "The register is hidden under the Guild floor.")
    pending = fact(ws, "Brand has been spared by the party.")
    graph = {
        "conclusions": [{"id": "who", "fact": unseen}],
        "nodes": [{"id": "inn", "entity": inn, "entry": True}],
        "clues": [
            {"id": "clue-seen", "fact": seen, "on": "inn", "points_to": ["who"]},
            {"id": "clue-unseen", "fact": unseen, "on": "inn", "points_to": ["who"]},
        ],
    }
    act(ws, "record_mystery", mystery=who, **graph)
    act(
        ws,
        "write_prep",
        path="session-1/handoff.md",
        text="# Handoff\n```yaml\nclues: [clue-seen, clue-unseen]\n```\n",
    )
    dossier = ws.root / "notes/npcs" / f"{brand}.md"
    dossier.parent.mkdir(parents=True)
    triggers = [
        {"if": "she softens", "facts": [pending]},
        {"if": "she hardens", "facts": [pending, "f-00000000"]},
    ]
    dossier.write_text(
        index.join_doc({"id": "d-00000001", "status": "adopted", "triggers": triggers}, "")
    )

    wrap(ws, 1, notes[1], duplicate_of=seen)  # the table found the first clue
    first = signals.fn(1)
    assert first["unused_prep"]["clues"] == ["clue-unseen"]
    assert first["unused_prep"]["warnings"]  # the three-clue rule is open for this mystery
    assert {w["mystery"] for w in first["unused_prep"]["warnings"]} == {who}
    assert first["fulfilled_triggers"] == [
        {"note": brand, "id": "d-00000001", "if": "she softens", "facts": [pending]}
    ]
    assert signals.fn(1) == first  # stable across runs
