"""Calls on the GM (DEL-30..33, ARC-28, MET-06) and the live session (DEL-03, DEL-03b, DEL-04)."""

import asyncio
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

import jsonschema
import pytest
import yaml
from mcp import Client

from secondchair import cli, runner
from secondchair.cli import main
from secondchair.core import calls, delegation, jobs, workspace
from secondchair.core.server import build_server
from secondchair.core.tools import Change, Tool
from secondchair.core.workspace import Workspace

CONTRACTS = Path(__file__).parents[1] / "docs/contracts"
LOG_SCHEMA = json.loads((CONTRACTS / "action-log-entry.schema.json").read_text())
JOB_SCHEMA = json.loads((CONTRACTS / "job.schema.json").read_text())
CALL_SCHEMA = json.loads((CONTRACTS / "call.schema.json").read_text())


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path), "--language", "fr", "--calendar", "absalom"])
    return workspace.load(tmp_path)


def gm(*argv: str, root: Path, interactive: bool = True) -> int:
    with patch.object(cli, "interactive", return_value=interactive):
        return main([*argv, "--workspace", str(root)])


def records(ws: Workspace, directory: str, schema: dict) -> list[dict]:
    found = [yaml.safe_load(p.read_text()) for p in sorted((ws.root / directory).glob("*.yaml"))]
    for record in found:
        jsonschema.validate(record, schema)
    return found


def log(ws: Workspace) -> list[dict]:
    return records(ws, "action-log", LOG_SCHEMA)


def open_calls(ws: Workspace) -> list[dict]:
    return records(ws, "calls", CALL_SCHEMA)


def set_cell(ws: Workspace, responsibility: str, **cell: str) -> None:
    path = ws.root / delegation.TABLE_FILE
    table = yaml.safe_load(path.read_text())
    table["live-session"][responsibility].update(cell)
    path.write_text(yaml.safe_dump(table))


def propose(ws: Workspace, name: str, **extra: Any) -> Any:
    """create_entity, under memory: at propose in the live session (play profile)."""

    async def run() -> Any:
        async with Client(build_server(ws)) as client:
            return await client.call_tool("create_entity", {"names": [name], "agent": "a", **extra})

    return asyncio.run(run())


# The live session (DEL-03, DEL-03b, DEL-04)


def test_starting_a_session_while_one_is_open_is_refused(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gm("session", "start", root=ws.root) == 0
    assert delegation.current_moment(ws) == ("live-session", 2)
    assert delegation.current_session(ws) == 1
    capsys.readouterr()

    assert gm("session", "start", root=ws.root) == 1
    assert "already open" in capsys.readouterr().err
    assert gm("moment", "prep", root=ws.root) == 1
    assert delegation.current_moment(ws) == ("live-session", 2)


def test_session_start_and_end_need_an_interactive_terminal(ws: Workspace) -> None:
    assert gm("session", "start", root=ws.root, interactive=False) == 1
    assert delegation.current_moment(ws) == ("prep", 1)


def test_ending_the_session_queues_wrap_a_session(ws: Workspace) -> None:
    assert gm("session", "end", root=ws.root) == 1  # none open
    gm("session", "start", root=ws.root)
    assert gm("session", "end", root=ws.root) == 0

    assert delegation.current_moment(ws) == ("between-sessions", 3)
    assert delegation.current_session(ws) is None
    [wrap] = records(ws, "jobs", JOB_SCHEMA)
    assert (wrap["playbook"], wrap["moment"], wrap["status"]) == (
        "wrap-a-session",
        "between-sessions",
        "queued",
    )
    assert wrap["inputs"] == {"session": "1"} and wrap["responsibility"] == "memory"

    gm("session", "start", root=ws.root)
    assert delegation.current_session(ws) == 2


# Deadlines and safe defaults (DEL-30, DEL-31, DEL-32)


def test_in_a_live_session_a_blocking_proposal_is_due_now_and_another_at_the_break(
    ws: Workspace,
) -> None:
    gm("session", "start", root=ws.root)
    assert propose(ws, "Ada Fen", blocking=True).structured_content["status"] == "pending"
    assert propose(ws, "Bo Lark").structured_content["status"] == "pending"

    now, later = open_calls(ws)
    assert (now["kind"], now["entry"], now["deadline"], now["interruption"]) == (
        "proposal",
        1,
        "now",
        True,
    )
    assert (later["deadline"], later["interruption"], later["session"]) == ("break", False, 1)


def test_a_blocking_call_forced_to_break_takes_its_safe_default_at_once(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    set_cell(ws, "memory", deadline="break")
    gm("session", "start", root=ws.root)
    result = propose(ws, "Ada Fen", blocking=True).structured_content
    assert result == {"entry": 1, "status": "rejected"}

    [call] = open_calls(ws)
    assert (call["deadline"], call["status"], call["interruption"]) == ("break", "defaulted", False)
    assert log(ws)[-1] | {"at": None} == {
        "id": 2,
        "at": None,
        "kind": "safe_default",
        "moment": "live-session",
        "moment_seq": 2,
        "call": 1,
        "entry": 1,
        "job": None,
    }
    assert not list(ws.root.glob("canon/entities/*.md"))
    capsys.readouterr()
    assert gm("break", root=ws.root) == 0
    assert "Call 1  proposal  memory  safe default applied: entry 1" in capsys.readouterr().out


def test_a_cell_forced_to_now_makes_a_non_blocking_call_an_interruption(ws: Workspace) -> None:
    set_cell(ws, "memory", deadline="now")
    gm("session", "start", root=ws.root)
    propose(ws, "Ada Fen")
    [call] = open_calls(ws)
    assert (call["deadline"], call["interruption"]) == ("now", True)


def test_an_unanswered_proposal_is_rejected_at_its_deadline_and_shown_again_at_the_break(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    gm("session", "start", root=ws.root)
    propose(ws, "Ada Fen", blocking=True)
    propose(ws, "Bo Lark", blocking=True)
    propose(ws, "Cy Moss")
    assert gm("approve", "2", root=ws.root) == 0

    calls.move_on(ws)  # the blocking scene went on without an answer to entry 1
    assert [c["status"] for c in open_calls(ws)] == ["defaulted", "answered", "open"]
    assert [e["status"] for e in log(ws) if e["kind"] == "action"] == [
        "rejected",
        "applied",
        "pending",
    ]
    assert gm("approve", "1", root=ws.root) == 1

    capsys.readouterr()
    assert gm("break", root=ws.root) == 0
    pile = capsys.readouterr().out
    assert "Call 1  proposal  memory  safe default applied: entry 1" in pile
    assert "Call 3  proposal  memory  to answer: entry 3" in pile and "Call 2" not in pile
    gm("break", root=ws.root)  # a defaulted call is shown again once; an open one until answered
    pile = capsys.readouterr().out
    assert "Call 1" not in pile and "Call 3" in pile

    gm("session", "end", root=ws.root)  # the end of the moment is the last deadline
    assert [c["status"] for c in open_calls(ws)] == ["defaulted", "answered", "defaulted"]
    assert [e["call"] for e in log(ws) if e["kind"] == "safe_default"] == [1, 3]


def test_an_irreversible_action_never_takes_effect_by_default(ws: Workspace) -> None:
    def speak() -> Change:
        return Change(path="lines/1.md", after="Hello")

    tool = Tool(fn=speak, responsibility="disclosure", delegated_action=True, reversible=False)
    gm("session", "start", root=ws.root)
    assert delegation.act(ws, tool, "a", speak, blocking=True)["status"] == "pending"
    calls.move_on(ws)
    assert not (ws.root / "lines/1.md").exists()
    assert log(ws)[0]["status"] == "rejected"


def test_an_exception_takes_no_action_by_default(ws: Workspace) -> None:
    gm("session", "start", root=ws.root)
    calls.raise_exception(ws, "rules_and_combat", "The damage does not add up.", blocking=True)
    [call] = open_calls(ws)
    assert (call["kind"], call["deadline"], call["interruption"]) == ("exception", "now", True)
    calls.move_on(ws)
    assert open_calls(ws)[0]["status"] == "defaulted"
    assert [e["kind"] for e in log(ws)] == ["safe_default"]


# Live jobs (ARC-28)


def live_job(ws: Workspace, blocking: bool = False) -> dict:
    return jobs.queue(
        ws,
        playbook="answer-a-question",
        inputs={},
        expected_output="An answer.",
        responsibility="memory",
        tier="fast",
        blocking=blocking,
    )


def test_a_live_job_missing_its_call_s_deadline_applies_the_safe_default(ws: Workspace) -> None:
    gm("session", "start", root=ws.root)
    assert (live_job(ws, blocking=True)["deadline"], live_job(ws)["deadline"]) == ("now", "break")
    jobs.start(ws, 1, {"host": "h", "model": "m", "effort": "e"}, manual=True)
    assert propose(ws, "Ada Fen", job=1).structured_content["status"] == "pending"
    assert open_calls(ws)[0]["deadline"] == "now"  # inherited from the job

    calls.move_on(ws)
    assert [j["status"] for j in records(ws, "jobs", JOB_SCHEMA)] == ["missed", "queued"]
    assert propose(ws, "Bo Lark", job=1).is_error  # a missed job takes no further action
    assert [(e["call"], e["job"]) for e in log(ws) if e["kind"] == "safe_default"] == [
        (None, 1),
        (1, 1),
    ]
    calls.take_break(ws)
    assert jobs.read(ws, 2)["status"] == "missed"
    assert jobs.pending(ws) == []


def test_the_runner_stops_a_live_job_s_host_once_it_missed_its_deadline(ws: Workspace) -> None:
    gm("session", "start", root=ws.root)
    live_job(ws, blocking=True)
    config = {"host": "slow", "model": "m", "effort": "e"}
    slow = {"slow": [sys.executable, "-c", "import time; time.sleep(60)"]}
    with ThreadPoolExecutor() as pool:
        running = pool.submit(runner.run, ws, 1, {"fast": [config]}, slow)
        while jobs.read(ws, 1)["status"] != "started":
            time.sleep(0.05)
        calls.move_on(ws)
        assert (running.result(timeout=10) or {}).get("status") == "missed"
    [attempt] = jobs.read(ws, 1)["attempts"]
    assert (attempt["outcome"], attempt["error"]) == ("failed", "missed its deadline")
    assert not list(ws.root.glob("calls/*.yaml"))  # no exception: the safe default already ran


def test_a_job_queued_outside_a_live_session_has_no_deadline(ws: Workspace) -> None:
    job = live_job(ws)
    assert (job["deadline"], job["blocking"]) == (None, False)
    calls.take_break(ws)
    assert jobs.read(ws, 1)["status"] == "queued"


# Interruptions (DEL-33, MET-06)

FIXTURE = Path(__file__).parent / "fixtures/interruptions.yaml"


def test_the_interruption_count_matches_the_bench_fixture(ws: Workspace) -> None:
    script = yaml.safe_load(FIXTURE.read_text())
    for responsibility, cell in script["live-session"].items():
        set_cell(ws, responsibility, **cell)
    gm("session", "start", root=ws.root)
    for n, step in enumerate(script["steps"]):
        if step == "move on":
            calls.move_on(ws)
        elif step == "break":
            calls.take_break(ws)
        elif "approve" in step:
            delegation.approve(ws, step["approve"], "cli", True)
        elif "exception" in step:
            calls.raise_exception(ws, step["exception"], "scripted", blocking=step["blocking"])
        else:

            def change(n: int = n) -> Change:
                return Change(path=f"notes/{n}.md", after="x")

            tool = Tool(
                fn=change, responsibility=step["propose"], delegated_action=True, reversible=True
            )
            delegation.act(ws, tool, "bench", change, blocking=step["blocking"])
    gm("session", "end", root=ws.root)

    expected = script["expected"]
    assert calls.interruptions(ws, session=1) == expected["interruptions"]
    defaulted = [c["id"] for c in open_calls(ws) if c["status"] == "defaulted"]
    assert defaulted == expected["defaulted"]
