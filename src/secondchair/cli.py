"""The `secondchair` command line."""

import argparse
import sys
from pathlib import Path

import yaml

from secondchair.core import canon, delegation, index, machine, workspace
from secondchair.core.delegation import DelegationError
from secondchair.core.index import CanonError
from secondchair.core.server import LOOPBACK, MCP_PATH, serve
from secondchair.core.tools import RegistrationError
from secondchair.core.workspace import WorkspaceError

DEFAULT_PORT = 7240


class MachineConfigError(Exception):
    """A machine configuration `serve` cannot use."""


def configured_port() -> int:
    path = machine.config_dir() / "config.yaml"
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


def interactive() -> bool:
    """Whether the GM is at an interactive terminal: the CLI's authenticated Surface (ARC-13)."""
    return sys.stdin.isatty()


def _gm_command(args: argparse.Namespace) -> str:
    """Run a GM gesture on the workspace; the message to print."""
    ws = workspace.load(args.workspace)
    auth = interactive()
    if args.command == "moment":
        if not auth:  # DEL-03a
            raise DelegationError("Changing the moment needs an interactive terminal.")
        if not delegation.change_moment(ws, args.moment):
            return f"Already in {args.moment}."
        return f"Moment: {args.moment}. The previous moment's action log is frozen."
    if args.command == "confirm":
        if not auth:  # DEL-29
            raise DelegationError("Confirming a GM decision needs an interactive terminal.")
        entry = canon.confirm(ws, args.id, "cli", auth)
        return f"Confirmed {args.id} as a GM decision (entry {entry['id']})."
    if args.command == "approve":
        delegation.approve(ws, args.entry, "cli", auth)
        return f"Approved and applied entry {args.entry}."
    if args.command == "reject":
        delegation.reject(ws, args.entry, args.reason, "cli", auth)
        return f"Rejected entry {args.entry} ({args.reason})."
    delegation.undo(ws, args.entry, args.reason, "cli", auth)
    return f"Undid entry {args.entry} ({args.reason})."


def check(ws: workspace.Workspace) -> int:
    """Rebuild the derived index from the workspace alone (CAN-10); 1 if a file is invalid."""
    errors = index.rebuild(ws)
    for error in errors:
        print(f"secondchair: {error}", file=sys.stderr)
    entities, facts, events = index.counts(ws)
    print(f"Indexed {entities} entities, {facts} facts, {events} events from {ws.root}.")
    return 1 if errors else 0


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
    commands.add_parser(
        "token", help="print the token the Foundry module connects with, creating it once"
    )
    host_cmd = commands.add_parser("host", help="agent host configuration")
    host_sub = host_cmd.add_subparsers(dest="host_command", required=True)
    setup_cmd = host_sub.add_parser("setup", help="print the configuration for an agent host")
    setup_cmd.add_argument("host", choices=sorted(HOST_SETUP))
    in_workspace = argparse.ArgumentParser(add_help=False)
    in_workspace.add_argument(
        "-w", "--workspace", type=Path, default=Path(), help="campaign workspace (default: .)"
    )
    reason = argparse.ArgumentParser(add_help=False)
    reason.add_argument("--reason", required=True, choices=delegation.REASONS)
    moment_cmd = commands.add_parser(
        "moment", parents=[in_workspace], help="change the current moment (interactive only)"
    )
    moment_cmd.add_argument("moment", choices=delegation.MOMENTS)
    for name, help_text, parents in (
        ("approve", "approve a pending action", [in_workspace]),
        ("reject", "reject a pending action", [in_workspace, reason]),
    ):
        commands.add_parser(name, parents=parents, help=help_text).add_argument("entry", type=int)
    commands.add_parser(
        "confirm",
        parents=[in_workspace],
        help="confirm a fact or event relayed from your words as a GM decision (interactive only)",
    ).add_argument("id", help="the fact or event id, f-… or v-…")
    commands.add_parser(
        "check", parents=[in_workspace], help="rebuild the derived index and report invalid files"
    )
    log_cmd = commands.add_parser("log", help="the action log")
    log_sub = log_cmd.add_subparsers(dest="log_command", required=True)
    undo_cmd = log_sub.add_parser(
        "undo", parents=[in_workspace, reason], help="undo an action of the current moment"
    )
    undo_cmd.add_argument("entry", type=int)
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            calendar = _calendar_arg(args.calendar)
            ws = workspace.init(args.workspace, args.language, calendar)
            print(
                f"Created campaign workspace {ws.root} (campaign language {ws.campaign_language})"
            )
        elif args.command == "token":
            print("Foundry token (keep it secret; paste it into the SecondChair module settings):")
            print(machine.ensure_foundry_token())
        elif args.command == "host":
            print(host_setup(args.host), end="")
        elif args.command == "check":
            return check(workspace.load(args.workspace))
        elif args.command == "serve":
            serve(workspace.load(args.workspace), configured_port())
        else:
            print(_gm_command(args))
    except (
        WorkspaceError,
        MachineConfigError,
        RegistrationError,
        DelegationError,
        CanonError,
        OSError,
    ) as e:
        print(f"secondchair: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
