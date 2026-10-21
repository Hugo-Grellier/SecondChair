import json
import socket
from pathlib import Path

import pytest

from secondchair import runner
from secondchair.cli import main


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".config" / "secondchair").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    for var in ("XDG_CONFIG_HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    (tmp_path / "bin").mkdir()
    monkeypatch.chdir(tmp_path)
    return home


def _tool(tmp_path: Path, name: str) -> None:
    (tmp_path / "bin" / name).write_text("#!/bin/sh\n")
    (tmp_path / "bin" / name).chmod(0o755)


def test_an_empty_machine_fails_with_a_fix_per_problem(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (home / ".config/secondchair/config.yaml").write_text("port: 1\n")
    assert main(["init", str(tmp_path / "w"), "--language", "en", "--calendar", "absalom"]) == 0
    capsys.readouterr()
    assert main(["check-setup", "-w", str(tmp_path / "w")]) == 1
    out = capsys.readouterr().out
    assert "FAIL Core not reachable on port 1" in out
    assert "Fix: Run `secondchair serve" in out
    assert "FAIL Foundry token missing" in out
    assert "FAIL no agent host" in out
    assert "WARN campaign date not set" in out
    assert "Moment:" in out  # the status block


def test_a_ready_machine_passes_without_printing_the_token(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        (home / ".config/secondchair/config.yaml").write_text(
            f"port: {port}\nrunners:\n  fast: [{{host: claude, model: m, effort: low}}]\n"
        )
        (home / ".config/secondchair/foundry-token").write_text("sekrit-token\n")
        url = f"http://127.0.0.1:{port}/mcp"
        (home / ".claude.json").write_text(
            json.dumps({"mcpServers": {"secondchair": {"url": url}}})
        )
        names = [
            json.loads((d / ".claude-plugin/plugin.json").read_text())["name"]
            for d in runner.playbook_dirs()
        ]
        plugins = home / ".claude/plugins"
        plugins.mkdir(parents=True)
        (plugins / "installed_plugins.json").write_text(
            json.dumps({"plugins": {f"{n}@{n}": [] for n in names}})
        )
        _tool(tmp_path, "claude")
        _tool(tmp_path, "whisperx")
        assert main(["init", str(tmp_path / "w"), "--language", "en", "--calendar", "absalom"]) == 0
        capsys.readouterr()
        code = main(["check-setup", "-w", str(tmp_path / "w")])
    out = capsys.readouterr().out
    assert "FAIL" not in out, out
    assert code == 0
    assert "sekrit-token" not in out
    assert "ok   claude registers the Core" in out
    assert "ok   claude has the playbooks" in out


def test_an_unregistered_host_and_an_unreadable_config(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tool(tmp_path, "codex")
    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_text("model = 'o4'\n")
    assert main(["check-setup", "-w", str(tmp_path / "nowhere")]) == 1
    out = capsys.readouterr().out
    assert "FAIL workspace:" in out
    assert "FAIL codex does not register the Core" in out
    assert "Fix: Run `secondchair host setup codex`" in out
    (home / ".codex/config.toml").write_text("= broken")
    main(["check-setup", "-w", str(tmp_path / "nowhere")])
    assert "WARN cannot verify: codex registers the Core" in capsys.readouterr().out
