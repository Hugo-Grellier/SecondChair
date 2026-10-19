"""The `secondchair` command line."""

import argparse
import os
import sys
from pathlib import Path

import yaml

from secondchair.core import workspace
from secondchair.core.server import LOOPBACK, MCP_PATH, serve
from secondchair.core.tools import RegistrationError
from secondchair.core.workspace import WorkspaceError

DEFAULT_PORT = 7240


def machine_config_dir() -> Path:
    """The machine configuration (PKG-13): never inside a workspace."""
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "secondchair"


class MachineConfigError(Exception):
    """A machine configuration `serve` cannot use."""


def configured_port() -> int:
    path = machine_config_dir() / "config.yaml"
    if not path.is_file():
        return DEFAULT_PORT
    try:
        config = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise MachineConfigError(f"{path} is not valid YAML: {e}") from e
    port = config.get("port", DEFAULT_PORT) if isinstance(config, dict) else None
    if type(port) is not int or not 0 <= port <= 65535:
        raise MachineConfigError(f"{path}: port must be an integer between 0 and 65535.")
    return port


HOST_SETUP = {
    "claude": """Add SecondChair to Claude Code for every project with:

  claude mcp add --scope user --transport http secondchair {url}

or, for one project, put this in its .mcp.json:

{{"mcpServers": {{"secondchair": {{"type": "http", "url": "{url}"}}}}}}
""",
    "codex": """Add SecondChair to Codex by putting this in ~/.codex/config.toml:

[mcp_servers.secondchair]
url = "{url}"
""",
}


def host_setup(host: str) -> str:
    """The host configuration for the Core on this machine; never written anywhere (PKG-19)."""
    return HOST_SETUP[host].format(url=f"http://{LOOPBACK}:{configured_port()}{MCP_PATH}")


def _calendar_arg(value: str) -> str | dict:
    """A calendar name, or the content of a `.yaml` / `.yml` file declaring one."""
    if not value.endswith((".yaml", ".yml")):
        return value
    path = Path(value)
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise WorkspaceError(f"{path} is not valid YAML: {e}") from e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secondchair")
    commands = parser.add_subparsers(dest="command", required=True)
    init_cmd = commands.add_parser("init", help="create a campaign workspace")
    init_cmd.add_argument("workspace", type=Path)
    init_cmd.add_argument(
        "--language", required=True, help="campaign language, a BCP 47 tag; fixed once set"
    )
    init_cmd.add_argument(
        "--calendar",
        required=True,
        help="campaign calendar, fixed once set: a System extension's calendar name (absalom) "
        "or a YAML file declaring one",
    )
    serve_cmd = commands.add_parser("serve", help="serve a campaign workspace on 127.0.0.1")
    serve_cmd.add_argument("workspace", type=Path)
    host_cmd = commands.add_parser("host", help="agent host configuration")
    host_sub = host_cmd.add_subparsers(dest="host_command", required=True)
    setup_cmd = host_sub.add_parser("setup", help="print the configuration for an agent host")
    setup_cmd.add_argument("host", choices=sorted(HOST_SETUP))
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            calendar = _calendar_arg(args.calendar)
            ws = workspace.init(args.workspace, args.language, calendar)
            print(
                f"Created campaign workspace {ws.root} (campaign language {ws.campaign_language})"
            )
        elif args.command == "host":
            print(host_setup(args.host), end="")
        else:
            serve(workspace.load(args.workspace), configured_port())
    except (WorkspaceError, MachineConfigError, RegistrationError, OSError) as e:
        print(f"secondchair: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
