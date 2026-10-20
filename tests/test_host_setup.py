import tomllib
from pathlib import Path

import pytest

from secondchair import runner
from secondchair.cli import main


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home with existing Claude Code and Codex configurations and SecondChair on port 7300."""
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "config.toml").write_text('model = "o4"\n')
    (home / ".claude.json").write_text("{}\n")
    (home / ".config" / "secondchair").mkdir(parents=True)
    (home / ".config" / "secondchair" / "config.yaml").write_text("port: 7300\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    return home


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_host_setup_codex_prints_a_config_toml_entry(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["host", "setup", "codex"]) == 0
    out = capsys.readouterr().out
    toml = out[out.index("[mcp_servers.secondchair]") : out.index("\nInstall")]
    assert tomllib.loads(toml) == {
        "mcp_servers": {"secondchair": {"url": "http://127.0.0.1:7300/mcp"}}
    }


def test_host_setup_claude_prints_the_mcp_add_command(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["host", "setup", "claude"]) == 0
    out = capsys.readouterr().out
    assert (
        "claude mcp add --scope user --transport http secondchair http://127.0.0.1:7300/mcp" in out
    )


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_host_setup_writes_no_host_file(home: Path, tmp_path: Path, host: str) -> None:
    before = _snapshot(tmp_path)
    assert main(["host", "setup", host]) == 0
    assert _snapshot(tmp_path) == before


def test_host_setup_prints_how_to_install_the_playbooks(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["host", "setup", "claude"])
    out = capsys.readouterr().out
    assert f"claude plugin marketplace add {runner.PLAYBOOKS}" in out
    assert "claude plugin install secondchair@secondchair\n" in out
    assert "claude plugin install secondchair-foundry@secondchair-foundry\n" in out  # ARC-10
    main(["host", "setup", "codex"])
    out = capsys.readouterr().out
    for skill in runner.skills():
        assert f"ln -sfn {skill} ~/.codex/skills/{skill.name}" in out
