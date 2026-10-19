from pathlib import Path

import pytest
import yaml

from secondchair.cli import main


def test_init_creates_a_workspace_with_schema_version_and_language(tmp_path: Path) -> None:
    ws = tmp_path / "campaign"
    assert main(["init", str(ws), "--language", "fr"]) == 0

    config = yaml.safe_load((ws / "workspace.yaml").read_text())
    assert config == {"schema_version": 1, "campaign_language": "fr"}
    assert (ws / ".secondchair").is_dir()
    assert ".secondchair/" in (ws / ".gitignore").read_text().splitlines()


def test_campaign_language_cannot_be_changed_after_init(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["init", str(tmp_path), "--language", "fr"])

    assert main(["init", str(tmp_path), "--language", "en"]) == 1
    assert "campaign language is fixed" in capsys.readouterr().err
    assert yaml.safe_load((tmp_path / "workspace.yaml").read_text())["campaign_language"] == "fr"


def test_init_rejects_a_language_that_is_not_a_bcp47_tag(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path), "--language", "French!"]) == 1
    assert not (tmp_path / "workspace.yaml").exists()


def test_init_keeps_an_existing_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("notes.tmp\n")
    main(["init", str(tmp_path), "--language", "en-GB"])
    assert (tmp_path / ".gitignore").read_text() == "notes.tmp\n.secondchair/\n"
