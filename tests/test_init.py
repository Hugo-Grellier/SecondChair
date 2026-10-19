from pathlib import Path

import pytest
import yaml

from secondchair.cli import main
from secondchair.workspace import WorkspaceError, load


def test_init_creates_a_workspace_with_schema_version_and_language(tmp_path: Path) -> None:
    ws = tmp_path / "campaign"
    assert main(["init", str(ws), "--language", "fr", "--calendar", "absalom"]) == 0

    config = yaml.safe_load((ws / "workspace.yaml").read_text())
    assert config == {"schema_version": 1, "campaign_language": "fr", "calendar": "absalom"}
    assert (ws / ".secondchair").is_dir()
    assert ".secondchair/" in (ws / ".gitignore").read_text().splitlines()


def test_campaign_language_cannot_be_changed_after_init(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["init", str(tmp_path), "--language", "fr", "--calendar", "absalom"])

    assert main(["init", str(tmp_path), "--language", "en", "--calendar", "absalom"]) == 1
    assert "campaign language and calendar are fixed" in capsys.readouterr().err
    assert yaml.safe_load((tmp_path / "workspace.yaml").read_text())["campaign_language"] == "fr"


def test_init_rejects_a_language_that_is_not_a_bcp47_tag(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path), "--language", "French!", "--calendar", "absalom"]) == 1
    assert not (tmp_path / "workspace.yaml").exists()


def test_init_keeps_an_existing_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("notes.tmp\n")
    main(["init", str(tmp_path), "--language", "en-GB", "--calendar", "absalom"])
    assert (tmp_path / ".gitignore").read_text() == "notes.tmp\n.secondchair/\n"


def test_init_requires_a_calendar(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["init", str(tmp_path), "--language", "fr"])
    assert not (tmp_path / "workspace.yaml").exists()


def test_init_refuses_an_unknown_calendar_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", str(tmp_path), "--language", "fr", "--calendar", "gregorian"]) == 1
    assert "gregorian" in capsys.readouterr().err
    assert not (tmp_path / "workspace.yaml").exists()


DECLARED = {
    "months": [{"name": "Thaw", "days": 36}, {"name": "Lanternnight", "days": 1}],
    "leap": {"interval": 5, "first_year": 2, "month": 2},
    "week": {
        "days": ["A", "B", "C", "D", "E", "F"],
        "anchor": {"date": "0300-01-01", "weekday": 1},
    },
    "era": "AF",
}


def test_init_declares_a_calendar_inline_from_a_file(tmp_path: Path) -> None:
    source = tmp_path / "calendar.yaml"
    source.write_text(yaml.safe_dump(DECLARED))
    ws = tmp_path / "campaign"
    assert main(["init", str(ws), "--language", "en", "--calendar", str(source)]) == 0

    assert yaml.safe_load((ws / "workspace.yaml").read_text())["calendar"] == DECLARED
    assert load(ws).calendar.display("0302-02-02") == "2 Lanternnight 302 AF"


def test_init_refuses_an_invalid_declared_calendar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "calendar.yaml"
    source.write_text(yaml.safe_dump({**DECLARED, "months": []}))
    ws = tmp_path / "campaign"
    assert main(["init", str(ws), "--language", "en", "--calendar", str(source)]) == 1
    assert "month" in capsys.readouterr().err
    assert not ws.exists()


def test_calendar_cannot_be_changed_after_init(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["init", str(tmp_path), "--language", "fr", "--calendar", "absalom"])
    source = tmp_path / "calendar.yaml"
    source.write_text(yaml.safe_dump(DECLARED))

    assert main(["init", str(tmp_path), "--language", "fr", "--calendar", str(source)]) == 1
    assert "calendar are fixed" in capsys.readouterr().err
    assert yaml.safe_load((tmp_path / "workspace.yaml").read_text())["calendar"] == "absalom"


def test_label_overrides_in_the_workspace_change_display_only(tmp_path: Path) -> None:
    main(["init", str(tmp_path), "--language", "fr", "--calendar", "absalom"])
    config = tmp_path / "workspace.yaml"
    data = yaml.safe_load(config.read_text())
    weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    data["calendar"] = {"name": "absalom", "labels": {"weekdays": weekdays}}
    config.write_text(yaml.safe_dump(data))

    calendar = load(tmp_path).calendar
    assert calendar.weekday_name("4726-01-01") == "Jeudi"
    assert calendar.canonical("4726-01-01") == "4726-01-01"


def test_a_workspace_without_a_calendar_is_refused(tmp_path: Path) -> None:
    (tmp_path / "workspace.yaml").write_text("schema_version: 1\ncampaign_language: fr\n")
    with pytest.raises(WorkspaceError, match="calendar"):
        load(tmp_path)
