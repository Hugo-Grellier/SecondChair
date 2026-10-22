"""`secondchair check-setup`: checks of the GM's machine with a one-action fix each.

Writes no host or machine file (PKG-19). Reads only presence and the Core's URL: never a token's
or a runner's content, and no message quotes a host or machine configuration file's content or
its parse error.
"""

import json
import os
import shlex
import shutil
import socket
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from secondchair.core import capture, machine, workspace
from secondchair.core.server import LOOPBACK, MCP_PATH

FAIL, WARN, PASS = "FAIL", "WARN", "ok"
Result = tuple[str, str, str]  # level, what was checked, the one action that fixes it
UNREADABLE = (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError)


def _reachable(port: int) -> bool:
    try:
        with socket.create_connection((LOOPBACK, port), timeout=0.5):
            return True
    except OSError:
        return False


def _claude_dir() -> Path:
    """Where Claude Code keeps its state; it also holds `.claude.json` when set."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _claude_json() -> Path:
    set_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(set_dir) if set_dir else Path.home()) / ".claude.json"


def _has_core(servers: Any, url: str) -> bool:
    if servers is None:
        return False
    entry = servers.get("secondchair")  # a wrong shape raises: the caller cannot verify
    return entry is not None and entry.get("url") == url


def _registered(host: str, url: str, root: Path) -> bool | None:
    """Whether the host's configuration registers the Core at `url`; None if it cannot tell
    (no file, an unreadable or oddly shaped one)."""
    try:
        if host == "codex":
            home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
            return _has_core(
                tomllib.loads((home / "config.toml").read_text()).get("mcp_servers"), url
            )
        known = False  # whether any file could be read
        found = False
        user = _claude_json()
        if user.is_file():
            data = json.loads(user.read_text())
            projects = data.get("projects", {})
            mine = projects.get(str(root.resolve()), {}) if isinstance(projects, dict) else {}
            found = _has_core(data.get("mcpServers"), url) or _has_core(
                mine.get("mcpServers") if isinstance(mine, dict) else None, url
            )
            known = True
        project = root.resolve() / ".mcp.json"
        if project.is_file():
            found = found or _has_core(json.loads(project.read_text()).get("mcpServers"), url)
            known = True
        return True if found else (False if known else None)
    except UNREADABLE:
        return None


def _playbooks_installed(host: str, plugins: list[str], skills: list[str]) -> bool | None:
    try:
        if host == "codex":
            home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
            return all((home / "skills" / s).exists() for s in skills)
        listed = json.loads((_claude_dir() / "plugins/installed_plugins.json").read_text())
        return all(f"{p}@{p}" in listed["plugins"] for p in plugins)
    except UNREADABLE:
        return None


def run(
    root: Path,
    *,
    port: int | None,
    runners: dict[str, list],
    transcription: list[str] | None,
    plugins: list[str],
    skills: list[str],
    config_error: bool = False,
    which: Callable[[str], str | None] = shutil.which,
) -> list[Result]:
    """Every check, in the order a first-time GM fixes them. `port` is None with a
    `config_error`: the machine configuration could not be read."""
    out: list[Result] = []
    w = "" if root == Path() else f" -w {shlex.quote(str(root))}"
    ws = None
    try:
        ws = workspace.load(root)
        out.append((PASS, f"workspace valid (language {ws.campaign_language})", ""))
    except workspace.WorkspaceError as e:
        fix = (
            f"Run `secondchair upgrade{w}` or `secondchair check{w}`, or restore a backup."
            if (root / workspace.CONFIG_FILE).exists()
            else "Run `secondchair init <dir> --language en --calendar absalom`, "
            "or pass -w with the workspace."
        )
        out.append((FAIL, f"workspace: {e}", fix))
    if ws and not capture.time(ws)["current_date"]:
        out.append((WARN, "campaign date not set", f"Run `secondchair date <date>{w}`."))
    if config_error or port is None:
        out.append(
            (
                FAIL,
                "machine configuration unusable (port, runners or transcription)",
                f"Fix {machine.config_dir() / 'config.yaml'} (valid YAML; port, runners, "
                "transcription as documented), then run check-setup again.",
            )
        )
    else:
        out.append(
            (PASS, f"something answers on port {port} (not verified to be the Core)", "")
            if _reachable(port)
            else (
                FAIL,
                f"nothing answers on port {port}",
                f"Run `secondchair serve {shlex.quote(str(root))}` in another terminal.",
            )
        )
    try:
        token = machine.foundry_token()
    except OSError, ValueError:
        token, unreadable = None, True
    else:
        unreadable = False
    token_file = machine.config_dir() / machine.TOKEN_FILE
    out.append(
        (PASS, "Foundry token exists", "")
        if token
        else (
            FAIL,
            f"Foundry token {'unreadable' if unreadable else 'missing'}",
            f"Fix the permissions of {token_file}."
            if unreadable
            else "Run `secondchair token` and paste it in the Foundry module settings.",
        )
    )
    url = f"http://{LOOPBACK}:{port}{MCP_PATH}"
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
                None if port is None else _registered(host, url, root),
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
    out.append(
        (PASS, "runners configured", "")
        if any(runners.values())
        else (
            WARN,
            "no runner configured (jobs wait for your agent)",
            f"Optional: add `runners:` to {machine.config_dir() / 'config.yaml'}.",
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
