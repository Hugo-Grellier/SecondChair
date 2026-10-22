"""The Foundry bridge handshake (docs/contracts/foundry-bridge.md).

PKG-07, PKG-08, PKG-09, ARC-18."""

import asyncio
import contextlib
import json
import queue
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Generator, Iterator
from concurrent.futures import CancelledError
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from conftest import Serving
from mcp import Client
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Origin

from secondchair.cli import main
from secondchair.core.vtt import Unanswered, VttError
from secondchair.core.workspace import load
from secondchair_foundry import bridge as bridge_module
from secondchair_foundry.bridge import Bridge

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
def gm_client(
    url: str,
    token: str,
    ceiling: str = "act-then-review",
    inbox: queue.Queue | None = None,
    sent: list[ClientConnection] | None = None,
) -> Generator[dict[str, dict]]:
    """A connected GM client answering requests in its own little world under `ceiling`, as the
    module's generic actions do; yields that world. Other messages go to `inbox`; the socket
    to `sent`, to say more."""
    docs = {TOKEN: {"x": 100, "y": 200}}
    with connect(url, origin=Origin("https://foundry.example")) as socket:
        socket.send(json.dumps(hello(token)))
        assert json.loads(socket.recv(timeout=5))["type"] == "welcome"
        thread = threading.Thread(target=answer, args=(socket, docs, ceiling, inbox), daemon=True)
        thread.start()
        if sent is not None:
            sent.append(socket)
        yield docs
    thread.join(timeout=5)


LEVELS = ["manual", "propose", "act-then-review", "autonomous"]


def answer(
    socket: ClientConnection, docs: dict[str, dict], ceiling: str, inbox: queue.Queue | None
) -> None:
    """Answer the Core's requests until the socket closes."""
    for raw in socket:
        request = json.loads(raw)
        jsonschema.validate(request, SCHEMA)
        if request["type"] != "request":
            if inbox is not None:
                inbox.put(request)
            continue  # the live session, the Desk
        doc = docs[request["target"]]
        before = dict(doc)
        level = request["level"]
        if level is not None and LEVELS.index(level) > LEVELS.index(ceiling):
            reply = {
                "ok": False,
                "error": f"Refused by the ceiling ({ceiling})",
                "reason": "ceiling",
            }
        elif request["expect"] and request["expect"] != before:
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


def test_above_the_ceiling_the_connector_refuses_and_the_gm_gets_a_call(
    bridge: str, token: str, workspace: Path
) -> None:
    with gm_client(bridge, token, ceiling="propose") as docs:
        result = move(bridge)
        assert docs[TOKEN] == {"x": 100, "y": 200}

    assert result.is_error
    assert "ceiling" in result.content[0].text
    assert (action(workspace)["effective_level"], action(workspace)["status"]) == (
        "act-then-review",
        "failed",
    )
    called = yaml.safe_load((workspace / "calls/000001.yaml").read_text())
    assert (called["kind"], called["entry"]) == ("ceiling_refusal", 1)


# The Director's Desk (ARC-12, ARC-14, DEL-03)


def next_of(inbox: queue.Queue, kind: str, test: Any = lambda _: True) -> dict:
    """The next message of `kind` from the Core passing `test`, skipping the others."""
    while True:
        message = inbox.get(timeout=10)
        if message["type"] == kind and test(message):
            return message


def say(socket: ClientConnection, message: dict) -> None:
    jsonschema.validate(message, SCHEMA)
    socket.send(json.dumps(message))


def test_the_desk_starts_a_session_and_approves_a_vtt_proposal_due_now(
    bridge: str, token: str, workspace: Path
) -> None:
    table = yaml.safe_load((workspace / "delegation.yaml").read_text())
    table["live-session"]["vtt_operations"]["level"] = "propose"
    (workspace / "delegation.yaml").write_text(yaml.safe_dump(table))
    inbox: queue.Queue = queue.Queue()
    sockets: list[ClientConnection] = []
    with gm_client(bridge, token, inbox=inbox, sent=sockets) as docs:
        assert next_of(inbox, "desk")["moment"] == "prep"
        say(sockets[0], {"type": "gesture", "id": "g1", "gesture": "start_session"})
        assert next_of(inbox, "result")["ok"] is True
        live = next_of(inbox, "desk", lambda m: m["moment"] == "live-session")
        assert live["session"] == 1

        async def propose() -> Any:
            async with Client(bridge.replace("ws://", "http://").replace("/foundry", "/mcp")) as c:
                arguments = {"token": TOKEN, "x": 300, "y": 200, "agent": "a", "blocking": True}
                return await c.call_tool("move_token", arguments)

        assert asyncio.run(propose()).structured_content == {"entry": 1, "status": "pending"}
        [due] = next_of(inbox, "desk", lambda m: m["calls"])["calls"]
        assert (due["kind"], due["entry"]) == ("proposal", 1)

        say(sockets[0], {"type": "gesture", "id": "g2", "gesture": "approve", "entry": 1})
        assert next_of(inbox, "result") == {"type": "result", "id": "g2", "ok": True}
        assert docs[TOKEN] == {"x": 300, "y": 200}
    assert (action(workspace)["status"], action(workspace)["approval"]["channel"]) == (
        "applied",
        "desk",
    )


class SlowClient:
    """A GM client socket that keeps the requests it is sent, answered by the test."""

    def __init__(self) -> None:
        self.requests: queue.Queue[dict] = queue.Queue()

    async def send_json(self, message: dict) -> None:
        self.requests.put(message)


@pytest.fixture
def slow(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Bridge, SlowClient]]:
    """A bridge with a GM client that answers after the reply timeout (#99)."""
    monkeypatch.setattr(bridge_module, "REPLY_TIMEOUT", 0.1)
    bridge, client = Bridge(load(workspace)), SlowClient()
    bridge.loop = asyncio.new_event_loop()
    bridge.gm = client  # ty: ignore[invalid-assignment]
    thread = threading.Thread(target=bridge.loop.run_forever, daemon=True)
    thread.start()
    yield bridge, client
    bridge.loop.call_soon_threadsafe(bridge.loop.stop)
    thread.join(timeout=5)


def late_reply(bridge: Bridge, reply: dict) -> None:
    assert bridge.loop is not None
    [request_id] = bridge.waiting  # still awaited after the timeout
    future = bridge.waiting[request_id]
    bridge.loop.call_soon_threadsafe(future.set_result, {"id": request_id, **reply})


def test_a_late_reply_resolves_what_the_timeout_left_unanswered(
    slow: tuple[Bridge, SlowClient],
) -> None:
    bridge, _ = slow
    with pytest.raises(Unanswered, match="may have been taken") as unanswered:
        bridge.perform("move_token", TOKEN, {"x": 300, "y": 200}, None, "act-then-review")

    late_reply(bridge, {"ok": True, "before": {"x": 100}, "after": {"x": 300}})

    assert unanswered.value.later.result(timeout=5) == ({"x": 100}, {"x": 300})


def test_a_late_refusal_raises_its_error_later(slow: tuple[Bridge, SlowClient]) -> None:
    bridge, _ = slow
    with pytest.raises(Unanswered) as unanswered:
        bridge.perform("move_token", TOKEN, {"x": 300, "y": 200}, None, "act-then-review")

    late_reply(bridge, {"ok": False, "error": "changed since"})

    with pytest.raises(VttError, match="changed since"):
        unanswered.value.later.result(timeout=5)


def test_a_client_leaving_unanswered_cancels_what_it_left(
    slow: tuple[Bridge, SlowClient],
) -> None:
    bridge, _ = slow
    with pytest.raises(Unanswered) as unanswered:
        bridge.perform("move_token", TOKEN, {"x": 300, "y": 200}, None, "act-then-review")
    assert bridge.loop is not None
    [future] = bridge.waiting.values()

    bridge.loop.call_soon_threadsafe(future.set_exception, VttError("No GM client"))

    with pytest.raises(CancelledError):
        unanswered.value.later.result(timeout=5)


def snapshot_payload(version: str, extra: tuple[dict, ...] = ()) -> dict:
    entry = {
        "uuid": "Compendium.sys.bestiary.Actor.a1",
        "slug": "grik",
        "name": "Grik",
        "type": "npc",
        "pack": "sys.bestiary",
        "level": 2,
        "rarity": "rare",
        "traits": ["goblin"],
        "publication": "Monster Core",
        "remaster": True,
        "description": "PRIVATE TEXT",  # a faulty module: the Core keeps metadata fields only
    }
    return {
        "system": {"id": "sys", "version": version, "translation": "Traduction"},
        "entries": [entry, *extra],
    }


def connect_with_snapshot(url: str, token: str, payload: dict, kept: Path) -> None:
    """A GM client that answers the Core's compendium snapshot read and stays until the Core
    has kept it."""
    with connect(url, origin=Origin("https://foundry.example")) as socket:
        socket.send(json.dumps(hello(token)))
        assert json.loads(socket.recv(timeout=5))["type"] == "welcome"
        for raw in socket:
            message = json.loads(raw)
            jsonschema.validate(message, SCHEMA)
            if message["type"] == "read" and message["op"] == "compendium_snapshot":
                socket.send(
                    json.dumps(
                        {"type": "reply", "id": message["id"], "ok": True, "result": payload}
                    )
                )
                wait_for(kept)
                break


def search_offline(url: str, **arguments: Any) -> Any:
    async def run() -> Any:
        async with Client(url.replace("ws://", "http://").replace("/foundry", "/mcp")) as c:
            return await c.call_tool("search_compendium", arguments)

    return asyncio.run(run())


def wait_for(path: Path) -> None:
    for _ in range(50):
        if path.exists():
            return
        time.sleep(0.1)
    raise AssertionError(f"{path} was not written")


def test_the_handshake_snapshot_answers_compendium_lookups_with_no_client(
    bridge: str, token: str, workspace: Path
) -> None:
    connect_with_snapshot(
        bridge, token, snapshot_payload("7.1.0"), workspace / ".secondchair/compendium/7.1.0.json"
    )
    time.sleep(0.3)  # the client left; the Core notices

    by_slug = search_offline(bridge, query="GRIK").structured_content
    by_uuid = search_offline(bridge, query="Compendium.sys.bestiary.Actor.a1", type="Actor")
    nothing = search_offline(bridge, query="ogre").structured_content

    assert by_slug["offline"] is True
    assert by_slug["snapshot"] == "7.1.0"
    [entry] = by_slug["entries"]
    assert (entry["slug"], entry["level"], entry["publication"], entry["remaster"]) == (
        "grik",
        2,
        "Monster Core",
        True,
    )
    assert by_uuid.structured_content["entries"][0]["uuid"] == entry["uuid"]
    assert nothing["entries"] == []
    assert "PRIVATE TEXT" not in (workspace / ".secondchair/compendium/7.1.0.json").read_text()


def test_without_a_snapshot_the_compendium_search_still_fails_cleanly(bridge: str) -> None:
    result = search_offline(bridge, query="grik")

    assert result.is_error and "No GM client" in result.content[0].text


def test_a_system_version_change_between_handshakes_is_reported(workspace: Path) -> None:
    from secondchair_foundry import compendium

    ws = load(workspace)
    assert compendium.store(ws, snapshot_payload("7.1.0")) is None
    assert compendium.store(ws, snapshot_payload("7.1.0")) is None  # same version: no change
    time.sleep(0.01)
    extra = (
        {**snapshot_payload("7.2.0")["entries"][0], "uuid": "Compendium.sys.bestiary.Actor.a2"},
    )

    change = compendium.store(ws, snapshot_payload("7.2.0", extra))

    assert (
        change
        == "System sys version changed from 7.1.0 to 7.2.0: 1 entries added, 0 removed, 0 changed."
    )
    with pytest.raises(ValueError, match="malformed"):
        compendium.store(ws, {"system": {"version": "../x"}, "entries": []})


SECRET = "The vault key hides under the altar."


def holding(root: Path, text: str) -> set[str]:
    """The workspace files whose content holds `text`."""
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and text.encode() in p.read_bytes()
    }


def test_a_situation_card_reaches_the_gm_desk_only(
    bridge: str, token: str, workspace: Path
) -> None:
    from test_canon import entity, fact
    from test_knowledge import learn

    from secondchair.core import delegation, observations

    ws = load(workspace)
    tovan = entity(ws, "Tovan Reed")
    learn(ws, tovan, fact(ws, SECRET, entities=[tovan]))
    delegation.start_session(ws)
    for i, (kind, payload) in enumerate(
        [("scene", {"action": "activate", "name": "Tower"}), ("chat", {"speaker": "Tovan Reed"})]
    ):
        envelope: dict[str, Any] = {"id": f"o{i}", "session": 1, "kind": kind}
        envelope["at"] = f"2026-10-21T20:0{i}:00Z"
        envelope |= {"scene": "Scene.t", "actor": None, "visibility": "players"}
        assert observations.record(ws, envelope | {"payload": payload}) is None
    before = holding(workspace, SECRET)

    # A client without the GM's token gets a refusal and nothing else.
    assert SECRET not in json.dumps(reply(bridge, hello("not-the-token")))

    inbox: queue.Queue = queue.Queue()
    sockets: list[ClientConnection] = []
    with gm_client(bridge, token, inbox=inbox, sent=sockets):
        received = [next_of(inbox, "desk")]
        say(sockets[0], {"type": "gesture", "id": "g1", "gesture": "situation"})
        while not (received[-1]["type"] == "desk" and received[-1].get("situation")):
            received.append(inbox.get(timeout=10))
        # A second client, even with the token, is refused while the GM's holds the bridge.
        with connect(bridge, origin=Origin("https://foundry.example")) as second:
            second.send(json.dumps(hello(token)))
            heard = []
            with contextlib.suppress(ConnectionClosed):  # until the Core closes it
                while True:
                    heard.append(json.loads(second.recv(timeout=5)))
        assert [m["type"] for m in heard] == ["refused"]
        assert SECRET not in json.dumps(heard)
        time.sleep(1.5)  # whatever else the Core sends meanwhile
        while not inbox.empty():
            received.append(inbox.get())

    [card] = [m["situation"] for m in received if m["type"] == "desk" and m.get("situation")][:1]
    assert [n["secret"][0]["statement"] for n in card["npcs"]] == [SECRET]
    for message in received:  # the secret travels in the Desk's card, never anywhere else
        rest = {k: v for k, v in message.items() if (message["type"], k) != ("desk", "situation")}
        assert SECRET not in json.dumps(rest), message
    # In the workspace, only the card's own derived file is new to hold it.
    assert holding(workspace, SECRET) - before == {".secondchair/situation.json"}


def test_the_desk_refreshes_when_the_wrap_status_changes(
    bridge: str, token: str, workspace: Path
) -> None:
    from secondchair.core import calls, capture, delegation

    ws = load(workspace)
    inbox: queue.Queue = queue.Queue()
    sockets: list[ClientConnection] = []
    with gm_client(bridge, token, inbox=inbox, sent=sockets):
        assert next_of(inbox, "desk")["wrap"] is None
        for gesture in ("start_session", "end_session"):
            say(sockets[0], {"type": "gesture", "id": gesture, "gesture": gesture})
        queued = next_of(inbox, "desk", lambda m: m["wrap"] is not None)
        assert (queued["wrap"]["session"], queued["wrap"]["status"]) == (1, "queued")

        [job] = [j for j in calls._jobs(ws) if j["playbook"] == capture.PLAYBOOK]
        path = workspace / delegation.JOBS_DIR / f"{job['id']:06d}.yaml"
        path.write_text(yaml.safe_dump({**job, "status": "started"}))  # no other change
        running = next_of(inbox, "desk", lambda m: (m["wrap"] or {}).get("status") == "running")
        assert running["wrap"]["session"] == 1

        path.write_text(yaml.safe_dump({**job, "status": "done"}))
        assert next_of(inbox, "desk", lambda m: m["wrap"]["status"] == "waiting")
        data = capture.time(ws)
        data["sessions"][1] = {"wrapped": True}
        (workspace / capture.TIME_FILE).write_text(yaml.safe_dump(data))
        # A client without the GM's token, a player's, is refused and told nothing of the wrap.
        assert "wrap" not in json.dumps(reply(bridge, hello("not-the-token")))
        assert next_of(inbox, "desk", lambda m: m["wrap"] is None)
