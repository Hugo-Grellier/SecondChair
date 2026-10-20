"""What the PF2e system adapter feeds the Core over the bridge (docs/contracts/foundry-bridge.md):
the rules context (RUL-22), the world clock (CAL-11..14) and official names (CAN-20), with a
stand-in GM client speaking the module's messages. The adapter's own side: foundry/tests/."""

import asyncio
import json
import threading
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from mcp import Client
from test_foundry_bridge import bridge, hello, token, workspace  # noqa: F401  (fixtures)
from test_observations import BRIDGE
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Origin

from secondchair import cli
from secondchair.core import capture
from secondchair.core.workspace import load

CONTEXT: dict[str, Any] = {
    "foundry": "14.369",
    "system": "pf2e",
    "system_version": "8.6.1",
    "modules": {"pf2-fr": "8.6.0"},
    "settings": {"pf2e.proficiencyVariant": False},
    "turn_driver": None,
}
SETTLE = 1.5  # seconds: the bridge looks at the moment once a second


class GmClient:
    """The GM client: it answers the Core's requests and reads as the library and the PF2e
    adapter do, around a world clock on 4725-03-01, and sends observations."""

    def __init__(self, socket: ClientConnection, context: dict) -> None:
        self.socket = socket
        self.context = context
        self.date = "4725-03-01"
        self.names = {"goblin-warrior": "Gobelin guerrier"}
        self.results: list[dict] = []  # the Core's answers to Director's Desk gestures
        self.desks: list[dict] = []  # what the Director's Desk was told to show

    def send(self, message: dict) -> None:
        BRIDGE.validate(message)
        self.socket.send(json.dumps(message))

    def observe(self, kind: str, payload: dict, session: int | None) -> None:
        envelope = {
            "id": uuid.uuid4().hex,
            "session": session,
            "at": datetime.now(UTC).isoformat(),
            "scene": None,
            "actor": None,
            "kind": kind,
            "visibility": "gm",
            "payload": payload,
        }
        self.send({"type": "observation", "envelope": envelope})

    def answer(self) -> None:
        for raw in self.socket:
            message = json.loads(raw)
            BRIDGE.validate(message)
            if message["type"] == "read":
                self.send({"type": "reply", "id": message["id"], **self.read(message)})
            elif message["type"] == "request":
                self.send({"type": "reply", "id": message["id"], **self.act(message)})
            elif message["type"] == "result":
                self.results.append(message)
            elif message["type"] == "desk":
                self.desks.append(message)

    def act(self, request: dict) -> dict:
        date = request["params"]["date"]
        if request["op"] != "set_date" or not "4600-03-01" <= date <= "4800-02-28":
            return {"ok": False, "error": f"Cannot set the PF2e world clock to {date}."}
        before, self.date = self.date, date
        return {"ok": True, "before": {"date": before}, "after": {"date": date}}

    def read(self, message: dict) -> dict:
        if message["op"] == "rules_context":
            return {"ok": True, "result": self.context}
        key = message["params"]["key"]
        if key not in self.names:
            return {"ok": False, "error": f"No official entry {key!r} in this world's packs."}
        return {"ok": True, "result": {"name": self.names[key], "key": key, "pack": None}}


@contextmanager
def gm_client(url: str, token: str, context: dict = CONTEXT) -> Generator[GmClient]:  # noqa: F811
    with connect(url, origin=Origin("https://foundry.example")) as socket:
        socket.send(json.dumps(hello(token)))
        assert json.loads(socket.recv(timeout=5))["type"] == "welcome"
        client = GmClient(socket, context)
        thread = threading.Thread(target=client.answer, daemon=True)
        thread.start()
        settle()
        yield client
    thread.join(timeout=5)


def settle() -> None:
    asyncio.run(asyncio.sleep(SETTLE))


def gm(workspace: Path, *argv: str) -> int:  # noqa: F811
    with patch.object(cli, "interactive", return_value=True):
        return cli.main([*argv, "-w", str(workspace)])


def recorded(workspace: Path, kind: str) -> list[dict]:  # noqa: F811
    """Every observation of `kind` recorded so far, whatever its session, oldest first."""
    found = [
        o
        for path in (workspace / "observations").glob("*.jsonl")
        for o in map(json.loads, path.read_text().splitlines())
        if o["kind"] == kind
    ]
    return sorted(found, key=lambda o: o["at"])


def test_the_rules_context_is_recorded_on_connection_and_at_the_start_of_each_moment(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    with gm_client(bridge, token):
        [first] = recorded(workspace, "rules_context")
        assert (first["payload"], first["session"]) == (CONTEXT, None)

        assert gm(workspace, "session", "start") == 0
        settle()

        second = recorded(workspace, "rules_context")[-1]
        assert (second["payload"], second["session"]) == (CONTEXT, 1)


def test_a_module_toggled_reloads_the_client_and_its_new_context_is_recorded_once(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    toggled = {**CONTEXT, "modules": {**CONTEXT["modules"], "pf2e-toolbelt": "4.2.0"}}
    for context in (CONTEXT, CONTEXT, toggled):  # each connection is a reload of the client
        with gm_client(bridge, token, context):
            pass

    assert [o["payload"] for o in recorded(workspace, "rules_context")] == [CONTEXT, toggled]


def test_the_desk_learns_the_turn_driver_from_the_rules_context(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    driven = {
        **CONTEXT,
        "modules": {**CONTEXT["modules"], "pf2e-combater": "1.4.2"},
        "turn_driver": "pf2e-combater",
    }
    with gm_client(bridge, token, driven) as client:
        settle()
        assert client.desks[-1]["turn_driver"] == "pf2e-combater"
    with gm_client(bridge, token) as client:
        settle()
        assert client.desks[-1]["turn_driver"] is None


def test_session_start_pushes_the_current_date_and_records_the_clock(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert gm(workspace, "date", "4725-05-12") == 0
    with gm_client(bridge, token) as client:
        assert gm(workspace, "session", "start") == 0

        assert client.date == "4725-05-12"
        assert "from 4725-03-01 to 4725-05-12" in capsys.readouterr().out
        [clock] = recorded(workspace, "clock")
        assert (clock["payload"], clock["session"]) == ({"date": "4725-05-12"}, 1)


def test_session_start_from_the_directors_desk_pushes_the_date_too(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    assert gm(workspace, "date", "4725-05-12") == 0
    with gm_client(bridge, token) as client:
        client.send({"type": "gesture", "id": "g1", "gesture": "start_session"})
        settle()

        assert client.date == "4725-05-12"
        [result] = client.results
        assert result["ok"] and "4725-05-12" in result["message"]


def test_a_date_the_adapter_refuses_is_a_failed_push_and_the_session_still_starts(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert gm(workspace, "date", "4801-01-01") == 0
    with gm_client(bridge, token) as client:
        assert gm(workspace, "session", "start") == 0

        assert client.date == "4725-03-01"
        out = capsys.readouterr().out
        assert "Session 1 started" in out
        assert "not pushed" in out and "4801-01-01" in out


def test_without_a_current_date_session_start_pushes_nothing(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    with gm_client(bridge, token) as client:
        assert gm(workspace, "session", "start") == 0
        assert client.date == "4725-03-01"
    assert "secondchair date" in capsys.readouterr().out


def test_clock_advances_propose_the_session_interval(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    gm(workspace, "date", "4725-05-12")
    with gm_client(bridge, token) as client:
        gm(workspace, "session", "start")
        client.observe("clock", {"date": "4725-05-13", "world_time": 86400}, 1)
        client.observe("clock", {"date": "4725-05-15", "world_time": 259200}, 1)
        settle()
    gm(workspace, "session", "end")

    ws = load(workspace)
    assert capture.observed_interval(ws, 1) == {"start": "4725-05-12", "end": "4725-05-15"}
    assert capture.observed_interval(ws, 2) is None
    assert capture.time(ws)["current_date"] == "4725-05-12"  # only the wrap or the GM move it


def test_the_current_date_is_set_only_from_an_interactive_terminal(
    workspace: Path,  # noqa: F811
) -> None:
    with patch.object(cli, "interactive", return_value=False):
        assert cli.main(["date", "4725-05-12", "-w", str(workspace)]) == 1
    assert gm(workspace, "date", "4725-13-40") == 1
    assert capture.time(load(workspace))["current_date"] is None


def call(bridge: str, tool: str, arguments: dict) -> Any:  # noqa: F811
    async def run() -> Any:
        async with Client(bridge.replace("ws://", "http://").replace("/foundry", "/mcp")) as c:
            return await c.call_tool(tool, arguments)

    return asyncio.run(run())


def test_an_official_name_is_offered_from_the_gm_install_with_its_english_key(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
) -> None:
    with gm_client(bridge, token):
        offered = call(bridge, "official_name", {"key": "goblin-warrior"})
        missing = call(bridge, "official_name", {"key": "nothing-like-it"})

    assert offered.structured_content == {
        "name": "Gobelin guerrier",
        "official_reference": {"key": "goblin-warrior", "pack": None},
    }
    assert missing.is_error and "nothing-like-it" in missing.content[0].text


def test_with_no_gm_client_an_official_name_cannot_be_read(bridge: str) -> None:  # noqa: F811
    result = call(bridge, "official_name", {"key": "goblin-warrior"})
    assert result.is_error and "No GM client" in result.content[0].text
