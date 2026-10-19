"""The `secondchair` command line."""

import argparse
import sys
from pathlib import Path

import yaml

from secondchair import runner
from secondchair.core import canon, delegation, index, jobs, machine, workspace
from secondchair.core.delegation import DelegationError
from secondchair.core.index import CanonError
from secondchair.core.server import LOOPBACK, MCP_PATH, serve
from secondchair.core.tools import RegistrationError
from secondchair.core.workspace import WorkspaceError

DEFAULT_PORT = 7240


class MachineConfigError(Exception):
    """A machine configuration `serve` cannot use."""


def _machine_config() -> tuple[Path, dict]:
    path = machine.config_dir() / "config.yaml"
    if not path.is_file():
        return path, {}
    try:
        config = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise MachineConfigError(f"{path} is not valid YAML: {e}") from e
    if not isinstance(config, dict):
        raise MachineConfigError(f"{path} must be a YAML mapping.")
    return path, config


def configured_port() -> int:
    path, config = _machine_config()
    port = config.get("port", DEFAULT_PORT)
    if type(port) is not int or not 0 <= port <= 65535:
        raise MachineConfigError(f"{path}: port must be an integer between 0 and 65535.")
    return port


def configured_runners() -> tuple[dict[str, list[dict[str, str]]], dict[str, list]]:
    """The runner configuration, keyed by tier only (ARC-26), and the agent hosts' command
    templates: the built-in ones, overridden or extended by the machine configuration's."""
    path, config = _machine_config()
    runners = config.get("runners") or {}
    hosts = config.get("hosts") or {}
    if not isinstance(runners, dict) or not set(runners) <= set(jobs.TIERS):
        raise MachineConfigError(f"{path}: runners must map tiers ({', '.join(jobs.TIERS)}).")
    for tier, entries in runners.items():
        if not isinstance(entries, list) or not all(
            isinstance(e, dict)
            and sorted(e) == sorted(jobs.CONFIG_KEYS)
            and all(isinstance(v, str) and v for v in e.values())
            for e in entries
        ):
            raise MachineConfigError(
                f"{path}: runners.{tier} must be a list of {{host, model, effort}} entries."
            )
    if not isinstance(hosts, dict) or not all(
        isinstance(t, list) and t and all(isinstance(a, str) for a in t) for t in hosts.values()
    ):
        raise MachineConfigError(f"{path}: hosts must map host names to command lists.")
    return runners, {**runner.HOSTS, **hosts}


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

PLAYBOOK_SETUP = {
    "claude": """
Install the SecondChair playbooks (a Claude Code plugin) with:

  claude plugin marketplace add {playbooks}
  claude plugin install secondchair@secondchair
""",
    "codex": """
Install the SecondChair playbooks (a Codex skill bundle) with:

  mkdir -p ~/.codex/skills
{links}""",
}


def host_setup(host: str) -> str:
    """The host configuration for the Core and its playbooks on this machine; never written
    anywhere (PKG-19)."""
    links = "".join(
        f"  ln -sfn {skill} ~/.codex/skills/{skill.name}\n"
        for skill in sorted(runner.SKILLS.iterdir())
    )
    return HOST_SETUP[host].format(
        url=f"http://{LOOPBACK}:{configured_port()}{MCP_PATH}"
    ) + PLAYBOOK_SETUP[host].format(playbooks=runner.PLAYBOOKS, links=links)


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


def _input(value: str) -> tuple[str, str]:
    """A job input `name=value`; a value naming an existing file becomes its absolute path, so
    the agent finds it wherever it runs."""
    name, sep, text = value.partition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"{value!r}: expected name=value")
    path = Path(text).expanduser()
    return name, str(path.resolve()) if path.exists() else text


def _describe(job: dict) -> str:
    lines = [
        f"Job {job['id']}  {job['status']}  {job['playbook']}  "
        f"({job['responsibility']}, {job['moment']}; tier {job['tier']})"
    ]
    if job["attempts"]:
        last = job["attempts"][-1]
        config = ", ".join(last["runner_configuration"][k] for k in jobs.CONFIG_KEYS)
        error = f": {last['error']}" if last["error"] else ""
        lines.append(f"  last attempt {last['outcome']} ({config}){error}")
    return "\n".join(lines)


def _jobs_command(args: argparse.Namespace) -> int:
    ws = workspace.load(args.workspace)
    if args.job_command == "queue":
        job = runner.queue(ws, args.playbook, dict(args.input), args.tier)
        print(f"Queued job {job['id']} ({job['playbook']}, tier {job['tier']}).")
        return 0
    if args.job_command is None:
        pending = jobs.pending(ws)
        for job in pending:
            print(_describe(job))
        print(
            "Start a job from your agent host session: ask it to start SecondChair job <id>; "
            "the tier is a hint."
            if pending
            else "No pending job."
        )
        return 0
    runners, hosts = configured_runners()
    queued = [j for j in jobs.pending(ws) if j["status"] == "queued"]
    status = 0
    for job in [jobs.read(ws, args.job)] if args.job else queued:
        try:
            done = runner.run(ws, job["id"], runners, hosts)
        except (runner.RunnerError, DelegationError) as e:
            print(f"secondchair: {e}", file=sys.stderr)
            status = 1
            continue
        if done is None:
            print(
                f"Job {job['id']}: no runner configured for tier {job['tier']}; "
                "it waits for you to start it from your agent host session."
            )
        else:
            print(_describe(done))
    return status


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
    jobs_cmd = commands.add_parser(
        "jobs", parents=[in_workspace], help="list pending jobs, queue one or run them"
    )
    # `-w` after the job command too, without its default hiding one given before it.
    sub_workspace = argparse.ArgumentParser(add_help=False)
    sub_workspace.add_argument("-w", "--workspace", type=Path, default=argparse.SUPPRESS)
    jobs_sub = jobs_cmd.add_subparsers(dest="job_command")
    queue_cmd = jobs_sub.add_parser("queue", parents=[sub_workspace], help="queue a job")
    queue_cmd.add_argument("playbook")
    queue_cmd.add_argument(
        "--input", type=_input, action="append", default=[], help="a job input, name=value"
    )
    queue_cmd.add_argument("--tier", choices=jobs.TIERS, help="override the playbook's tier")
    run_cmd = jobs_sub.add_parser(
        "run", parents=[sub_workspace], help="start queued jobs with the configured runner"
    )
    run_cmd.add_argument("job", type=int, nargs="?", help="one job (default: every queued job)")
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
        elif args.command == "jobs":
            return _jobs_command(args)
        else:
            print(_gm_command(args))
    except (
        WorkspaceError,
        MachineConfigError,
        RegistrationError,
        DelegationError,
        CanonError,
        runner.RunnerError,
        OSError,
    ) as e:
        print(f"secondchair: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
