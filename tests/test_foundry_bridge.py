"""The Foundry bridge handshake (docs/contracts/foundry-bridge.md).

PKG-07, PKG-08, PKG-09, ARC-18."""

import asyncio
import json
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from conftest import Serving
from mcp import Client
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Origin

from secondchair.cli import main

SCHEMA = json.loads(
    (Path(__file__).parent.parent / "docs/contracts/foundry-bridge.schema.json").read_text()
)
WORLD = "secondchair-dev"
TOKEN = "Scene.s1.Token.t1"


@pytest.fixture
def token(machine_config: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("XDG_CONFIG_HOME", machine_config["XDG_CONFIG_HOME"])
    assert main(["token"]) == 0
    return (
        (Path(machine_config["XDG_CONFIG_HOME"]) / "secondchair" / "foundry-token")
        .read_text()
        .strip()
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "campaign"
    main(["init", str(ws), "--language", "fr", "--calendar", "absalom"])
    return ws


@pytest.fixture
def bridge(workspace: Path, machine_config: dict[str, str], serving: Serving) -> Iterator[str]:
    with serving(workspace, machine_config) as line:
        assert line.startswith("Serving "), line
        yield f"ws://127.0.0.1:{line.rsplit(':', 1)[1]}/foundry"


def hello(token: str, **overrides: object) -> dict:
    message = {
        "type": "hello",
        "protocol": "0.1.0",
        "token": token,
        "world": WORLD,
        "campaign": None,
    } | overrides
    jsonschema.validate(message, SCHEMA)
    return message


@contextmanager
def greet(url: str, message: dict) -> Generator[dict]:
    """Say `message` to the bridge and yield its reply while the connection stays open."""
    with connect(
        url, origin=Origin("https://foundry.example")
    ) as socket:  # a remotely hosted Foundry
        socket.send(json.dumps(message))
        reply = json.loads(socket.recv(timeout=5))
        jsonschema.validate(reply, SCHEMA)
        yield reply


def reply(url: str, message: dict) -> dict:
    with greet(url, message) as answer:
        return answer


def refusal(url: str, message: dict) -> str:
    answer = reply(url, message)
    assert answer["type"] == "refused", answer
    return answer["message"]


def test_secondchair_token_is_kept_private_and_stable(
    token: str, machine_config: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    path = Path(machine_config["XDG_CONFIG_HOME"]) / "secondchair" / "foundry-token"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(token) >= 32
    assert main(["token"]) == 0
    assert capsys.readouterr().out.strip().endswith(token)


def test_a_gm_client_connects_and_binds_the_world(bridge: str, token: str, workspace: Path) -> None:
    with greet(bridge, hello(token)) as welcome:
        assert welcome["type"] == "welcome"
        assert welcome["protocol"] == "0.1.0"
        binding = yaml.safe_load((workspace / "foundry.yaml").read_text())
        assert binding == {"world": WORLD, "campaign": welcome["campaign"]}


def test_a_second_gm_connection_is_refused_until_the_first_leaves(bridge: str, token: str) -> None:
    with greet(bridge, hello(token)) as welcome:
        assert welcome["type"] == "welcome"
        again = hello(token, campaign=welcome["campaign"])
        assert "already connected" in refusal(bridge, again)
    assert reply(bridge, again)["type"] == "welcome"


def test_a_wrong_token_is_refused(bridge: str, token: str) -> None:
    assert "token" in refusal(bridge, hello("not-" + token))


def test_without_a_token_the_gm_is_told_to_create_one(bridge: str) -> None:
    assert "secondchair token" in refusal(bridge, hello("anything"))


@pytest.mark.parametrize("version", ["0.2.0", "1.0.0", "nonsense"])
def test_an_incompatible_protocol_is_refused(bridge: str, token: str, version: str) -> None:
    message = refusal(bridge, hello(token, protocol=version))
    assert "protocol" in message
    assert "0.1.0" in message


def test_a_compatible_patch_version_connects(bridge: str, token: str) -> None:
    assert reply(bridge, hello(token, protocol="0.1.7"))["type"] == "welcome"


def test_a_world_bound_to_another_campaign_is_refused(bridge: str, token: str) -> None:
    other = "0" * 32
    assert "another campaign" in refusal(bridge, hello(token, campaign=other))


def test_a_campaign_bound_to_another_world_refuses_this_one(bridge: str, token: str) -> None:
    reply(bridge, hello(token))
    message = refusal(bridge, hello(token, world="another-world", campaign=None))
    assert WORLD in message
    assert "another-world" in message


def test_a_bound_world_that_lost_its_mark_reconnects(bridge: str, token: str) -> None:
    welcome = reply(bridge, hello(token))
    assert reply(bridge, hello(token)) == welcome


@contextmanager
def gm_client(url: str, token: str) -> Generator[dict[str, dict]]:
    """A connected GM client answering requests in its own little world, as the module's
    generic actions do; yields that world."""
    docs = {TOKEN: {"x": 100, "y": 200}}
    with connect(url, origin=Origin("https://foundry.example")) as socket:
        socket.send(json.dumps(hello(token)))
        assert json.loads(socket.recv(timeout=5))["type"] == "welcome"
        thread = threading.Thread(target=answer, args=(socket, docs), daemon=True)
        thread.start()
        yield docs
    thread.join(timeout=5)


def answer(socket: ClientConnection, docs: dict[str, dict]) -> None:
    """Answer the Core's requests until the socket closes."""
    for raw in socket:
        request = json.loads(raw)
        jsonschema.validate(request, SCHEMA)
        doc = docs[request["target"]]
        before = dict(doc)
        if request["expect"] and request["expect"] != before:
            reply = {"ok": False, "error": f"{request['target']} changed since"}
        else:
            doc.update(request["params"])
            reply = {"ok": True, "before": before, "after": dict(doc)}
        message = {"type": "reply", "id": request["id"], **reply}
        jsonschema.validate(message, SCHEMA)
        socket.send(json.dumps(message))


def move(bridge: str) -> Any:
    async def run() -> Any:
        async with Client(bridge.replace("ws://", "http://").replace("/foundry", "/mcp")) as c:
            return await c.call_tool(
                "move_token", {"token": TOKEN, "x": 300, "y": 200, "agent": "claude-live"}
            )

    return asyncio.run(run())


def gm_undo(workspace: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "secondchair.cli", "log", "undo", "1", "--reason", "tone"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
    )


def action(workspace: Path) -> dict:
    return yaml.safe_load((workspace / "action-log/000001.yaml").read_text())


def test_an_agent_moves_a_token_and_the_gm_undoes_it_from_the_cli(
    bridge: str, token: str, workspace: Path, machine_config: dict[str, str]
) -> None:
    with gm_client(bridge, token) as docs:
        assert move(bridge).structured_content == {"entry": 1, "status": "applied"}
        assert docs[TOKEN] == {"x": 300, "y": 200}

        undo = gm_undo(workspace, machine_config)

        assert undo.returncode == 0, undo.stderr
        assert docs[TOKEN] == {"x": 100, "y": 200}
    assert (action(workspace)["op"], action(workspace)["status"]) == ("move_token", "undone")


def test_undo_of_a_vtt_action_needs_the_core_served(
    bridge: str, token: str, workspace: Path, machine_config: dict[str, str]
) -> None:
    with gm_client(bridge, token):
        move(bridge)
    (workspace / ".secondchair/serve.json").unlink()

    undo = gm_undo(workspace, machine_config)

    assert undo.returncode == 1
    assert "secondchair serve" in undo.stderr
    assert action(workspace)["status"] == "applied"


def test_the_gm_gesture_relay_refuses_a_wrong_token(
    bridge: str, token: str, workspace: Path
) -> None:
    gesture = {"gesture": "undo", "entry": 1, "reason": "tone", "authenticated": True}
    request = urllib.request.Request(
        bridge.replace("ws://", "http://").replace("/foundry", "/gm"),
        data=json.dumps({**gesture, "workspace": str(workspace.resolve())}).encode(),
        headers={"Authorization": f"Bearer not-{token}"},
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)
    assert refused.value.code == 401


def test_with_no_gm_client_open_the_action_fails_cleanly(bridge: str, workspace: Path) -> None:
    result = move(bridge)

    assert result.is_error
    assert "No GM client" in result.content[0].text
    assert action(workspace)["status"] == "failed"


def test_a_malformed_hello_is_refused(bridge: str, token: str) -> None:
    with connect(bridge) as socket:
        socket.send("not json")
        reply = json.loads(socket.recv(timeout=5))
    jsonschema.validate(reply, SCHEMA)
    assert reply["type"] == "refused"
