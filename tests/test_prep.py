"""Prep notes: the Markdown handoff the GM reads to run a session, written by a delegated action
under `prep/` and undone like any other (ARC-04)."""

from test_delegation import call, gm, log, ws  # noqa: F401  (ws is a fixture)

from secondchair.core.workspace import Workspace

HANDOFF = "# Séance 2\n\nLes PJ arrivent au port.\n"


def write(ws: Workspace, path: str, text: str = HANDOFF):  # noqa: F811
    return call(ws, "write_prep", {"path": path, "text": text, "agent": "claude-prep"})


def test_a_prep_note_is_written_under_prep_and_logged(ws: Workspace) -> None:  # noqa: F811
    result = write(ws, "session-2/handoff.md")

    assert result.structured_content == {"entry": 1, "status": "applied"}
    assert (ws.root / "prep/session-2/handoff.md").read_text() == HANDOFF
    assert log(ws)[0]["responsibility"] == "prep"


def test_a_prep_note_outside_prep_or_not_markdown_is_refused(ws: Workspace) -> None:  # noqa: F811
    for path in ("../canon/entities/e-1.md", "/etc/x.md", "Session 2.md", "session-2/notes.txt"):
        result = write(ws, path)
        assert result.is_error, path
    assert not (ws.root / "prep").exists()
    assert not (ws.root / "canon/entities/e-1.md").exists()


def test_the_gm_undoes_a_prep_note(ws: Workspace) -> None:  # noqa: F811
    write(ws, "session-2/handoff.md")

    assert gm("log", "undo", "1", "--reason", "other", root=ws.root) == 0
    assert not (ws.root / "prep/session-2/handoff.md").exists()
