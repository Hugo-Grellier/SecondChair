"""Prep writes world documents (journals, actors, items, playlists) as a desired state; the bridge
has the GM client realise them before the scenes, which may refer to them; the agent finds what
the GM's install holds through generic reads (ARC-07, ARC-10, docs/contracts/foundry-bridge.md).
The reconciliation itself is tested in the module's `node --test`
(foundry/tests/documents.test.js)."""

import json
import threading
import time
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from test_delegation import call, log, ws  # noqa: F401  (ws is a fixture)
from test_foundry_bridge import SCHEMA, bridge, hello, token, workspace  # noqa: F401
from test_scenes import CAVE, gm_client, mcp, prepare, report_of
from websockets.sync.client import ClientConnection

from secondchair.core.workspace import Workspace

NOTE = {
    "type": "JournalEntry",
    "data": {
        "name": "The ransom note",
        "pages": [{"name": "Note", "type": "text", "text": {"markdown": "Bring **100 gp**."}}],
    },
}
GOBLIN = "Compendium.pf2e.pathfinder-bestiary.Actor.aBcD1234"


def prepare_note(bridge: str, desired: dict = NOTE) -> Any:  # noqa: F811
    return mcp(bridge, "prepare_document", {"key": "ransom", **desired, "agent": "claude-prep"})


def next_of(socket: ClientConnection, *kinds: str) -> dict:
    """The next message of one of `kinds` the Core sends, the others skipped."""
    while True:
        message = json.loads(socket.recv(timeout=10))
        jsonschema.validate(message, SCHEMA)
        if message["type"] in kinds and message.get("op") != "rules_context":
            return message


def answer(socket: ClientConnection, request: dict, report: dict) -> None:
    reply = {"type": "realised", "id": request["id"], "ok": True, "report": report}
    jsonschema.validate(reply, SCHEMA)
    socket.send(json.dumps(reply))


def test_prep_writes_a_document_desired_state(ws: Workspace) -> None:  # noqa: F811
    npc = {"type": "Actor", "base": GOBLIN, "data": {"name": "Grik"}}
    result = call(ws, "prepare_document", {"key": "grik", **npc, "agent": "claude-prep"})

    assert result.structured_content == {"entry": 1, "status": "applied"}
    assert yaml.safe_load((ws.root / "documents/grik.yaml").read_text()) == npc
    assert log(ws)[0]["responsibility"] == "prep"


@pytest.mark.parametrize(
    ("desired", "error"),
    [
        ({"type": "Wallpaper", "data": {"name": "x"}}, "Wallpaper"),
        ({"type": "JournalEntry", "data": {}}, "name"),
        ({"type": "Item", "base": GOBLIN, "data": {}}, "Item"),
        ({"type": "Actor", "base": "goblin", "data": {}}, "UUID"),
    ],
)
def test_a_malformed_desired_document_is_refused(ws: Workspace, desired: dict, error: str) -> None:  # noqa: F811
    result = call(ws, "prepare_document", {"key": "x", **desired, "agent": "claude-prep"})

    assert result.is_error
    assert error in result.content[0].text
    assert not (ws.root / "documents").exists()


def test_documents_are_realised_before_scenes_and_reported(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    prepare(bridge, CAVE)
    assert prepare_note(bridge).structured_content["status"] == "applied"
    waiting = mcp(bridge, "document_report", {"key": "ransom"}).structured_content
    assert waiting["realised"] is False

    with gm_client(bridge, token) as socket:
        first = next_of(socket, "realise", "realise_document")
        assert (first["type"], first["document"], first["desired"]) == (
            "realise_document",
            "ransom",
            NOTE,
        )
        assert first["level"] == "act-then-review"
        report = {"document": "j1", "summary": {"create": 1}, "actions": [], "errors": []}
        answer(socket, first, report)
        scene = next_of(socket, "realise", "realise_document")
        assert scene["type"] == "realise"
        answer(
            socket, scene, {"scene": "s1", "summary": {"create": 3}, "actions": [], "errors": []}
        )

        for _ in range(50):
            done = mcp(bridge, "document_report", {"key": "ransom"}).structured_content
            if done["realised"]:
                break
            time.sleep(0.1)
        assert (done["pending"], done["report"]) == (False, report)
        assert report_of(bridge)["report"]["summary"] == {"create": 3}

        # A document changed: the scenes are sent again, as the ids they refer to may have too.
        prepare_note(bridge, {**NOTE, "choice": "overwrite"})
        again = next_of(socket, "realise", "realise_document")
        assert again["desired"]["choice"] == "overwrite"
        answer(socket, again, report)
        assert next_of(socket, "realise", "realise_document")["scene"] == "cave"


@pytest.mark.parametrize(
    ("tool", "arguments", "op", "params"),
    [
        (
            "browse_files",
            {"path": "modules/pf2e-beginner-box/maps", "extensions": [".webp"]},
            "browse_files",
            {"path": "modules/pf2e-beginner-box/maps", "source": "data", "extensions": [".webp"]},
        ),
        (
            "search_compendium",
            {"query": "goblin", "type": "npc"},
            "search_compendium",
            {"query": "goblin", "type": "npc", "limit": 20},
        ),
        (
            "list_world_documents",
            {"type": "Actor"},
            "list_world_documents",
            {"type": "Actor", "query": ""},
        ),
    ],
)
def test_a_generic_read_is_asked_of_the_gm_client(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    tool: str,
    arguments: dict,
    op: str,
    params: dict,
) -> None:
    result = {"dirs": [], "files": ["a.webp"]} if op == "browse_files" else [{"name": "Grik"}]
    with gm_client(bridge, token) as socket:
        answered: dict[str, Any] = {}
        thread = threading.Thread(
            target=lambda: answered.update(reply=mcp(bridge, tool, arguments)), daemon=True
        )
        thread.start()
        read = next_of(socket, "read")
        assert (read["op"], read["params"]) == (op, params)
        socket.send(json.dumps({"type": "reply", "id": read["id"], "ok": True, "result": result}))
        thread.join(timeout=10)

    reply = answered["reply"]
    assert not reply.is_error
    assert reply.structured_content == ({"result": result} if isinstance(result, list) else result)
