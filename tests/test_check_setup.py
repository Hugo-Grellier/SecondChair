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
    assert "FAIL nothing answers on port 1" in out
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


def _workspace(tmp_path: Path) -> Path:
    assert main(["init", str(tmp_path / "w"), "--language", "en", "--calendar", "absalom"]) == 0
    return tmp_path / "w"


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_no_configuration_content_is_ever_printed(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    w = _workspace(tmp_path)
    for tool in ("claude", "codex"):
        _tool(tmp_path, tool)
    (home / ".config/secondchair/config.yaml").write_text('x: "SECRET15\n')
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "x": {"env": {"K": "SECRET1"}},
                    "secondchair": {"url": "http://SECRET2:pw@127.0.0.1:7240/mcp"},
                },
                "projects": {str(w.resolve()): {"mcpServers": {"y": {"env": {"T": "SECRET3"}}}}},
            }
        )
    )
    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_text(
        '[mcp_servers.z]\nenv = {K = "SECRET4"}\n'
        '[mcp_servers.secondchair]\nurl = "http://SECRET5@x"\n'
    )
    (w / ".mcp.json").write_text('{"mcpServers": {"a": "SECRET6"')  # broken
    code = main(["check-setup", "-w", str(w)])
    out = _out(capsys)
    assert code == 1
    assert "SECRET" not in out
    assert "FAIL machine configuration unusable" in out  # and the check went on
    assert "FAIL no agent host" not in out
    assert "FAIL codex does not register the Core" in out or "cannot verify: codex" in out
    # wrong shapes and runaway nesting
    (home / ".config/secondchair/config.yaml").unlink()
    (w / ".mcp.json").write_text("[" * 100000 + '"SECRET8"' + "]" * 100000)
    (home / ".claude.json").write_text('[1, "SECRET9"]')
    (home / ".codex/config.toml").write_text('mcp_servers = ["SECRET10"]\n')
    main(["check-setup", "-w", str(w)])
    out = _out(capsys)
    assert "SECRET" not in out
    assert "WARN cannot verify: claude registers the Core" in out
    assert "WARN cannot verify: codex registers the Core" in out


def test_claude_config_dir_and_the_workspace_entry(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w = _workspace(tmp_path)
    _tool(tmp_path, "claude")
    url = {"secondchair": {"url": "http://127.0.0.1:7240/mcp"}}
    elsewhere = tmp_path / "cc"
    elsewhere.mkdir()
    (elsewhere / ".claude.json").write_text(json.dumps({"mcpServers": url}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(elsewhere))
    main(["check-setup", "-w", str(w)])
    assert "ok   claude registers the Core" in _out(capsys)
    # only this workspace's project entry counts
    (elsewhere / ".claude.json").write_text(
        json.dumps({"projects": {"/other": {"mcpServers": url}}})
    )
    main(["check-setup", "-w", str(w)])
    assert "FAIL claude does not register the Core" in _out(capsys)
    (elsewhere / ".claude.json").write_text(
        json.dumps({"projects": {str(w.resolve()): {"mcpServers": url}}})
    )
    main(["check-setup", "-w", str(w)])
    assert "ok   claude registers the Core" in _out(capsys)
    # a missing user file and no project file: cannot verify
    (elsewhere / ".claude.json").unlink()
    main(["check-setup", "-w", str(w)])
    assert "WARN cannot verify: claude registers the Core" in _out(capsys)
    (w / ".mcp.json").write_text(json.dumps({"mcpServers": url}))
    main(["check-setup", "-w", str(w)])
    assert "ok   claude registers the Core" in _out(capsys)


def test_an_unreadable_token_is_a_fail_and_fixes_name_the_workspace(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    w = _workspace(tmp_path)
    (home / ".config/secondchair/foundry-token").mkdir()  # reading a directory raises OSError
    assert main(["check-setup", "-w", str(w)]) == 1
    out = _out(capsys)
    assert "FAIL Foundry token unreadable" in out
    assert f"secondchair date <date> -w {w}" in out
    (w / "workspace.yaml").write_text("campaign_language: [")
    main(["check-setup", "-w", str(w)])
    assert f"secondchair upgrade -w {w}" in _out(capsys)
