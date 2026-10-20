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
import pytest
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


def next_realise(socket: ClientConnection) -> dict:
    """Take the next scene the Core sends."""
    request = {"type": "session"}
    while request["type"] in ("session", "desk", "read", "ack"):  # told on connection, change
        request = json.loads(socket.recv(timeout=10))
        jsonschema.validate(request, SCHEMA)
    assert request["type"] == "realise"
    return request


def realise(socket: ClientConnection) -> dict:
    """Take the next scene the Core sends and report it realised."""
    request = next_realise(socket)
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


@pytest.mark.parametrize(
    ("bad", "error"),
    [
        ({**CAVE, "scene": {**CAVE["scene"], "ownership.default": 2}}, "ownership"),
        (
            {**CAVE, "items": [{"key": "n", "type": "Note", "data": {"-=ownership": None}}]},
            "ownership",
        ),
        (
            {
                **CAVE,
                "items": [
                    {
                        "key": "t",
                        "type": "Region",
                        "data": {"behaviors": [{"type": "executeScript"}]},
                    }
                ],
            },
            "executeScript",
        ),
        (
            {**CAVE, "items": [{"key": "g", "type": "Token", "data": {"delta": {"name": "x"}}}]},
            "delta",
        ),
        *(
            ({**CAVE, "items": [{"key": "r", "type": "Region", "data": data}]}, error)
            for data, error in [
                ({"behaviors": [{"type": "executeMacro"}]}, "executeMacro"),
                ({"behaviors": [{"type": "my-module.run"}]}, "my-module.run"),
                ({"behaviors.0.type": "executeScript"}, "must be a list"),
                ({"behaviors": {"0": {"type": "pauseGame"}}}, "must be a list"),
                ({"behaviors": ["pauseGame"]}, "must be a list"),
                ({"==behaviors": []}, "operator"),
                ({"flags": {"pf2e": {}}}, "pf2e"),
                ({"flags.core.sheetClass": "x"}, "core"),
                ({"flags": {"secondchair-foundry": {"key": "boss"}}}, "reconciliation"),
                ({"flags.secondchair-foundry.spec": "s"}, "reconciliation"),
                ({"behaviors": [{"type": "toggleBehavior"}]}, "toggleBehavior"),
                ({"behaviors": [{"type": "pauseGame", "system": {"-=once": None}}]}, "operator"),
            ]
        ),
        *(
            ({**CAVE, "scene": {"name": "Cave", **extra}}, error)
            for extra, error in [
                ({"tokens": []}, "as items"),
                ({"walls.0.c": [0, 0, 1, 1]}, "as items"),
                ({"levels": [{}]}, "as items"),
                ({"-=regions": None}, "operator"),
                ({"grid": {"==size": 100}}, "operator"),
                ({"flags": {"secondchair-foundry": {"scene": "x"}}}, "reconciliation"),
                ({"flags": {"core": {}}}, "core"),
            ]
        ),
    ],
)
def test_a_scene_never_sets_ownership_nor_runs_a_script(
    ws: Workspace,  # noqa: F811
    bad: dict,
    error: str,
) -> None:
    result = call(ws, "prepare_scene", {"key": "cave", **bad, "agent": "claude-prep"})

    assert result.is_error
    assert error in result.content[0].text
    assert not (ws.root / "scenes").exists()


def test_a_scene_may_place_an_allowed_region_behaviour(ws: Workspace) -> None:  # noqa: F811
    behaviors = [{"type": "pauseGame"}, {"type": "modifyMovementCost"}]
    region = {"key": "r", "type": "Region", "data": {"behaviors": behaviors}}
    flags = {"flags": {"secondchair-foundry": {"note": "mine"}}}
    tile = {"key": "t", "type": "Tile", "data": flags}
    arguments = {"key": "cave", **CAVE, "items": [region, tile], "agent": "claude-prep"}
    assert not call(ws, "prepare_scene", arguments).is_error


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


def report_of(bridge: str) -> dict:  # noqa: F811
    """The scene's report once the GM client's reply is recorded."""
    for _ in range(50):
        report = mcp(bridge, "scene_report", {"key": "cave"}).structured_content
        if report["realised"]:
            return report
        time.sleep(0.1)
    raise AssertionError("the realisation was never recorded")


def test_a_realisation_carries_the_level_of_the_preparation_that_wrote_it(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    """DEL-19a: a GM hand edit, like an undo, has no level, so the ceiling does not bound it."""
    prepare(bridge, CAVE)
    with gm_client(bridge, token) as socket:
        assert realise(socket)["level"] == "act-then-review"
        edited = {**CAVE, "choices": {"boss": "keep"}}
        (workspace / "scenes/cave.yaml").write_text(yaml.safe_dump(edited, sort_keys=False))
        request = realise(socket)
        assert (request["desired"], request["level"]) == (edited, None)


def test_a_realisation_above_the_ceiling_is_reported_and_sent_again_when_it_changes(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    prepare(bridge, CAVE)
    with gm_client(bridge, token) as socket:
        request = next_realise(socket)
        error = "Refused by this world's delegation ceiling (propose): asked at act-then-review."
        refused = {"type": "realised", "id": request["id"], "ok": False, "error": error}
        refused["reason"] = "ceiling"
        jsonschema.validate(refused, SCHEMA)
        socket.send(json.dumps(refused))
        report = report_of(bridge)
        assert (report["ok"], report["reason"], report["error"]) == (False, "ceiling", error)

        change = {"user": "gm1", "before": "propose", "after": "act-then-review"}
        envelope = {"id": "c1", "session": None, "at": "2026-10-20T20:00:00.000Z"}
        envelope |= {"scene": None, "actor": None, "kind": "ceiling", "visibility": "gm"}
        observation = {"type": "observation", "envelope": envelope | {"payload": change}}
        socket.send(json.dumps(observation))
        assert realise(socket)["scene"] == "cave"  # the GM raised the ceiling: tried again
