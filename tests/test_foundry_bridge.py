"""The Foundry bridge handshake (docs/contracts/foundry-bridge.md).

PKG-07, PKG-08, PKG-09, ARC-18."""

import json
import stat
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

import jsonschema
import pytest
import yaml
from conftest import Serving
from websockets.sync.client import connect
from websockets.typing import Origin

from secondchair.cli import main

SCHEMA = json.loads(
    (Path(__file__).parent.parent / "docs/contracts/foundry-bridge.schema.json").read_text()
)
WORLD = "secondchair-dev"


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


def test_a_malformed_hello_is_refused(bridge: str, token: str) -> None:
    with connect(bridge) as socket:
        socket.send("not json")
        reply = json.loads(socket.recv(timeout=5))
    jsonschema.validate(reply, SCHEMA)
    assert reply["type"] == "refused"
