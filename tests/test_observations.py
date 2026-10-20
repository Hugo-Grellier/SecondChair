"""Durable observation capture in the event envelope (ARC-16, CAP-03, CAP-08)."""

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource
from test_canon import act, entity, fact, refused
from test_foundry_bridge import SCHEMA as BRIDGE_SCHEMA
from test_foundry_bridge import bridge, hello, token, workspace  # noqa: F401 (fixtures)
from websockets.sync.client import ClientConnection, connect

from secondchair.core import delegation, observations
from secondchair.core import workspace as wsmod
from secondchair.core.workspace import Workspace

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "docs/contracts/event-envelope.schema.json").read_text()
)
# The bridge schema refers to the envelope schema by its $id.
BRIDGE = jsonschema.Draft202012Validator(
    BRIDGE_SCHEMA, registry=Registry().with_resource(SCHEMA["$id"], Resource.from_contents(SCHEMA))
)


def envelope(id: str, visibility: str = "players", session: int = 1) -> dict:
    env = {
        "id": id,
        "session": session,
        "at": "2026-10-19T20:15:00+00:00",
        "scene": "Scene.s1",
        "actor": "Actor.a1",
        "kind": "chat",
        "visibility": visibility,
        "payload": {"author": "Gamemaster", "text": "The bell rings.", "whisper": [], "rolls": []},
    }
    jsonschema.validate(env, SCHEMA, format_checker=jsonschema.FormatChecker())
    return env


@pytest.mark.parametrize(
    "change",
    [
        {"visibility": "whisper"},
        {"kind": "Chat"},
        {"session": 0},
        {"payload": []},
        {"extra": 1},
    ],
)
def test_the_core_refuses_what_the_schema_refuses(change: dict) -> None:
    bad = envelope("o1") | change
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert observations.problem(bad) is not None


def receive(socket: ClientConnection, type_: str) -> dict:
    while True:
        message = json.loads(socket.recv(timeout=5))
        BRIDGE.validate(message)
        if message["type"] == type_:
            return message


def send(socket: ClientConnection, env: dict) -> dict:
    message = {"type": "observation", "envelope": env}
    BRIDGE.validate(message)
    socket.send(json.dumps(message))
    return receive(socket, "ack")


def lines(root: Path, session: int = 1) -> list[dict]:
    path = root / f"observations/{session:06d}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_reload_mid_session_loses_no_observation(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    ws = wsmod.load(workspace)
    delegation.change_moment(ws, "live-session")
    with connect(bridge) as gm:
        gm.send(json.dumps(hello(token)))
        campaign = receive(gm, "welcome")["campaign"]
        assert receive(gm, "session")["session"] == 1
        assert send(gm, envelope("o1")) == {"type": "ack", "id": "o1", "ok": True}
    # The module resends what it holds unacknowledged after the reload: o1 again, and o2.
    with connect(bridge) as gm:
        gm.send(json.dumps(hello(token, campaign=campaign)))
        receive(gm, "session")
        assert send(gm, envelope("o1"))["ok"]
        assert send(gm, envelope("o2", "blind"))["ok"]
        refusal = send(gm, envelope("o3", session=2))
        assert not refusal["ok"]
        assert "session 2" in refusal["error"]
        delegation.change_moment(ws, "between-sessions")
        assert receive(gm, "session")["session"] is None

    assert [o["id"] for o in lines(workspace)] == ["o1", "o2"]
    for o in lines(workspace):
        jsonschema.validate(o, SCHEMA)


def test_a_ceiling_change_is_recorded_in_every_moment(
    bridge: str,  # noqa: F811
    token: str,  # noqa: F811
    workspace: Path,  # noqa: F811
) -> None:
    """DEL-19a: each change of the VTT's ceiling is an observation, in a live session or not."""
    ws = wsmod.load(workspace)
    change = {"user": "gm1", "before": "act-then-review", "after": "propose"}
    ceiling = envelope("c1") | {"kind": "ceiling", "visibility": "gm", "scene": None}
    ceiling |= {"actor": None, "payload": change}
    with connect(bridge) as gm:
        gm.send(json.dumps(hello(token)))
        receive(gm, "welcome")
        assert receive(gm, "session")["session"] is None
        assert send(gm, ceiling | {"session": None})["ok"]  # in prep
        delegation.change_moment(ws, "live-session")
        assert receive(gm, "session")["session"] == 1
        assert send(gm, ceiling | {"id": "c2"})["ok"]

    outside = workspace / observations.OUTSIDE
    [kept] = [json.loads(line) for line in outside.read_text().splitlines()]
    jsonschema.validate(kept, SCHEMA)
    assert (kept["id"], kept["session"], kept["payload"]) == ("c1", None, change)
    assert [o["id"] for o in lines(workspace)] == ["c2"]
    assert observations.find(ws, observations.locator(kept)) == kept


@pytest.fixture
def played(tmp_path: Path) -> Workspace:
    """A workspace whose session 1 recorded a public, a GM-only and a blind observation."""
    from secondchair.cli import main

    main(["init", str(tmp_path / "camp"), "--language", "en", "--calendar", "absalom"])
    ws = wsmod.load(tmp_path / "camp")
    delegation.change_moment(ws, "live-session")
    for visibility in ("players", "gm", "blind"):
        assert observations.record(ws, envelope(visibility, visibility)) is None
    delegation.change_moment(ws, "between-sessions")
    return ws


def seen(id: str, quote: str = "The bell rings.") -> dict:
    return {"kind": "observation", "quote": quote, "locator": f"observations/000001.jsonl#{id}"}


@pytest.mark.parametrize("visibility", ["gm", "blind"])
def test_a_gm_only_or_blind_observation_never_marks_a_fact_known_by_the_party(
    played: Workspace, visibility: str
) -> None:
    bell = fact(played, "The dry bell rang at noon.", entities=[entity(played, "Dry Bell")])

    error = refused(
        played, "record_knowledge", knower="party", fact=bell, origin=seen(visibility), date="4725"
    )

    assert visibility in error
    assert not list((played.root / "canon/knowledge").glob("*.md"))


def test_a_public_observation_marks_a_fact_known_by_the_party(played: Workspace) -> None:
    bell = fact(played, "The dry bell rang at noon.", entities=[entity(played, "Dry Bell")])
    act(played, "record_knowledge", knower="party", fact=bell, origin=seen("players"), date="4725")
    # An NPC may learn from what only the GM saw; an unknown observation is refused.
    act(
        played,
        "record_knowledge",
        knower=entity(played, "Tovan"),
        fact=bell,
        origin=seen("gm"),
        date="4725",
    )
    assert "o-missing" in refused(
        played,
        "record_knowledge",
        knower="party",
        fact=bell,
        origin=seen("o-missing"),
        date="4725",
    )


def test_a_line_cut_short_by_a_crash_is_skipped(played: Workspace) -> None:
    file = played.root / "observations/000001.jsonl"
    file.write_text(file.read_text() + '{"id": "torn", "sess')

    assert observations.record(played, envelope("after")) is None

    assert observations.find(played, "observations/000001.jsonl#after") is not None
    assert observations.find(played, "observations/000001.jsonl#players") is not None


def test_an_observation_waits_for_the_workspace_lock_and_takes_it_reentrantly(
    played: Workspace,
) -> None:
    import threading

    delegation.change_moment(played, "live-session")
    done = threading.Event()
    with delegation.locked(played):  # another writer, e.g. a CLI gesture (#211)
        worker = threading.Thread(
            target=lambda: (observations.record(played, envelope("late")), done.set())
        )
        worker.start()
        assert not done.wait(0.3)
        assert observations.record(played, envelope("mine")) is None  # same thread: reentrant
    worker.join(5)
    assert done.is_set()
    assert observations.find(played, "observations/000001.jsonl#late") is not None
