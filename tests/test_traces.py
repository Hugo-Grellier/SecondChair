"""Behaviour traces reach the Core through the GM's client (TRC-01, TRC-02, TRC-04, TRC-05)."""

import json
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

import yaml
from test_foundry_bridge import bridge, hello, token, workspace  # noqa: F401 (fixtures)
from test_observations import BRIDGE, receive
from websockets.sync.client import ClientConnection, connect

from secondchair.core import delegation
from secondchair.core import traces as traces_mod
from secondchair.core import workspace as wsmod

ALICE, BOB = "alice0000000001", "bob00000000000001"
T0 = 1_760_000_000_000


def eventually[T](read: Callable[[], T]) -> T:
    """What `read` returns once it is truthy: the Core writes traces without acknowledging."""
    deadline = time.monotonic() + 5
    while not (value := read()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert value
    return value


def send(gm: ClientConnection, message: dict) -> None:
    BRIDGE.validate(message)
    gm.send(json.dumps(message))


def traces(user: str, *records: dict) -> dict:
    return {"type": "traces", "user": user, "name": user[:5].title(), "records": list(records)}


def click(t: int) -> dict:
    return {"t": t, "stream": "input", "input": "click", "button": 0, "x": 10, "y": 20}


def stored(data_home: Path, user: str) -> Callable[[], list[dict]]:
    def read() -> list[dict]:
        files = list((data_home / "secondchair/traces").glob(f"*/{user}.jsonl"))
        return [json.loads(line) for f in files for line in f.read_text().splitlines()]

    return read


@contextmanager
def gm_client(bridge: str, token: str) -> Generator[ClientConnection]:  # noqa: F811
    with connect(bridge) as gm:
        gm.send(json.dumps(hello(token)))
        receive(gm, "welcome")
        yield gm


def test_traces_are_kept_outside_the_workspace_tagged_by_moment(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
    machine_config: dict[str, str],
) -> None:
    data_home = Path(machine_config["XDG_DATA_HOME"])
    with gm_client(bridge, token) as gm:
        send(gm, traces(ALICE, click(T0), {"t": T0 + 5, "stream": "semantic", "event": "roll"}))
        lines = eventually(stored(data_home, ALICE))
    campaign = yaml.safe_load((workspace / "foundry.yaml").read_text())["campaign"]
    assert (data_home / f"secondchair/traces/{campaign}/{ALICE}.jsonl").is_file()
    assert [(r["stream"], r["moment"], r["seq"]) for r in lines] == [
        ("input", "prep", 1),
        ("semantic", "prep", 1),
    ]
    assert not [p for p in workspace.rglob("*") if ALICE.encode() in _bytes(p)]


def _bytes(path: Path) -> bytes:
    """A workspace file's bytes; empty for a directory or a file gone since the listing.

    A derived-index rebuild may delete its temporary SQLite journal between rglob and the read.
    """
    try:
        return path.read_bytes()
    except FileNotFoundError, IsADirectoryError:
        return b""


def test_erasing_removes_only_that_users_traces(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    machine_config: dict[str, str],
) -> None:
    data_home = Path(machine_config["XDG_DATA_HOME"])
    with gm_client(bridge, token) as gm:
        send(gm, traces(ALICE, click(T0)))
        send(gm, traces(BOB, click(T0)))
        eventually(stored(data_home, ALICE))
        eventually(stored(data_home, BOB))
        send(gm, {"type": "erase_traces", "user": ALICE})
        eventually(lambda: not stored(data_home, ALICE)())
    assert stored(data_home, BOB)()


def test_a_user_id_that_is_not_one_is_never_a_path(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    machine_config: dict[str, str],
) -> None:
    data_home = Path(machine_config["XDG_DATA_HOME"])
    with gm_client(bridge, token) as gm:
        gm.send(json.dumps(traces("../../escape", click(T0))))
        gm.send(json.dumps({"type": "erase_traces", "user": ".."}))
        send(gm, traces(ALICE, click(T0)))
        eventually(stored(data_home, ALICE))
    assert not list(data_home.rglob("*escape*"))


def test_with_no_gm_client_player_traces_are_lost_and_the_gap_is_in_the_report(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    ws = wsmod.load(workspace)
    delegation.change_moment(ws, "live-session")
    gap = {"t": T0 + 90_000, "stream": "gap", "from": T0, "to": T0 + 90_000, "lost": 42}
    with gm_client(bridge, token) as gm:
        send(gm, traces(ALICE, gap, click(T0 + 91_000)))
        path = workspace / "frictions/000002.md"
        report = eventually(lambda: path.read_text() if path.is_file() else "")
    front = yaml.safe_load(report.split("---")[1])
    assert front["moment"] == "live-session"
    assert front["seq"] == 2
    assert front["gaps"] == [
        {
            "user": ALICE,
            "name": "Alice",
            "from": "2025-10-09T08:53:20Z",
            "to": "2025-10-09T08:54:50Z",
            "lost": 42,
        }
    ]
    assert "Alice" in report.split("---", 2)[2]


def test_erasing_also_removes_the_user_from_the_reports(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
    machine_config: dict[str, str],
) -> None:
    data_home = Path(machine_config["XDG_DATA_HOME"])
    gap = {"t": T0 + 9, "stream": "gap", "from": T0, "to": T0 + 9, "lost": 3}
    path = workspace / "frictions/000001.md"
    text = lambda: path.read_text() if path.is_file() else ""  # noqa: E731
    with gm_client(bridge, token) as gm:
        send(gm, traces(ALICE, gap))
        send(gm, traces(BOB, gap))
        eventually(lambda: ALICE in text() and BOB in text())
        send(gm, {"type": "erase_traces", "user": ALICE})
        eventually(lambda: ALICE not in text())
    assert BOB in text()
    assert not stored(data_home, ALICE)()


def test_a_message_with_no_user_or_a_gap_with_no_count_is_refused() -> None:
    assert traces_mod.problem({"type": "traces", "name": "x", "records": []}) is not None
    assert traces_mod.problem(traces(ALICE, {"t": 5, "stream": "gap"})) is not None
    assert traces_mod.problem(traces(ALICE, click(T0))) is None
