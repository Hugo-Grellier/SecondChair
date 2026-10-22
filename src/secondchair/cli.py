"""The `secondchair` command line."""

import argparse
import contextlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from secondchair import review, runner, transcribe
from secondchair.core import (
    admission,
    calls,
    campaign_skill,
    canon,
    capture,
    delegation,
    index,
    jobs,
    journal,
    library,
    machine,
    mystery,
    notes,
    rules,
    setup_check,
    signals,
    snapshot,
    workspace,
    world,
)
from secondchair.core.calendar import CalendarError
from secondchair.core.delegation import DelegationError
from secondchair.core.index import CanonError
from secondchair.core.machine import MachineConfigError
from secondchair.core.server import GM_PATH, LOOPBACK, MCP_PATH, SERVE_FILE, serve
from secondchair.core.tools import RESPONSIBILITIES, RegistrationError, load_tools
from secondchair.core.workspace import STATE_DIR, WorkspaceError

DEFAULT_PORT = 7240


def configured_port() -> int:
    path, config = machine.config()
    port = config.get("port", DEFAULT_PORT)
    if type(port) is not int or not 0 <= port <= 65535:
        raise MachineConfigError(f"{path}: port must be an integer between 0 and 65535.")
    return port


def configured_runners() -> tuple[dict[str, list[dict[str, str]]], dict[str, list]]:
    """The runner configuration, keyed by tier only (ARC-26), and the agent hosts' command
    templates: the built-in ones, overridden or extended by the machine configuration's."""
    path, config = machine.config()
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


def configured_transcription() -> list[str] | None:
    """The transcription engine's command template, or None for WhisperX's."""
    path, config = machine.config()
    template = config.get("transcription")
    if template is not None and not (
        isinstance(template, list) and template and all(isinstance(a, str) for a in template)
    ):
        raise MachineConfigError(f"{path}: transcription must be a command list.")
    return template


def _track(value: str) -> tuple[str, Path]:
    """A speaker track `discord-user=audio-file`."""
    speaker, sep, path = value.partition("=")
    if not sep or not speaker or not path:
        raise argparse.ArgumentTypeError(f"{value!r}: expected discord-user=audio-file")
    return speaker, Path(path)


def _transcribe_command(args: argparse.Namespace) -> None:
    ws = workspace.load(args.workspace)
    if args.source:
        if args.tracks:
            raise transcribe.TranscriptionError("Give either speaker tracks or --from, not both.")
        source_id = transcribe.register(ws, args.session, args.source)
        print(f"Referenced transcript {source_id} for session {args.session}.")
        out = args.source.expanduser().resolve()
    else:
        tracks = dict(args.tracks)
        if len(tracks) != len(args.tracks):
            raise transcribe.TranscriptionError("Give one track per speaker.")
        template = configured_transcription()
        out = transcribe.transcribe(ws, args.session, tracks, args.out, args.language, template)
        print(f"Transcript of session {args.session}: {out}")
    job, new = capture.attach_transcript(ws, args.session, out)
    n, done = job["id"], "queued on it" if new else "given it"
    print(
        f'Job {n} "wrap a session" {done}: run it (secondchair jobs run, or ask your agent '
        f"to start job {n}), then secondchair wrap {args.session}."
    )


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
Install the SecondChair playbooks (one Claude Code plugin per block) with:

{plugins}""",
    "codex": """
Install the SecondChair playbooks (a Codex skill bundle) with:

  mkdir -p ~/.codex/skills
{links}""",
}


def host_setup(host: str) -> str:
    """The host configuration for the Core and its playbooks on this machine; never written
    anywhere (PKG-19)."""
    links = "".join(
        f"  ln -sfn {skill} ~/.codex/skills/{skill.name}\n" for skill in runner.skills()
    )
    plugins = ""
    for playbooks in runner.playbook_dirs():
        name = json.loads((playbooks / ".claude-plugin/plugin.json").read_text())["name"]
        plugins += f"  claude plugin marketplace add {playbooks}\n"
        plugins += f"  claude plugin install {name}@{name}\n"
    return HOST_SETUP[host].format(
        url=f"http://{LOOPBACK}:{configured_port()}{MCP_PATH}"
    ) + PLAYBOOK_SETUP[host].format(plugins=plugins, links=links)


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


def _consent_to_destructive(root: Path, versions: list[int]) -> bool:
    """The GM types the workspace name at an interactive terminal (ADR 0018, ADR 0003)."""
    if not interactive():
        raise WorkspaceError(
            f"The migration(s) from schema version {versions} rewrite or remove authoritative "
            "content: run `secondchair upgrade` from an interactive terminal."
        )
    typed = input(
        f"Migration(s) from schema version {versions} rewrite or remove authoritative content. "
        f"Type the workspace name ({root.name}) to proceed: "
    )
    return typed.strip() == root.name


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
    if args.command == "session":
        if not auth:  # DEL-03a
            raise DelegationError("Starting or ending a session needs an interactive terminal.")
        if args.action == "start":
            unwrapped = _unwrapped(ws)  # read before: the new session is not played yet
            started = f"Session {delegation.start_session(ws)} started: moment live-session."
            if unwrapped:
                started += (
                    f" Warning: session {unwrapped} is not wrapped yet; what was played there "
                    "is not in canon (secondchair status)."
                )
            return _session_started(ws, started)
        notes = str(Path(args.notes).expanduser().resolve()) if args.notes else None
        live = delegation.end_session(ws, notes)
        return (
            f"Session {live} ended: moment between-sessions. "
            'Job "wrap a session" queued (secondchair jobs).'
        )
    if args.command == "date":
        if args.date is None:
            return capture.time(ws)["current_date"] or "The campaign has no current date yet."
        if not auth:  # the current date moves only through the wrap or a GM gesture (CAL-14)
            raise DelegationError("Setting the current date needs an interactive terminal.")
        return f"Current date: {capture.set_current_date(ws, args.date)}."
    if args.command == "override":
        o = (args.entity, args.responsibility)
        if args.override_command == "add":
            delegation.add_override(ws, *o, args.level, args.moment, "cli", auth)
            where = args.moment or "every moment"
            return f"{args.responsibility} for {args.entity} lowered to {args.level} ({where})."
        delegation.remove_override(ws, *o, args.moment, "cli", auth)
        return f"Override removed: {args.responsibility} for {args.entity}."
    if args.command == "hold":
        lift = args.hold_command == "lift"
        cell = (args.responsibility, args.moment)
        delegation.set_hold(ws, *cell, not lift, "cli", auth)
        if lift:
            return (
                f"Hold lifted on {args.responsibility} in {args.moment}: its irreversible "
                "actions now run at the cell's level, at once and with no undo."
            )
        return f"Hold restored on {args.responsibility} in {args.moment}."
    if args.command == "house-rule":
        if args.rule_command == "mark":
            rule = rules.mark_intended(ws, args.call, args.name, "cli", auth)
            return (
                f"House rule {rule['name']!r} recorded: {rule['check']} checks are silenced "
                "until you remove it."
            )
        if args.rule_command == "remove":
            rule = rules.remove_house_rule(ws, args.name, "cli", auth)
            return f"House rule {rule['name']!r} removed: {rule['check']} checks run again."
        return (
            "\n".join(
                f"{r['name']}  silences {r['check']} checks (discrepancy {r['call']}, {r['at']})"
                for r in rules.house_rules(ws)
            )
            or "No house rule."
        )
    if args.command == "break":
        pile = calls.take_break(ws)
        return "\n".join(_describe_call(c) for c in pile) or "Nothing held for the break."
    if args.command == "confirm":
        if not auth:  # DEL-29
            raise DelegationError("Confirming a GM decision needs an interactive terminal.")
        done = [f"{i} (entry {canon.confirm(ws, i, 'cli', auth)['id']})" for i in args.id]
        return f"Confirmed as GM decisions: {', '.join(done)}."
    if args.command == "wrap":
        return _describe_wrap(ws, capture.wrap(ws, args.session, auth, args.start, args.end))
    if args.command == "promote":
        delegation.promote(ws, args.entry, "cli", auth)
        return f"Promoted hand edit {args.entry} to a GM decision."
    if args.command == "approve":
        for entry in args.entry:  # one at a time, in order: the first refusal stops the rest
            if _in_vtt(ws, entry):
                _relay(ws, {"gesture": "approve", "entry": entry, "authenticated": auth})
            else:
                delegation.approve(ws, entry, "cli", auth)
        return f"Approved and applied {_entries(args.entry)}."
    if args.command == "reject":
        delegation.reject(ws, args.entry, args.reason, "cli", auth)
        return f"Rejected entry {args.entry} ({args.reason})."
    if _in_vtt(ws, args.entry):
        gesture = {"gesture": "undo", "entry": args.entry, "reason": args.reason}
        _relay(ws, {**gesture, "authenticated": auth})
    else:
        delegation.undo(ws, args.entry, args.reason, "cli", auth)
    return f"Undid entry {args.entry} ({args.reason})."


def _entries(ids: list[int]) -> str:
    return f"entry {ids[0]}" if len(ids) == 1 else f"entries {', '.join(map(str, ids))}"


def _unwrapped(ws: workspace.Workspace) -> int | None:
    """The last played session when it is not wrapped yet, else None."""
    last = delegation.last_session(ws)
    if last and not capture.time(ws)["sessions"].get(last, {}).get("wrapped"):
        return last
    return None


def status(ws: workspace.Workspace) -> str:
    """Where the campaign stands and what the GM does next, in a few lines."""
    moment, _ = delegation.current_moment(ws)
    live = delegation.current_session(ws)
    entries, _ = delegation.read_log(ws)
    held = [e["id"] for e in entries if e.get("status") == "pending"]
    open_calls = [c for c in calls.read_calls(ws) if c.get("status") == "open"]
    pending_jobs = jobs.pending(ws)
    entities, facts, events = index.counts(ws)
    played = delegation.last_session(ws)
    lines = [
        f"Moment: {moment}" + (f" (session {live} is live)" if live else ""),
        f"Campaign date: {capture.time(ws)['current_date'] or 'not set'}",
        f"Canon: {entities} entities, {facts} facts, {events} events",
        f"Sessions played: {played}",
    ]
    nexts = []
    if not capture.time(ws)["current_date"] and not live:
        nexts.append("secondchair date <date>  (set the campaign's current date before play)")
    if (unwrapped := _unwrapped(ws)) and not live:
        lines.append(f"Session {unwrapped} is not wrapped: what was played is not in canon yet.")
        nexts.append(f"secondchair wrap {unwrapped}  (after its wrap job)")
    for job in pending_jobs:
        lines.append(f"Job {job['id']} {job['status']}: {job['playbook']} (tier {job['tier']})")
        if job["status"] == "queued":
            nexts.append(
                f'ask your agent: "start SecondChair job {job["id"]}", or secondchair jobs run '
                f"{job['id']} with a runner"
            )
    if held:
        lines.append(f"Awaiting your approval: {_entries(held)}")
        nexts.append(f"secondchair approve {' '.join(map(str, held))}  (or reject <entry>)")
    if open_calls:
        lines.append(f"Open calls on you: {len(open_calls)} (secondchair break shows them)")
    handoff = ws.root / "prep" / f"session-{played + 1}" / "handoff.md"
    if not live and not unwrapped:  # prepare from what was played, once it is canon
        if handoff.is_file():
            lines.append(f"Next session's handoff: {handoff.relative_to(ws.root)}")
        else:
            nexts.append(
                f'ask your agent: "prepare session {played + 1}" (prepare-a-session playbook)'
            )
    lines += [f"Next: {n}" for n in nexts] or ["Next: nothing waits on you."]
    return "\n".join(lines)


def _describe_call(call: dict) -> str:
    what = (
        f"entry {call['entry']}"
        if call["entry"] is not None
        else call["message"] or f"job {call['job']}"
    )
    state = "safe default applied" if call["status"] == "defaulted" else "to answer"
    return f"Call {call['id']}  {call['kind']}  {call['responsibility']}  {state}: {what}"


def _describe_wrap(ws: workspace.Workspace, summary: dict) -> str:
    """The wrap's grouped round (CAP-13): questions first, contradictions leading, then what was
    applied, each undoable by its entries."""
    lines = []

    def rank(call: dict) -> int:  # contradictions, blocking questions, then proposals
        message = call["message"] or ""
        return 0 if message.startswith("contradiction") else 1 if message else 2

    questions = sorted(summary["questions"], key=rank)
    for call in questions:
        what = call["message"] or "a fact held for your approval"
        lines.append(f"Question (entry {call['entry']}): {what}")
    if questions:
        lines.append(
            "Answer each: `secondchair approve <entry>` admits it as written, `secondchair "
            "reject <entry> --reason contradiction` drops it. Then run the wrap again."
        )
    for c in summary["candidates"]:
        if c["status"] == "held":
            continue
        flag = f" [flagged: {c['reason']}]" if c["classification"] != "certain" else ""
        error = f": {c['error']}" if c["error"] else ""
        entries = f" (entries {', '.join(map(str, c['entries']))})" if c["entries"] else ""
        lines.append(f"{c['status']}  {c['statement']}{flag}{error}{entries}")
    if summary["candidates"] and not questions:
        lines.append("Undo any applied item with `secondchair log undo <entry> --reason <reason>`.")
    if summary["settled"]:
        settled, job = summary["settled"], summary["job"]
        lines.append(
            f"Session interval {settled['start']} to {settled['end']}; current date "
            f"{settled['end']}. World-turn job {job['id']} queued (secondchair jobs)."
        )
        if summary["spotlight"]:
            names = {e["id"]: e["names"][0] for e in index.search_entities(ws)}
            counts = ", ".join(sorted(f"{names[i]} {n}" for i, n in summary["spotlight"].items()))
            lines.append(f"Spotlight (played facts citing each PC): {counts}.")
    return "\n".join(lines)


def check(ws: workspace.Workspace) -> int:
    """Rebuild the derived index and validate the workspace from the directory alone, with no
    Foundry or Source (CAN-10, PKG-15); 1 if a file is invalid. Lists the hand edits the
    rebuild logged that await the GM (CAN-11)."""
    errors = dict.fromkeys(index.rebuild(ws) + delegation.check(ws) + transcribe.check(ws))
    for error in errors:
        print(f"secondchair: {error}", file=sys.stderr)
    entities, facts, events = index.counts(ws)
    print(f"Indexed {entities} entities, {facts} facts, {events} events from {ws.root}.")
    latest = {e["target"]: e for e in delegation.read_log(ws)[0] if e.get("kind") == "hand_edit"}
    for entry in latest.values():
        if entry["rank"] == "agent_proposal" and entry["after"] is not None:
            print(
                f"Hand edit of {entry['target']} ranks agent_proposal; "
                f"`secondchair promote {entry['id']}` makes it a GM decision."
            )
    return 1 if errors else 0


def doctor(ws: workspace.Workspace) -> int:
    """Re-resolve the evidence of played and cited canon (ADR 0015); 1 if some no longer
    resolves. Ranks stand: the GM corrects the record or promotes it."""
    found = admission.unresolved(ws)
    for problem in found:
        print(f"secondchair: {problem}", file=sys.stderr)
    print(f"{len(found)} played or cited records whose evidence no longer resolves.")
    return 1 if found else 0


def check_setup(root: Path) -> int:
    """Checks of this machine, one fix per failure; 1 if any FAILs. Writes no host or machine
    file; the status block may refresh the derived index."""
    plugins = [
        json.loads((d / ".claude-plugin/plugin.json").read_text())["name"]
        for d in runner.playbook_dirs()
    ]
    port, runners, transcription, error = None, {}, None, False
    try:
        port, runners = configured_port(), configured_runners()[0]
        transcription = configured_transcription()
    except MachineConfigError:  # its text may quote the file: the line names the file instead
        error = True
    results = setup_check.run(
        root,
        port=port,
        runners=runners,
        transcription=transcription,
        plugins=plugins,
        skills=[s.name for s in runner.skills()],
        config_error=error,
    )
    for level, what, fix in results:
        print(f"{level:<4} {what}" + (f"\n     Fix: {fix}" if fix else ""))
    with contextlib.suppress(WorkspaceError):  # an invalid workspace is the first check's FAIL
        print("\n" + status(workspace.load(root)))
    return 1 if any(level == setup_check.FAIL for level, _, _ in results) else 0


def _runner_config(value: str) -> dict[str, str]:
    """A runner configuration `host/model/effort`."""
    parts = value.split("/")
    if len(parts) != 3 or not all(parts):
        raise argparse.ArgumentTypeError(f"{value!r}: expected host/model/effort")
    return dict(zip(jobs.CONFIG_KEYS, parts, strict=True))


def _bench_command(args: argparse.Namespace) -> int:
    from secondchair.bench import harness, recall, report, s2, scale  # not the Core's

    if args.bench_command in ("scale", "recall"):
        sizes = args.sizes.split(",")
        if args.bench_command == "scale":
            print(scale.run(sizes, args.seed))
            return 0
        passed, markdown = recall.run(sizes, args.seed)
        print(markdown)
        return 0 if passed else 1
    try:
        if args.bench_command == "s0":
            hosts = configured_runners()[1]
            found = harness.run_s0(args.sample, args.out, args.runner, hosts, args.runs)
        elif args.bench_command == "s2":
            hosts = configured_runners()[1]
            found = s2.run_s2(args.scenario, args.out, args.runner, hosts, args.runs)
        else:
            found = report.recompute(args.out)
    except s2.BenchError as e:
        print(f"secondchair: {e}", file=sys.stderr)
        return 1
    print(
        f"{found['scenario']} {'passed' if found['passed'] else 'FAILED'}; "
        f"report: {args.out / 'report.md'}"
    )
    return 0 if found["passed"] else 1


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
        job = runner.queue(ws, args.playbook, dict(args.input), args.tier, args.entity)
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


def _describe_occurrence(o: dict) -> str:
    if o["kind"] == "ticks":  # LW-15: one line, one key per tick
        return f"{len(o['keys'])} ticks of {o['entity']} ({', '.join(o['dates'])})"
    status = f"  {o['status']}" if "status" in o else ""
    return f"{o['date']}  {o['key']}  {o['class']}{status}"


def _prep_command(args: argparse.Namespace) -> int:
    """Lint a prep note's index block, or guard a whole note for the party; 1 on a problem."""
    ws = workspace.load(args.workspace)
    tool = {t.name: t for t in load_tools(ws)}[
        "check_prep" if args.prep_command == "check" else "check_prep_guide"
    ]
    try:
        result = tool.fn(args.path)
    except CanonError as e:  # the guard's refusal, or a note that is not there
        print(f"secondchair: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


def _mystery_command(args: argparse.Namespace) -> str:
    """Check a mystery draft note against canon (#177); nothing is written."""
    ws = workspace.load(args.workspace)
    [check] = [t for t in mystery.tools(ws) if t.name == "check_draft_mystery"]
    found = check.fn(args.slug, args.lose)
    lines = [f"problem: {p}" for p in found["problems"]]
    lines += [f"{w['code']}: {w['message']}" for w in found["warnings"]]
    return "\n".join(lines) or "No problem, no warning."


def _world_command(args: argparse.Namespace) -> str:
    """The living world's GM gestures (LW-04, LW-05, LW-09, LW-12, LW-14, LW-16, LW-18)."""
    ws = workspace.load(args.workspace)
    auth = interactive()
    what = args.world_command
    if what in ("turn", "forecast"):
        shown = (
            world.present(world.world_turn(ws, args.date, args.since))
            if what == "turn"
            else world.forecast(ws, args.date, args.since)
        )
        lines = [_describe_occurrence(o) for o in shown]
        return "\n".join(lines) or "Nothing due."
    if what == "decide":
        record = world.decide(ws, args.key, args.answer, auth, args.date)
        return f"{args.key}: {record['status']}."
    if what == "undo":
        keys = world.undo(ws, args.key, args.reason, "cli", auth)
        return f"Undone and queued again: {', '.join(keys)}."
    record = world.set_active(ws, args.front, what == "resume", args.date, auth)
    return f"{record['key']}: applied."


def _in_vtt(ws: workspace.Workspace, entry_id: int) -> bool:
    path = ws.root / delegation.LOG_DIR / f"{entry_id:06d}.yaml"
    return path.is_file() and "op" in delegation.read_entry(ws, entry_id)


def _session_started(ws: workspace.Workspace, message: str) -> str:
    """`message`, then what the VTT did for the new live session (the current date pushed into
    its clock, CAL-11), when a Core serves the campaign: only that process holds the GM client."""
    if not (ws.root / STATE_DIR / SERVE_FILE).is_file():
        return message
    try:
        done = _relay(ws, {"gesture": "session_start"}, "No Core serves the campaign.")
    except DelegationError as e:
        return f"{message}\nThe VTT was not told the session started: {e}"
    return f"{message}\n{done['message']}" if done.get("message") else message


def _relay(
    ws: workspace.Workspace,
    gesture: dict,
    not_served_message: str = (
        "This entry is a VTT action: `secondchair serve` the campaign, with its world open as GM, "
        "then try again."
    ),
) -> dict:
    """Have the Core serving the campaign take a GM gesture on a VTT action: only that process
    holds the GM client (PKG-10)."""
    not_served = DelegationError(not_served_message)
    token = machine.foundry_token()
    try:
        port = json.loads((ws.root / STATE_DIR / SERVE_FILE).read_text())["port"]
    except (OSError, ValueError, KeyError) as e:
        raise not_served from e
    request = urllib.request.Request(
        f"http://{LOOPBACK}:{port}{GM_PATH}",
        data=json.dumps({**gesture, "workspace": str(ws.root.resolve())}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read())["error"]
        except ValueError, KeyError, TypeError:
            message = str(e)
        raise DelegationError(message) from e
    except TimeoutError as e:
        raise DelegationError(
            "The Core serving the campaign did not answer in time; check the action log before "
            "trying again."
        ) from e
    except OSError as e:  # connection refused: serve is not running
        raise not_served from e


def _sources_command(args: argparse.Namespace) -> None:
    ws = workspace.load(args.workspace)
    action = args.source_command
    if action == "add":
        metadata = {k: getattr(args, k) for k in library.METADATA}
        print("Registered: " + ", ".join(library.register(ws, args.path, metadata)))
    elif action == "permit":
        if args.index is None and args.model is None:
            raise WorkspaceError("Give --index allow|deny or --model allow|deny.")
        library.permit(
            ws,
            args.id,
            None if args.index is None else args.index == "allow",
            None if args.model is None else args.model == "allow",
            interactive(),
        )
        print(f"Permissions updated for {args.id}.")
    elif action == "index":
        diff = library.build_index(ws, args.id, args.replace_changed, interactive())
        print(f"Index ready for {args.id}.")
        if diff:
            print(json.dumps(diff, ensure_ascii=False, indent=2))
    elif action == "audit":
        print(json.dumps(library.audit(ws, args.id), ensure_ascii=False, indent=2))
    elif action == "list":
        print(json.dumps(library.listing(ws), ensure_ascii=False, indent=2))
    else:
        if args.local and not interactive():
            raise WorkspaceError("Local-only excerpts need an interactive GM terminal.")
        print(
            json.dumps(
                library.search(
                    ws,
                    args.query,
                    local=args.local,
                    limit=args.limit,
                    include_closed=args.include_closed,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )


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
    commands.add_parser(
        "campaign-skill",
        parents=[in_workspace],
        help="install or update the managed campaign skill; refuse local conflicts",
    )
    source_cmd = commands.add_parser("sources", help="registered campaign reference library")
    source_sub = source_cmd.add_subparsers(dest="source_command", required=True)
    add_cmd = source_sub.add_parser("add", parents=[in_workspace])
    add_cmd.add_argument("path", type=Path)
    add_cmd.add_argument("--title", help="the book's title (default: the PDF's own)")
    add_cmd.add_argument("--edition", choices=library.EDITIONS)
    add_cmd.add_argument("--version", help="printing or errata, as the GM names it")
    add_cmd.add_argument("--language", help="the source's language, e.g. en or fr")
    add_cmd.add_argument("--product-id", dest="product_id", help="the publisher's product id")
    source_sub.add_parser("list", parents=[in_workspace])
    permit_cmd = source_sub.add_parser("permit", parents=[in_workspace])
    permit_cmd.add_argument("id")
    permit_cmd.add_argument("--index", choices=("allow", "deny"))
    permit_cmd.add_argument("--model", choices=("allow", "deny"))
    index_cmd = source_sub.add_parser("index", parents=[in_workspace])
    index_cmd.add_argument("id")
    index_cmd.add_argument("--replace-changed", action="store_true")
    audit_cmd = source_sub.add_parser(
        "audit", parents=[in_workspace], help="list stat blocks and tables that could not be read"
    )
    audit_cmd.add_argument("id")
    search_cmd = source_sub.add_parser("search", parents=[in_workspace])
    search_cmd.add_argument("query")
    search_cmd.add_argument("--limit", type=int, default=10)
    search_cmd.add_argument("--local", action="store_true", help="GM terminal only; local excerpts")
    search_cmd.add_argument(
        "--include-closed", action="store_true", help="also search rejected and superseded notes"
    )
    notes_cmd = commands.add_parser("notes", help="design notes under notes/")
    notes_sub = notes_cmd.add_subparsers(dest="notes_command", required=True)
    notes_sub.add_parser("check", parents=[in_workspace], help="validate design note front matter")
    reason = argparse.ArgumentParser(add_help=False)
    reason.add_argument("--reason", required=True, choices=delegation.REASONS)
    moment_cmd = commands.add_parser(
        "moment", parents=[in_workspace], help="change the current moment (interactive only)"
    )
    moment_cmd.add_argument("moment", choices=delegation.MOMENTS)
    session_cmd = commands.add_parser(
        "session", parents=[in_workspace], help="start or end the live session (interactive only)"
    )
    session_cmd.add_argument("action", choices=("start", "end"))
    session_cmd.add_argument(
        "--notes", help="at end: your notes for the session, the wrap job's Source"
    )
    commands.add_parser(
        "break", parents=[in_workspace], help="signal a break and show the calls held for it"
    )
    commands.add_parser(
        "date",
        parents=[in_workspace],
        help="show the campaign's current date, or set it (interactive only)",
    ).add_argument("date", nargs="?", help="a full date of the campaign calendar, YYYY-MM-DD")
    override_cmd = commands.add_parser(
        "override", help="lower the delegation level for one acting entity"
    )
    override_sub = override_cmd.add_subparsers(dest="override_command", required=True)
    for name, help_text in (
        ("add", "add an entity override; it takes effect at once"),
        ("remove", "remove an entity override (interactive only)"),
    ):
        sub = override_sub.add_parser(name, parents=[in_workspace], help=help_text)
        sub.add_argument("entity", help="the acting entity's id, e-…")
        sub.add_argument("responsibility", help=", ".join(delegation.OVERRIDABLE))
        if name == "add":
            sub.add_argument("level", choices=delegation.LEVELS)
        sub.add_argument("--moment", choices=delegation.MOMENTS, help="default: every moment")
    hold_cmd = commands.add_parser(
        "hold", help="the irreversible hold of one delegation-table cell"
    )
    hold_sub = hold_cmd.add_subparsers(dest="hold_command", required=True)
    for name, help_text in (
        ("lift", "let the cell's irreversible actions run at its level (interactive only)"),
        ("restore", "hold the cell's irreversible actions at propose again"),
    ):
        sub = hold_sub.add_parser(name, parents=[in_workspace], help=help_text)
        sub.add_argument("responsibility", choices=RESPONSIBILITIES)
        sub.add_argument("moment", choices=delegation.MOMENTS)
    rule_cmd = commands.add_parser(
        "house-rule", help="the campaign's house rules, which silence a kind of rules check"
    )
    rule_sub = rule_cmd.add_subparsers(dest="rule_command", required=True)
    rule_sub.add_parser("list", parents=[in_workspace], help="list the house rules")
    mark_cmd = rule_sub.add_parser(
        "mark",
        parents=[in_workspace],
        help="mark a discrepancy as intended, recording a house rule (interactive only)",
    )
    mark_cmd.add_argument("call", type=int, help="the discrepancy's call id")
    mark_cmd.add_argument("name", help="the house rule's name")
    rule_sub.add_parser(
        "remove", parents=[in_workspace], help="remove a house rule: its checks run again"
    ).add_argument("name")
    commands.add_parser(
        "approve", parents=[in_workspace], help="approve pending actions, in the order given"
    ).add_argument("entry", type=int, nargs="+")
    commands.add_parser(
        "reject", parents=[in_workspace, reason], help="reject a pending action"
    ).add_argument("entry", type=int)
    commands.add_parser(
        "confirm",
        parents=[in_workspace],
        help="confirm facts or events relayed from your words as GM decisions (interactive only)",
    ).add_argument("id", nargs="+", help="the fact or event ids, f-… or v-…")
    wrap_cmd = commands.add_parser(
        "wrap",
        parents=[in_workspace],
        help="the wrap's grouped round, then settle the session and advance the date "
        "(interactive only)",
    )
    wrap_cmd.add_argument("session", type=int)
    wrap_cmd.add_argument("--start", help="the session's first campaign date, over the notes'")
    wrap_cmd.add_argument("--end", help="the session's last campaign date, over the notes'")
    commands.add_parser(
        "status", parents=[in_workspace], help="where the campaign stands and what to do next"
    )
    commands.add_parser(
        "check", parents=[in_workspace], help="rebuild the derived index and report invalid files"
    )
    backup_cmd = commands.add_parser(
        "backup", help="archive a workspace (not .secondchair/) with a manifest of hashes"
    )
    backup_cmd.add_argument("workspace", type=Path)
    backup_cmd.add_argument("archive", type=Path, help="a new file, outside the workspace")
    backup_cmd.add_argument(
        "--foundry-backup-at", help="when you backed up the paired Foundry world, ISO 8601"
    )
    backup_cmd.add_argument(
        "--with-library-cache", action="store_true", help="also copy the machine-wide library index"
    )
    restore_cmd = commands.add_parser(
        "restore", help="restore a backup into an empty or new directory, verify it and check it"
    )
    restore_cmd.add_argument("archive", type=Path)
    restore_cmd.add_argument("directory", type=Path)
    commands.add_parser(
        "recover",
        parents=[in_workspace],
        help="finish an interrupted world-turn once its stopped journal's file is resolved",
    )
    commands.add_parser(
        "doctor",
        parents=[in_workspace],
        help="re-check the evidence of played and cited facts and report what no longer "
        "resolves (changes nothing)",
    )
    commands.add_parser(
        "check-setup",
        parents=[in_workspace],
        help="check this machine is ready, with one fix per problem (changes nothing)",
    )
    commands.add_parser(
        "promote",
        parents=[in_workspace],
        help="make a logged hand edit a GM decision (interactive only)",
    ).add_argument("entry", type=int)
    upgrade_cmd = commands.add_parser(
        "upgrade", parents=[in_workspace], help="migrate the workspace to the current schema"
    )
    upgrade_cmd.add_argument(
        "--preview", action="store_true", help="show the diff of the migration; change nothing"
    )
    upgrade_cmd.add_argument(
        "--no-snapshot", action="store_true", help="skip the pre-upgrade backup archive"
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
    queue_cmd.add_argument(
        "--entity",
        action="append",
        help="an entity id the job is about; its vocabulary is then theirs (default: all)",
    )
    run_cmd = jobs_sub.add_parser(
        "run", parents=[sub_workspace], help="start queued jobs with the configured runner"
    )
    run_cmd.add_argument("job", type=int, nargs="?", help="one job (default: every queued job)")
    transcribe_cmd = commands.add_parser(
        "transcribe",
        parents=[in_workspace],
        help="transcribe a played session's per-speaker tracks, or reference an attributed "
        "transcript; both stay outside the workspace",
    )
    transcribe_cmd.add_argument("--session", type=int, required=True, help="the session id")
    transcribe_cmd.add_argument(
        "tracks", type=_track, nargs="*", help="one per speaker: discord-user=audio-file"
    )
    transcribe_cmd.add_argument(
        "--from",
        dest="source",
        type=Path,
        help="a transcript any engine produced in the transcript format, instead of tracks",
    )
    transcribe_cmd.add_argument(
        "--out", type=Path, help="the transcript (default: session-<id>.jsonl by the first track)"
    )
    transcribe_cmd.add_argument(
        "--language", help="the language spoken (default: the campaign language)"
    )
    prep_cmd = commands.add_parser("prep", help="check a prep note; writes nothing")
    prep_sub = prep_cmd.add_subparsers(dest="prep_command", required=True)
    for name, help_text in (
        ("check", "lint the note's index block: UUIDs, encounter XP, treasure, clues, scenes"),
        ("guard", "guard the whole note for the party, such as an adventure's players' guide"),
    ):
        cmd = prep_sub.add_parser(name, parents=[in_workspace], help=help_text)
        cmd.add_argument("path", help="relative to prep/: adventure-x/players-guide.md")
    mystery_cmd = commands.add_parser("mystery", help="mystery drafts")
    mystery_sub = mystery_cmd.add_subparsers(dest="mystery_command", required=True)
    draft_cmd = mystery_sub.add_parser(
        "check-draft",
        parents=[in_workspace],
        help="check notes/mysteries/<slug>.md as record_mystery would; writes nothing",
    )
    draft_cmd.add_argument("slug")
    draft_cmd.add_argument("--lose", action="append", default=[], help="simulate losing a clue id")
    signals_cmd = commands.add_parser(
        "signals", parents=[in_workspace], help="a session's deterministic signals; writes nothing"
    )
    signals_cmd.add_argument("session", type=int)
    world_cmd = commands.add_parser("world", help="advance, forecast and steer the living world")
    world_sub = world_cmd.add_subparsers(dest="world_command", required=True)
    for name, help_text in (
        ("turn", "run the world-turn up to a campaign date (never in a live session)"),
        ("forecast", "show what world-turns would do up to a campaign date; writes nothing"),
    ):
        cmd = world_sub.add_parser(name, parents=[in_workspace], help=help_text)
        cmd.add_argument("date")
        cmd.add_argument("--since", help="the date the world starts from, on the first turn")
    decide_cmd = world_sub.add_parser(
        "decide", parents=[in_workspace], help="answer a queued occurrence"
    )
    decide_cmd.add_argument("key")
    decide_cmd.add_argument("answer", choices=("accept", "reject", "reschedule"))
    decide_cmd.add_argument("--date", help="the new date, to reschedule")
    world_undo = world_sub.add_parser(
        "undo",
        parents=[in_workspace, reason],
        help="undo an applied occurrence and its cascade; their keys return to the queue",
    )
    world_undo.add_argument("key")
    for name in ("pause", "resume"):
        cmd = world_sub.add_parser(name, parents=[in_workspace], help=f"{name} a front")
        cmd.add_argument("front")
        cmd.add_argument("date")
    bench_cmd = commands.add_parser("bench", help="the test bench")
    bench_sub = bench_cmd.add_subparsers(dest="bench_command", required=True)
    s0_cmd = bench_sub.add_parser(
        "s0",
        help="run scenario S0 at the delegated table and at the baseline, then report; exits 1 "
        "when an invariant fails",
    )
    s0_cmd.add_argument("out", type=Path, help="a new directory for the runs and the report")
    s0_cmd.add_argument(
        "--sample", type=Path, default=Path("sample-campaign"), help="the sample campaign"
    )
    s0_cmd.add_argument(
        "--runner",
        type=_runner_config,
        required=True,
        help="the reference runner configuration, host/model/effort; host `fake` is the "
        "scripted fake runner (model scripted, leaky or idle)",
    )
    s0_cmd.add_argument("-n", "--runs", type=int, default=3, help="runs per table (default 3)")
    s2_cmd = bench_sub.add_parser(
        "s2",
        help="run scenario S2, Beginner Box prep, restoring its bench world before each run, "
        "then report; exits 1 when an invariant fails",
    )
    s2_cmd.add_argument("out", type=Path, help="a new directory for the runs and the report")
    s2_cmd.add_argument(
        "--scenario",
        type=Path,
        required=True,
        help="the private S2 scenario directory (scenario.yaml, gold.yaml)",
    )
    s2_cmd.add_argument(
        "--runner",
        type=_runner_config,
        required=True,
        help="the reference runner configuration, host/model/effort; `fake/prep/none` is the "
        "scripted fake runner",
    )
    s2_cmd.add_argument("-n", "--runs", type=int, default=3, help="runs (default 3)")
    for name, what in (
        ("scale", "the cost of the Core at each size of a synthetic campaign, with no model"),
        (
            "recall",
            "score the Core's temporal queries against a generated gold set, with no model; "
            "exits 1 when an invariant (delayed revelation, retcon) fails",
        ),
    ):
        synthetic = bench_sub.add_parser(name, help=what)
        synthetic.add_argument("--sizes", default="S", help="comma-separated S, M, L (default S)")
        synthetic.add_argument("--seed", type=int, default=0, help="the generator's seed")
    bench_report = bench_sub.add_parser(
        "report", help="recompute a bench report from its stored action logs"
    )
    bench_report.add_argument("out", type=Path, help="the bench output directory")
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            calendar = _calendar_arg(args.calendar)
            ws = workspace.init(args.workspace, args.language, calendar)
            print(
                f"Created campaign workspace {ws.root} (campaign language {ws.campaign_language})"
            )
        elif args.command == "campaign-skill":
            ws = workspace.load(args.workspace)
            changed = campaign_skill.install(ws.root)
            print(
                "Updated: " + ", ".join(changed) if changed else "Campaign skill already current."
            )
        elif args.command == "sources":
            _sources_command(args)
        elif args.command == "token":
            print("Foundry token (keep it secret; paste it into the SecondChair module settings):")
            print(machine.ensure_foundry_token())
        elif args.command == "host":
            print(host_setup(args.host), end="")
        elif args.command == "upgrade":
            before, after, diff = workspace.upgrade(
                args.workspace,
                check,
                _consent_to_destructive,
                preview=args.preview,
                snapshot=not args.no_snapshot,
            )
            if before == after:
                print(f"{args.workspace} is already at schema version {after}.")
            elif args.preview:
                print(diff or f"Schema version {before} to {after} changes no file.", end="")
            else:
                print(
                    f"Upgraded {args.workspace} from schema version {before} to {after}; the "
                    "workspace before it is kept beside it as .pre-upgrade (delete it, or rename "
                    "it back to roll back). Review the diff (git diff) and commit it."
                )
        elif args.command == "backup":
            manifest = snapshot.backup(
                workspace.load(args.workspace),
                args.archive,
                with_library_cache=args.with_library_cache,
                foundry_backup_at=args.foundry_backup_at,
            )
            print(f"Backed up {len(manifest['files'])} files to {args.archive} (mode 0600).")
            print("Back up the paired Foundry world too; SecondChair does not encrypt this file.")
        elif args.command == "restore":
            manifest, report = snapshot.restore(args.archive, args.directory)
            code = check(workspace.load(args.directory))
            print(f"Restored {len(manifest['files'])} files into {args.directory}.")
            print("\n".join(report))
            return code
        elif args.command == "status":
            print(status(workspace.load(args.workspace)))
        elif args.command == "notes":
            problems = notes.check(workspace.load(args.workspace))
            for problem in problems:
                print(f"secondchair: {problem}", file=sys.stderr)
            return 1 if problems else 0
        elif args.command == "check":
            return check(workspace.load(args.workspace))
        elif args.command == "recover":
            ws = workspace.load(args.workspace)
            with delegation.locked(ws):
                done = journal.recover(ws, force=True)
            print("\n".join(done) or "Nothing to recover.")
            return 1 if journal._journals(ws) else 0  # what is left is stopped
        elif args.command == "check-setup":
            return check_setup(args.workspace)
        elif args.command == "doctor":
            return doctor(workspace.load(args.workspace))
        elif args.command == "serve":
            ws = workspace.load(args.workspace)
            serve(ws, configured_port(), review.routes(ws))
        elif args.command == "jobs":
            return _jobs_command(args)
        elif args.command == "transcribe":
            _transcribe_command(args)
        elif args.command == "bench":
            return _bench_command(args)
        elif args.command == "prep":
            return _prep_command(args)
        elif args.command == "mystery":
            print(_mystery_command(args))
        elif args.command == "signals":
            [tool] = signals.tools(workspace.load(args.workspace))
            print(json.dumps(tool.fn(args.session), ensure_ascii=False, indent=2))
        elif args.command == "world":
            print(_world_command(args))
        else:
            print(_gm_command(args))
    except (
        WorkspaceError,
        MachineConfigError,
        RegistrationError,
        DelegationError,
        CanonError,
        runner.RunnerError,
        transcribe.TranscriptionError,
        CalendarError,
        OSError,
    ) as e:
        print(f"secondchair: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
