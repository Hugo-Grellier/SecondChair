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
from test_delegation import call, gm, log, ws  # noqa: F401  (ws is a fixture)
from test_foundry_bridge import SCHEMA, bridge, hello, token, workspace  # noqa: F401
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Origin

from secondchair.core import vtt
from secondchair.core.vtt import VttError
from secondchair.core.workspace import Workspace
from secondchair_foundry.bridge import scene_level
from secondchair_foundry.tools import check_assets, digest, validate_manifest

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


def test_a_prepared_scene_is_not_read_as_a_hand_edit_of_canon(ws: Workspace) -> None:  # noqa: F811
    call(ws, "prepare_scene", {"key": "cave", **CAVE, "agent": "claude-prep"})
    call(ws, "search_entities", {"text": ""})  # rebuilds the index, logging hand edits

    assert [e["kind"] for e in log(ws)] == ["action"]
    path = ws.root / "scenes/cave.yaml"
    assert scene_level(ws, path, path.read_text()) == "act-then-review"  # bounded by the ceiling


@pytest.mark.parametrize("folder", ["scenes", "documents"])
def test_a_desired_state_written_outside_prep_is_realised_at_autonomous(
    ws: Workspace,  # noqa: F811
    folder: str,
) -> None:
    """#163: a file no entry wrote is bounded by every ceiling below autonomous (DEL-19a)."""
    path = ws.root / folder / "cave.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(CAVE))
    assert scene_level(ws, path, path.read_text()) == "autonomous"


def test_an_undo_or_a_logged_hand_edit_is_the_gms_and_has_no_level(ws: Workspace) -> None:  # noqa: F811
    call(ws, "prepare_scene", {"key": "cave", **CAVE, "agent": "claude-prep"})
    changed = {**CAVE, "choices": {"boss": "recreate"}}
    call(ws, "prepare_scene", {"key": "cave", **changed, "agent": "claude-prep"})
    assert gm("log", "undo", "2", "--reason", "other", root=ws.root) == 0
    path = ws.root / "scenes/cave.yaml"
    assert scene_level(ws, path, path.read_text()) is None

    # Hand edits are logged for canon files only (CAN-11).
    path = ws.root / "canon/entities/e-1.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Grik\n")
    call(ws, "search_entities", {"text": ""})  # rebuilds the index, logging hand edits
    assert log(ws)[-1]["kind"] == "hand_edit"
    assert scene_level(ws, path, path.read_text()) is None


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
        (
            {**CAVE, "items": [{"key": "g", "type": "Token", "data": {"actorData": {"a": 1}}}]},
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
    """DEL-19a: a scene written outside `prepare_scene` is realised at autonomous (#163)."""
    prepare(bridge, CAVE)
    with gm_client(bridge, token) as socket:
        assert realise(socket)["level"] == "act-then-review"
        edited = {**CAVE, "choices": {"boss": "keep"}}
        (workspace / "scenes/cave.yaml").write_text(yaml.safe_dump(edited, sort_keys=False))
        request = realise(socket)
        assert (request["desired"], request["level"]) == (edited, "autonomous")


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


# --- asset_check (#179): what a scene needs exists in the GM's Foundry before it is realised ---

MAP = "modules/cave/map.webp"
FOUNDRY = {
    "images": {MAP: (2800, 2100), "tokens/boss.webp": (200, 200)},
    "sounds": {"sounds": ["sounds/drip.ogg"]},
    "uuids": {"Actor.grik": ("Grik", "Actor"), "Item.rope": ("Rope", "Item")},
}


@contextmanager
def foundry(world: dict | None = FOUNDRY) -> Generator[None]:
    """A fake GM client answering the reads from `world`, or none connected."""

    def read(op: str, params: dict) -> Any:
        assert world is not None
        if op == "image_size":
            if params["path"] not in world["images"]:
                raise VttError(f"Cannot load {params['path']} in the GM's client.")
            width, height = world["images"][params["path"]]
            return {"width": width, "height": height}
        if op == "browse_files":
            files = world["sounds"].get(params["path"], []) if params["source"] == "data" else []
            return {"dirs": [], "files": files}
        assert op == "resolve_uuid"
        found = world["uuids"].get(params["uuid"])
        return found and {"uuid": params["uuid"], "name": found[0], "type": found[1]}

    vtt.connect(None, read if world is not None else None)
    try:
        yield
    finally:
        vtt.connect(None)


def staged(ws: Workspace, scene: dict, docs: dict[str, dict] | None = None) -> None:  # noqa: F811
    (ws.root / "scenes").mkdir(exist_ok=True)
    (ws.root / "scenes/cave.yaml").write_text(yaml.safe_dump(scene, sort_keys=False))
    for key, doc in (docs or {}).items():
        (ws.root / "documents").mkdir(exist_ok=True)
        (ws.root / f"documents/{key}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


def good_scene() -> dict:
    boss = {"key": "boss", "type": "Token", "actor": "Actor.grik"}
    boss["data"] = {"x": 1, "y": 1, "texture": {"src": "tokens/boss.webp"}}
    drip = {
        "key": "drip",
        "type": "AmbientSound",
        "data": {"x": 1, "y": 1, "path": "sounds/drip.ogg"},
    }
    note = {"key": "note", "type": "Note", "data": {"x": 1, "y": 1, "entryId": "@prepared:diary"}}
    scene = {"name": "Cave", "grid": {"size": 70}, "background": {"src": MAP}}
    return {"scene": scene, "items": [boss, drip, note]}


DIARY = {"JournalEntry": {"type": "JournalEntry", "data": {"name": "Diary"}}}


def checks(ws: Workspace, world: dict | None = FOUNDRY) -> dict:  # noqa: F811
    with foundry(world):
        return check_assets(ws, "cave")


def where(report: dict, bucket: str) -> list[str]:
    return [f"{c['check']}:{c['where'].split(': ')[-1]}" for c in report[bucket]]


def test_an_asset_check_with_everything_in_place_passes(ws: Workspace) -> None:  # noqa: F811
    staged(ws, good_scene(), {"diary": DIARY["JournalEntry"]})

    report = checks(ws)

    assert report["passed"] is True
    assert (report["missing"], report["mismatched"], report["skipped"]) == ([], [], [])
    assert {"file:scene.background.src", "grid:scene.grid.size", "actor:items.0.actor"} <= set(
        where(report, "ok")
    )


def test_an_asset_check_reports_a_missing_file_actor_and_prepared_document(
    ws: Workspace,  # noqa: F811
) -> None:
    scene = good_scene()
    scene["scene"]["background"]["src"] = "modules/cave/gone.webp"
    scene["items"][0]["actor"] = "Actor.nobody"
    scene["items"][1]["data"]["path"] = "sounds/gone.ogg"
    staged(ws, scene)  # no documents/diary.yaml

    report = checks(ws)

    assert report["passed"] is False
    assert sorted(where(report, "missing")) == sorted(
        [
            "file:scene.background.src",
            "actor:items.0.actor",
            "file:items.1.data.path",
            "prepared:items.2.data.entryId",
        ]
    )
    assert report["mismatched"] == []


def test_an_asset_check_reports_a_grid_that_does_not_divide_the_map(ws: Workspace) -> None:  # noqa: F811
    scene = good_scene()
    scene["scene"]["grid"]["size"] = 150  # 2800 / 150 is not whole
    staged(ws, scene, {"diary": DIARY["JournalEntry"]})

    report = checks(ws)

    assert where(report, "mismatched") == ["grid:scene.grid.size"]
    assert report["passed"] is False


def test_an_asset_check_reports_an_actor_that_is_not_an_actor_and_a_wrong_prepared_type(
    ws: Workspace,  # noqa: F811
) -> None:
    scene = good_scene()
    scene["items"][0]["actor"] = "Item.rope"
    scene["items"][2]["actor"] = "@prepared:diary"  # a Note takes no actor: refused on write
    scene["items"][2].pop("actor")
    scene["items"].append({"key": "twin", "type": "Token", "actor": "@prepared:diary", "data": {}})
    staged(ws, scene, {"diary": DIARY["JournalEntry"]})

    report = checks(ws)

    assert sorted(where(report, "mismatched")) == ["actor:items.0.actor", "prepared:items.3.actor"]


def test_an_asset_check_follows_a_prepared_document_and_its_playlist_sounds(
    ws: Workspace,  # noqa: F811
) -> None:
    scene = good_scene()
    scene["scene"]["playlistSound"] = "@prepared:ambience/rain"
    scene["scene"]["playlist"] = "@prepared:ambience"
    sounds = [{"name": "wind", "path": "sounds/drip.ogg"}, {"name": "x", "path": "sounds/no.ogg"}]
    ambience = {"type": "Playlist", "data": {"name": "Ambience", "sounds": sounds}}
    staged(ws, scene, {"diary": DIARY["JournalEntry"], "ambience": ambience})

    report = checks(ws)

    assert sorted(where(report, "missing")) == [
        "file:data.sounds.1.path",
        "prepared:scene.playlistSound",
    ]


def test_an_asset_check_with_no_gm_client_says_what_it_could_not_run(ws: Workspace) -> None:  # noqa: F811
    staged(ws, good_scene(), {"diary": DIARY["JournalEntry"]})

    report = checks(ws, None)

    assert report["passed"] is False
    assert (report["missing"], report["mismatched"]) == ([], [])
    assert [c["check"] for c in report["skipped"]] == ["foundry"]
    assert "No GM client" in report["skipped"][0]["detail"]


def test_an_asset_check_of_a_hand_broken_scene_is_a_mismatch_not_a_crash(ws: Workspace) -> None:  # noqa: F811
    staged(ws, {"scene": {"name": "Cave"}, "items": [{"key": "Bad Key", "type": "Token"}]})

    report = checks(ws)

    assert report["passed"] is False
    assert where(report, "mismatched") == ["schema:scenes/cave.yaml"]


def test_the_scene_report_keeps_realised_valid_and_smoke_tested_apart(ws: Workspace) -> None:  # noqa: F811
    staged(ws, good_scene(), {"diary": DIARY["JournalEntry"]})

    with foundry():
        waiting = call(ws, "scene_report", {"key": "cave"}).structured_content
    assert waiting["production"] == {
        "structurally_valid": True,
        "realised": False,
        "smoke_tested": False,
    }

    record = {"desired": digest((ws.root / "scenes/cave.yaml").read_text()), "ok": True}
    record["report"] = {"summary": {"create": 3}, "actions": [], "errors": []}
    (ws.root / ".secondchair/scenes").mkdir(parents=True)
    (ws.root / ".secondchair/scenes/cave.json").write_text(json.dumps(record))
    with foundry(None):  # realised, but its assets cannot be checked now
        done = call(ws, "scene_report", {"key": "cave"}).structured_content
    assert done["production"] == {
        "structurally_valid": False,
        "realised": True,
        "smoke_tested": False,
    }

    record["report"]["actions"] = [{"action": "conflict", "key": "boss"}]
    (ws.root / ".secondchair/scenes/cave.json").write_text(json.dumps(record))
    with foundry():
        conflicted = call(ws, "scene_report", {"key": "cave"}).structured_content
    assert conflicted["production"]["realised"] is False


# --- the production manifest (#179): what a scene needs, with licence and consent ---


def entry(**over: Any) -> dict:
    base = {
        "key": "cave-map",
        "kind": "map",
        "need": "A goblin cave, 40 by 30 squares",
        "source": "user-file",
        "path": MAP,
        "licence": "GM's own",
        "consent": "local",
        "status": "found",
    }
    return {**base, **over}


def manifest(*entries: dict, **over: Any) -> dict:
    return {"entries": list(entries), **over}


def test_a_good_manifest_validates() -> None:
    generated = entry(
        key="boss-portrait",
        kind="portrait",
        source="provider",
        provider="imagegen",
        pack="generated",
        licence=None,
        consent="model",
        provenance={"prompt": "a goblin", "version": "1", "seed": 7, "terms": "personal use"},
    )
    del generated["licence"]
    validate_manifest(
        manifest(
            entry(),
            entry(key="drip", kind="ambience", status="wanted", path=None, pack="pack"),
            generated,
            packs={"pack": {"licence": "CC-BY"}, "generated": {"licence": "provider terms"}},
            map={"grid": 70, "levels": 1},
        )
    )


@pytest.mark.parametrize(
    ("bad", "error"),
    [
        (manifest(entry(status="done")), "status"),
        (manifest(entry(licence=None)), "no licence"),
        (manifest(entry(pack="nope")), "no licence record"),
        (manifest(entry(consent="maybe")), "consent"),
        (manifest(entry(path=None)), "needs its `path`"),
        (manifest(entry(path="/etc/passwd")), "not a path in Foundry"),
        (manifest(entry(), entry()), "own key"),
        (manifest(entry(source="provider")), "provider"),
        (
            manifest(entry(source="provider", provider="x", provenance={"prompt": "p"})),
            "provenance",
        ),
        (manifest(entry(provenance={"prompt": "p"})), "only a generated"),
        (manifest(entry(), packs={"p": {}}), "licence"),
    ],
)
def test_a_bad_manifest_is_refused(bad: dict, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        validate_manifest(bad)


def write_manifest(ws: Workspace, *entries: dict, **over: Any) -> Any:  # noqa: F811
    arguments = {"key": "cave", "entries": list(entries), "agent": "claude-prep", **over}
    return call(ws, "write_production_manifest", arguments)


def machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config: dict) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config/secondchair").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/secondchair/config.yaml").write_text(yaml.safe_dump(config))


def test_the_manifest_is_written_in_prep(
    ws: Workspace,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine(monkeypatch, tmp_path, {})

    result = write_manifest(ws, entry())

    assert result.structured_content == {"entry": 1, "status": "applied"}
    written = yaml.safe_load((ws.root / "prep/production/cave.yaml").read_text())
    assert written["entries"] == [entry()]
    assert log(ws)[0]["responsibility"] == "prep"


def test_a_purchased_module_file_is_referenced_never_taken_as_another_source(
    ws: Workspace,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine(monkeypatch, tmp_path, {"purchased_content": [{"path": "/data/Data/modules/premium"}]})
    inside = "modules/premium/assets/map.webp"

    refused = write_manifest(ws, entry(path=inside))
    allowed = write_manifest(ws, entry(path=inside, source="install"))
    elsewhere = write_manifest(ws, entry(path="modules/free/map.webp"))

    assert refused.is_error
    assert "purchased" in refused.content[0].text
    assert not allowed.is_error
    assert not elsewhere.is_error


def test_sending_to_a_model_needs_the_providers_switch(
    ws: Workspace,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent = entry(consent="model", provider="imagegen")

    machine(monkeypatch, tmp_path, {})
    assert "off" in write_manifest(ws, sent).content[0].text

    machine(monkeypatch, tmp_path, {"model_providers": ["other"]})
    assert write_manifest(ws, sent).is_error

    machine(monkeypatch, tmp_path, {"model_providers": ["imagegen"]})
    assert not write_manifest(ws, sent).is_error


def test_an_asset_check_reports_wanted_production_apart_from_a_broken_scene(
    ws: Workspace,  # noqa: F811
) -> None:
    staged(ws, good_scene(), {"diary": DIARY["JournalEntry"]})
    (ws.root / "prep/production").mkdir(parents=True)
    wanted = entry(key="theme", kind="music", status="wanted", path=None)
    gone = entry(key="portrait", kind="portrait", path="tokens/gone.webp")
    document = manifest(entry(), wanted, gone, map={"grid": 70})
    (ws.root / "prep/production/cave.yaml").write_text(yaml.safe_dump(document))

    report = checks(ws)

    assert [w["where"].split(": ")[-1] for w in report["wanted"]] == ["theme"]
    assert where(report, "missing") == ["file:portrait"]
    assert "file:cave-map" in where(report, "ok")

    document["entries"].pop()
    (ws.root / "prep/production/cave.yaml").write_text(yaml.safe_dump(document))
    assert checks(ws)["passed"] is True  # wanted production is not a broken scene


def test_an_asset_check_of_a_hand_broken_manifest_is_a_mismatch(ws: Workspace) -> None:  # noqa: F811
    staged(ws, good_scene(), {"diary": DIARY["JournalEntry"]})
    (ws.root / "prep/production").mkdir(parents=True)
    (ws.root / "prep/production/cave.yaml").write_text("entries: [1]")

    assert where(checks(ws), "mismatched") == ["schema:prep/production/cave.yaml"]
