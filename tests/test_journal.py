"""A world-turn occurrence and its cascade go through one roll-forward journal (ADR 0016, #169):
interrupted at any step, recovery leaves the workspace an uninterrupted run would have, retries
change nothing and no hand edit is logged; a changed input rolls it back, a changed target
stops it behind a call."""

import asyncio
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
import yaml
from test_world import DAY0, SCHEMA, front
from test_world import ws as _ws  # noqa: F401  (a fixture)

from secondchair.cli import main
from secondchair.core import calls, delegation, index, workspace, world
from secondchair.core.delegation import DelegationError
from secondchair.core.workspace import Workspace

NOW = "4725-01-08"  # the front's first tick, crossing both its steps
COMPARED = ("canon", "action-log", "occurrences")


class Frozen(datetime):
    @classmethod
    def now(cls, tz: object = None) -> Frozen:
        return cls(2026, 10, 21, tzinfo=UTC)


class Crash(Exception):
    pass


# A real world-turn in a Core process of its own: at its k-th journal step, it kills itself
# (`kill`) or holds the lock a while (`hold`), touching `flag` first.
CHILD = """
import os, signal, sys, time
from datetime import UTC, datetime
from pathlib import Path
from secondchair.core import delegation, workspace, world

class Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 21, tzinfo=UTC)

delegation.datetime = Frozen
root, mode, k, flag = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), Path(sys.argv[4])
steps = iter(range(10**6))

def fault(step):
    if next(steps) == k:
        if mode == "kill":
            os.kill(os.getpid(), signal.SIGKILL)
        flag.touch()
        time.sleep(1.5)

delegation._fault = fault
world.world_turn(workspace.load(root), "4725-01-08", since="4725-01-01")
"""


def state(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for top in COMPARED
        for p in sorted((root / top).rglob("*"))
        if p.is_file()
    }


def journals(ws: Workspace) -> list[Path]:
    return sorted((ws.root / delegation.JOURNAL_DIR).glob("*.yaml"))


def recover(ws: Workspace) -> None:
    with delegation.locked(ws):  # the first acquisition recovers
        pass


def turn(ws: Workspace) -> None:
    world.world_turn(ws, NOW, since=DAY0 if world.cursor(ws) is None else None)


def hand_edits(ws: Workspace) -> list[dict]:
    index.search_facts(ws)  # a rebuild logs them
    return [e for e in delegation.read_log(ws)[0] if e["kind"] == "hand_edit"]


@pytest.fixture
def cascade(_ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    """A front whose first tick crosses two threshold steps. `run(k)` copies the workspace and
    runs its world-turn, interrupted at the k-th journal step (never when None); `expected`
    is canon, the action log and the occurrences after an uninterrupted run."""
    steps = {"draft": {"clock_gte": 1}, "levy": {"clock_gte": 1}}
    ws = _ws
    tolls, _ = front(ws, "Toll Squeeze", steps=steps)
    monkeypatch.setattr(delegation, "datetime", Frozen)
    runs = iter(range(10**6))

    def copy() -> Workspace:
        return workspace.load(shutil.copytree(ws.root, tmp_path / f"run-{next(runs)}"))

    def run(k: int | None) -> Workspace:
        copied, steps = copy(), iter(range(10**6))

        def fault(step: str) -> None:
            labels.append(step)
            if next(steps) == k:
                raise Crash(step)

        labels.clear()
        monkeypatch.setattr(delegation, "_fault", fault)
        try:
            turn(copied)
            assert k is None
        except Crash:
            assert k is not None
        finally:
            monkeypatch.setattr(delegation, "_fault", lambda step: None)
        return copied

    labels: list[str] = []
    baseline = run(None)
    assert [o["status"] for o in world.occurrences(baseline)] == ["applied"] * 3
    assert world.state(baseline)["fronts"][tolls]["agenda"] == {"draft": "done", "levy": "done"}
    return run, list(labels), state(baseline.root), copy


def test_an_interruption_at_any_step_recovers_to_the_uninterrupted_run(cascade) -> None:
    run, labels, expected, _ = cascade
    # Before and after the journal, after each target and each log entry (three files for the
    # tick and for each step), after each step record and the tick's, before the deletion.
    assert labels[:2] == ["plan", "journal"] and labels[-1] == "commit"
    assert len(labels) == 2 + 3 * 3 * 2 + 3 + 1
    for k in range(len(labels)):
        crashed = run(k)
        left = journals(crashed)
        assert len(left) == (0 if k == 0 else 1)
        kept = left[0].read_text() if left else None
        recover(crashed)
        assert journals(crashed) == []
        turn(crashed)  # the rerun the GM makes: before the journal, it plans the tick again
        assert state(crashed.root) == expected, labels[k]
        assert hand_edits(crashed) == []
        if kept is not None:  # recovery interrupted before it deleted the journal: retried
            journals_dir = crashed.root / delegation.JOURNAL_DIR
            (journals_dir / left[0].name).write_text(kept)
            recover(crashed)
            assert journals(crashed) == [] and state(crashed.root) == expected
        assert not list(crashed.root.rglob("*.tmp")), labels[k]


def test_a_torn_target_is_finished_from_the_journal(cascade) -> None:
    run, _, expected, _ = cascade
    crashed = run(2)  # the tick's fact is written, not its entry
    [journal] = journals(crashed)
    second = yaml.safe_load(journal.read_text())["writes"][2]["path"]  # the tick's event
    torn = crashed.root / (second + ".tmp")
    torn.parent.mkdir(parents=True, exist_ok=True)
    torn.write_text("---\nid: v-tor")  # the rename never happened
    recover(crashed)
    turn(crashed)
    assert state(crashed.root) == expected and not torn.exists()
    assert hand_edits(crashed) == []


def test_a_hand_edited_target_stops_recovery_behind_a_call_until_recover(cascade) -> None:
    run, _, expected, _ = cascade
    crashed = run(2)  # the tick's fact is written, not its entry
    [journal] = journals(crashed)
    written = yaml.safe_load(journal.read_text())["writes"][0]
    target = crashed.root / written["path"]
    target.write_text(written["after"].replace("Toll Squeeze", "Toll Squeeze, edited"))

    recover(crashed)

    [kept] = journals(crashed)
    stopped = yaml.safe_load(kept.read_text())["stopped"]
    [call] = [c for c in calls.read_calls(crashed) if c["id"] == stopped]
    assert call["kind"] == "exception" and written["path"] in call["message"]
    assert "edited" in call["message"] and written["after"] in call["message"]
    recover(crashed)  # not retried on its own: no second call
    assert len([c for c in calls.read_calls(crashed) if c["kind"] == "exception"]) == 1
    assert hand_edits(crashed) == []  # the journal's targets are its own meanwhile
    with pytest.raises(DelegationError, match="recover"):
        turn(crashed)  # the occurrence waits for the GM
    assert main(["recover", "-w", str(crashed.root)]) == 1  # still neither version

    target.write_text(written["after"])  # the GM resolves the file
    assert main(["recover", "-w", str(crashed.root)]) == 0
    turn(crashed)
    assert journals(crashed) == [] and hand_edits(crashed) == []
    assert state(crashed.root) == expected


def test_a_changed_input_rolls_the_occurrence_back_and_calls_on_the_gm(cascade) -> None:
    run, _, _, _ = cascade
    crashed = run(8)  # the tick's three files and entries, and the first step's fact
    table = crashed.root / "delegation.yaml"
    table.write_text(table.read_text() + "# the GM's note\n")  # an input, not a target
    before = len(list((crashed.root / "canon/facts").glob("*.md")))

    recover(crashed)

    assert journals(crashed) == []
    assert world.occurrences(crashed) == []  # the tick's key is free: planned afresh
    undone = [e for e in delegation.read_log(crashed)[0] if e.get("reason") == "recovery"]
    assert undone and all(e["status"] == "undone" for e in undone)
    for entry in undone:
        jsonschema.validate(entry, SCHEMA)
        assert not (crashed.root / entry["target"]).exists()  # back to before
    assert len(list((crashed.root / "canon/facts").glob("*.md"))) < before
    assert calls.read_calls(crashed)[-1]["kind"] == "exception"
    assert hand_edits(crashed) == []

    turn(crashed)
    statuses = [o["status"] for o in world.occurrences(crashed)]
    assert statuses == ["applied"] * 3 and hand_edits(crashed) == []


def test_a_read_finding_a_pending_journal_recovers_before_it_answers(cascade) -> None:
    run, _, _, _ = cascade
    crashed = run(5)
    assert journals(crashed)
    clocks = [f for f in index.search_facts(crashed) if (f["state"] or {}).get("key") == "clock"]
    assert journals(crashed) == []  # the read rebuilt the index, which took the lock
    [now] = [f for f in clocks if f["valid_to"] is None]  # the answer is the finished one
    assert now["statement"] == "Toll Squeeze: 1/4"
    assert hand_edits(crashed) == []


def test_recovery_reached_from_an_event_loop_runs_in_a_worker_thread(
    cascade, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _, _, _ = cascade
    crashed = run(5)
    where: list[threading.Thread] = []
    original = delegation.recover

    def spy(ws: Workspace, force: bool = False) -> list[str]:
        where.append(threading.current_thread())
        return original(ws, force)

    monkeypatch.setattr(delegation, "recover", spy)

    async def bridge_read() -> None:
        recover(crashed)  # on the loop, as the bridge's hello takes the lock

    asyncio.run(bridge_read())
    assert journals(crashed) == []
    assert where and threading.main_thread() not in where


def test_a_plan_held_at_propose_journals_nothing_and_applies_whole_once_accepted(
    cascade, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, _, copy = cascade
    ws = copy()
    table = yaml.safe_load((ws.root / "delegation.yaml").read_text())
    table["prep"]["living_world"]["level"] = "propose"
    (ws.root / "delegation.yaml").write_text(yaml.safe_dump(table))
    journaled: list[dict] = []
    real = delegation.apply_journal

    def spy(ws: Workspace, journal: dict) -> None:
        journaled.append(journal)
        real(ws, journal)

    monkeypatch.setattr(delegation, "apply_journal", spy)

    turn(ws)

    [tick] = world.occurrences(ws)
    assert tick["status"] == "queued" and calls.read_calls(ws)[-1]["kind"] == "proposal"
    assert journaled == [] and not list((ws.root / "canon/knowledge").glob("*.md"))
    world.decide(ws, tick["key"], "accept", authenticated=True)
    [journal] = journaled  # the tick and both its steps, in one journal, its record last
    assert journal["writes"][-1]["path"] == f"occurrences/{tick['id']:06d}.yaml"
    assert [o["status"] for o in world.occurrences(ws)] == ["applied"] * 3
    entries = delegation.read_log(ws)[0]
    approvals = [e for e in entries if e.get("interaction") == "approve"]
    actions = [e for e in entries if e.get("occurrence")]
    assert len(actions) == len(approvals) == 9
    assert all(e["approval"]["interaction"] == e["id"] + 1 for e in actions)
    for entry in actions + approvals:
        jsonschema.validate(entry, SCHEMA)
    assert hand_edits(ws) == []


def run_child(root: Path, mode: str, k: int, flag: Path) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", CHILD, str(root), mode, str(k), str(flag)])


def test_a_world_turn_killed_mid_journal_recovers_in_the_next_process(
    cascade, tmp_path: Path
) -> None:
    _, labels, expected, copy = cascade
    ws = copy()
    child = run_child(ws.root, "kill", labels.index("journal") + 7, tmp_path / "flag")
    assert child.wait(timeout=60) == -9  # SIGKILL
    assert journals(ws)
    recover(ws)
    turn(ws)
    assert state(ws.root) == expected and hand_edits(ws) == []


def test_two_core_processes_racing_the_second_waits_and_finds_nothing_to_recover(
    cascade, tmp_path: Path
) -> None:
    _, labels, expected, copy = cascade
    ws, flag = copy(), tmp_path / "flag"
    child = run_child(ws.root, "hold", labels.index("journal") + 3, flag)
    deadline = time.monotonic() + 60
    while not flag.exists():
        assert time.monotonic() < deadline and child.poll() is None
        time.sleep(0.05)
    assert journals(ws)  # mid-journal, holding the lock
    started = time.monotonic()
    with delegation.locked(ws):
        waited = time.monotonic() - started
        assert journals(ws) == [] and delegation.recover(ws) == []
    assert waited > 0.5 and child.wait(timeout=60) == 0
    assert state(ws.root) == expected and hand_edits(ws) == []
