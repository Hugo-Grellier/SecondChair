import pytest

from secondchair.cli import main
from secondchair.core import index, notes, workspace


def note(ws, name, front, body="Pitch."):
    path = ws.root / "notes" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(f"{k}: {v}\n" for k, v in front.items())
    path.write_text(f"---\n{lines}---\n{body}\n" if front else body)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return workspace.init(tmp_path / "campaign", "fr", "absalom")


def test_a_valid_set_and_plain_notes_report_nothing(ws):
    note(ws, "plain.md", {})
    note(ws, "other.md", {"title": "x"})
    note(ws, "a.md", {"id": "d-00000001", "status": "adopted", "alternatives": "arc"})
    note(ws, "b.md", {"id": "d-00000002", "status": "rejected", "alternatives": "arc"})
    note(ws, "c.md", {"id": "d-00000003", "status": "draft", "supersedes": "[d-00000004]"})
    note(ws, "d.md", {"id": "d-00000004", "status": "superseded"})
    assert notes.check(ws) == []
    assert index.rebuild(ws) == []


@pytest.mark.parametrize(
    ("files", "problem"),
    [
        ([{"id": "x1", "status": "draft"}], "malformed id"),
        ([{"status": "draft"}], "malformed id"),
        ([{"id": "d-00000001", "status": "draft"}] * 2, "duplicate id"),
        ([{"id": "d-00000001", "status": "maybe"}], "unknown status"),
        ([{"id": "d-00000001", "status": "draft", "cites": "[f-nope]"}], "not in canon"),
        ([{"id": "d-00000001", "status": "draft", "supersedes": "[d-0000ffff]"}], "unknown note"),
        (
            [
                {"id": "d-00000001", "status": "draft", "supersedes": "[d-00000002]"},
                {"id": "d-00000002", "status": "rejected"},
            ],
            "not marked superseded",
        ),
    ],
)
def test_each_problem_is_reported(ws, files, problem):
    for i, front in enumerate(files):
        note(ws, f"n{i}.md", front)
    [error] = [e for e in notes.check(ws) if problem in e]
    assert error and any(problem in e for e in index.rebuild(ws))


def test_a_cite_that_resolves_in_canon_is_fine(ws):
    (ws.root / "canon/facts").mkdir(parents=True, exist_ok=True)
    (ws.root / "canon/facts/f-1.md").write_text("x")
    note(ws, "a.md", {"id": "d-00000001", "status": "draft", "cites": "[f-1]"})
    assert notes.check(ws) == []


def test_two_adopted_in_one_alternative_set_are_reported(ws, capsys):
    note(ws, "a.md", {"id": "d-00000001", "status": "adopted", "alternatives": "arc"})
    assert main(["notes", "check", "-w", str(ws.root)]) == 0
    note(ws, "b.md", {"id": "d-00000002", "status": "adopted", "alternatives": "arc"})
    note(ws, "c.md", {"id": "d-00000003", "status": "adopted", "alternatives": "other"})
    assert main(["notes", "check", "-w", str(ws.root)]) == 1
    assert "2 adopted notes" in capsys.readouterr().err
