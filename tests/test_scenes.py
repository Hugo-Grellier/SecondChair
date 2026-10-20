"""Prep writes a scene as a desired state; the bridge has the GM client realise it by
reconciliation (ARC-10, BVE-02, docs/contracts/foundry-bridge.md). The reconciliation itself is
tested in the module's `node --test` (foundry/tests/scenes.test.js)."""

import asyncio
import json
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from mcp import Client
from test_delegation import call, log, ws  # noqa: F401  (ws is a fixture)
from test_foundry_bridge import SCHEMA, bridge, hello, token, workspace  # noqa: F401
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Origin

from secondchair.core.workspace import Workspace

CAVE = {
    "scene": {"name": "Goblin cave", "width": 2000, "height": 1500},
    "items": [
        {
            "key": "boss",
            "type": "Token",
            "actor": "Compendium.pf2e.pathfinder-bestiary.Actor.goblin",
            "data": {"name": "Goblin boss", "x": 100, "y": 100, "hidden": True},
        },
        {"key": "torch", "type": "AmbientLight", "data": {"x": 500, "y": 500}},
    ],
}


def mcp(bridge: str, tool: str, arguments: dict[str, Any]) -> Any:  # noqa: F811
    async def run() -> Any:
        async with Client(bridge.replace("ws://", "http://").replace("/foundry", "/mcp")) as c:
            return await c.call_tool(tool, arguments)

    return asyncio.run(run())


def prepare(bridge: str, desired: dict) -> Any:  # noqa: F811
    return mcp(bridge, "prepare_scene", {"key": "cave", **desired, "agent": "claude-prep"})


@contextmanager
def gm_client(url: str, token: str) -> Generator[ClientConnection]:  # noqa: F811
    with connect(url, origin=Origin("https://foundry.example")) as socket:
        socket.send(json.dumps(hello(token)))
        assert json.loads(socket.recv(timeout=5))["type"] == "welcome"
        yield socket


def realise(socket: ClientConnection) -> dict:
    """Take the next scene the Core sends and report it realised."""
    request = {"type": "session"}
    while request["type"] in ("session", "desk", "read"):  # told on connection, change
        request = json.loads(socket.recv(timeout=10))
        jsonschema.validate(request, SCHEMA)
    assert request["type"] == "realise"
    report = {"scene": "s1", "summary": {"create": 3}, "actions": [], "errors": []}
    reply = {"type": "realised", "id": request["id"], "ok": True, "report": report}
    jsonschema.validate(reply, SCHEMA)
    socket.send(json.dumps(reply))
    return request


def test_prep_writes_the_desired_state_in_the_workspace(ws: Workspace) -> None:  # noqa: F811
    result = call(ws, "prepare_scene", {"key": "cave", **CAVE, "agent": "claude-prep"})

    assert result.structured_content == {"entry": 1, "status": "applied"}
    assert yaml.safe_load((ws.root / "scenes/cave.yaml").read_text()) == CAVE
    assert log(ws)[0]["responsibility"] == "prep"


def test_a_malformed_desired_scene_is_refused(ws: Workspace) -> None:  # noqa: F811
    bad = {**CAVE, "items": [{"key": "x", "type": "Wallpaper", "data": {}}]}
    result = call(ws, "prepare_scene", {"key": "cave", **bad, "agent": "claude-prep"})

    assert result.is_error
    assert "Wallpaper" in result.content[0].text
    assert not (ws.root / "scenes").exists()


def test_with_no_gm_client_open_the_desired_state_waits_and_is_applied_on_connection(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    assert prepare(bridge, CAVE).structured_content["status"] == "applied"
    waiting = mcp(bridge, "scene_report", {"key": "cave"}).structured_content
    assert waiting["realised"] is False
    assert "GM client" in waiting["message"]

    with gm_client(bridge, token) as socket:
        request = realise(socket)
        assert (request["scene"], request["desired"]) == ("cave", CAVE)
        for _ in range(50):  # the report is recorded once the reply is in
            report = mcp(bridge, "scene_report", {"key": "cave"}).structured_content
            if report["realised"]:
                break
            time.sleep(0.1)
        assert report["realised"] is True
        assert report["pending"] is False
        assert report["report"]["summary"] == {"create": 3}

        changed = {**CAVE, "choices": {"boss": "recreate"}}
        prepare(bridge, changed)
        assert realise(socket)["desired"] == changed  # a change reaches the connected GM

    with gm_client(bridge, token) as socket:  # every desired scene again on each connection
        assert realise(socket)["desired"] == changed
