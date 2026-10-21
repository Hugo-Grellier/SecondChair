"""`secondchair check-setup`: read-only checks of the GM's machine with a one-action fix each.

Reads only presence: never a token's or a runner's content, and never writes (PKG-19)."""

import json
import os
import shutil
import socket
import tomllib
from collections.abc import Callable
from pathlib import Path

from secondchair.core import capture, machine, workspace
from secondchair.core.server import MCP_PATH

FAIL, WARN, PASS = "FAIL", "WARN", "ok"
Result = tuple[str, str, str]  # level, what was checked, the one action that fixes it


def _reachable(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _registered(host: str, url: str, root: Path) -> bool | None:
    """Whether the host's configuration registers the Core at `url`; None if it cannot tell."""
    try:
        if host == "codex":
            home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
            servers = tomllib.loads((home / "config.toml").read_text()).get("mcp_servers", {})
            return servers.get("secondchair", {}).get("url") == url
        found = []
        for path in (Path.home() / ".claude.json", root / ".mcp.json"):
            if path.is_file():
                data = json.loads(path.read_text())
                found += [data.get("mcpServers", {})]
                found += [p.get("mcpServers", {}) for p in data.get("projects", {}).values()]
        if not found:
            return False if (Path.home() / ".claude.json").parent.is_dir() else None
        return any(s.get("secondchair", {}).get("url") == url for s in found)
    except OSError, ValueError, AttributeError:
        return None


def _playbooks_installed(host: str, plugins: list[str], skills: list[str]) -> bool | None:
    try:
        if host == "codex":
            home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
            return all((home / "skills" / s).exists() for s in skills)
        home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        listed = json.loads((home / "plugins/installed_plugins.json").read_text())["plugins"]
        return all(f"{p}@{p}" in listed for p in plugins)
    except OSError, ValueError, KeyError, TypeError:
        return None


def run(
    root: Path,
    *,
    port: int,
    runners: dict[str, list],
    transcription: list[str] | None,
    plugins: list[str],
    skills: list[str],
    which: Callable[[str], str | None] = shutil.which,
) -> list[Result]:
    """Every check, in the order a first-time GM fixes them."""
    out: list[Result] = []
    ws = None
    try:
        ws = workspace.load(root)
        out.append((PASS, f"workspace valid (language {ws.campaign_language})", ""))
    except workspace.WorkspaceError as e:
        out.append(
            (
                FAIL,
                f"workspace: {e}",
                "Run `secondchair init <dir> --language en --calendar absalom`.",
            )
        )
    if ws and not capture.time(ws)["current_date"]:
        out.append((WARN, "campaign date not set", "Run `secondchair date <date>`."))
    out.append(
        (PASS, f"Core listening on port {port}", "")
        if _reachable(port)
        else (
            FAIL,
            f"Core not reachable on port {port}",
            "Run `secondchair serve <workspace>` in another terminal.",
        )
    )
    out.append(
        (PASS, "Foundry token exists", "")
        if machine.foundry_token()
        else (
            FAIL,
            "Foundry token missing",
            "Run `secondchair token` and paste it in the Foundry module settings.",
        )
    )
    url = f"http://127.0.0.1:{port}{MCP_PATH}"
    present = [h for h in ("claude", "codex") if which(h)]
    out.append(
        (PASS, f"host binary on PATH: {', '.join(present)}", "")
        if present
        else (FAIL, "no agent host (claude, codex) on PATH", "Install Claude Code or Codex.")
    )
    for host in present:
        setup = f"Run `secondchair host setup {host}` and follow it."
        for yes, no, found in (
            (
                f"{host} registers the Core",
                f"{host} does not register the Core",
                _registered(host, url, root),
            ),
            (
                f"{host} has the playbooks",
                f"{host} lacks the playbooks",
                _playbooks_installed(host, plugins, skills),
            ),
        ):
            if found is None:
                out.append((WARN, f"cannot verify: {yes}", setup))
            else:
                out.append((PASS, yes, "") if found else (FAIL, no, setup))
    configured = any(runners.values())
    out.append(
        (PASS, "runners configured", "")
        if configured
        else (
            WARN,
            "no runner configured (jobs wait for your agent)",
            "Add `runners:` to the machine config.yaml, optional.",
        )
    )
    engine = (transcription or ["whisperx"])[0]
    out.append(
        (PASS, f"transcription engine {engine} on PATH", "")
        if which(engine)
        else (
            WARN,
            f"transcription engine {engine} not on PATH",
            f"Install {engine}, or skip it if you give transcripts yourself.",
        )
    )
    return out
