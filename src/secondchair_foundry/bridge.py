"""The bridge endpoint and handshake (ARC-06, docs/contracts/foundry-bridge.md).

The `secondchair-foundry` module, in the active GM's browser, dials `/foundry` on the loopback
Core (PKG-07). The Core never dials Foundry, so a remotely hosted Foundry connects the same way.
"""

import asyncio
import contextlib
import hmac
import json
import uuid
from pathlib import Path

import yaml
from starlette.routing import BaseRoute, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from secondchair.core import PROTOCOL_VERSION
from secondchair.core.machine import foundry_token
from secondchair.core.workspace import Workspace

PATH = "/foundry"
BINDING_FILE = "foundry.yaml"
HELLO_TIMEOUT = 10  # seconds the module has to say hello once the socket is open
POLICY_VIOLATION = 1008


class Refused(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def compatible(version: object) -> bool:
    """Semver compatibility with the Core's protocol version: same major, and same minor
    while the major is 0 (ARC-17)."""

    def key(v: str) -> tuple[int, ...]:
        major, minor, _patch = (int(n) for n in v.split("-")[0].split("."))
        return (major,) if major else (0, minor)

    try:
        return isinstance(version, str) and key(version) == key(PROTOCOL_VERSION)
    except ValueError:
        return False


class Bridge:
    """One campaign's bridge: one GM connection at a time (PKG-08)."""

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws
        self.gm: WebSocket | None = None

    @property
    def binding_path(self) -> Path:
        return self.ws.root / BINDING_FILE

    def check(self, hello: object) -> str:
        """The campaign id to welcome `hello` with, or `Refused`. Never awaits, so two clients
        cannot both pass the one-GM check."""
        if not (
            isinstance(hello, dict)
            and hello.get("type") == "hello"
            and isinstance(hello.get("token"), str)
            and isinstance(hello.get("world"), str)
            and hello["world"]
            and isinstance(hello.get("campaign"), str | None)
        ):
            raise Refused("malformed", "The module sent a malformed hello; update it.")
        expected = foundry_token()
        if expected is None:
            raise Refused(
                "no_token",
                "The Core has no Foundry token yet: run `secondchair token` on the machine "
                "running the Core and paste it into the SecondChair module settings.",
            )
        if not hmac.compare_digest(hello["token"].encode(), expected.encode()):
            raise Refused(
                "wrong_token",
                "Wrong token: paste the one `secondchair token` prints into the SecondChair "
                "module settings.",
            )
        if not compatible(hello.get("protocol")):
            raise Refused(
                "protocol",
                f"Incompatible protocol: the module speaks {hello.get('protocol')!r}, the Core "
                f"{PROTOCOL_VERSION}. Install matching versions of SecondChair and its module.",
            )
        if self.gm is not None:
            raise Refused(
                "busy",
                "Another GM client is already connected to this campaign; close it first.",
            )
        return self.bind(hello["world"], hello["campaign"])

    def bind(self, world: str, campaign: str | None) -> str:
        """Check the world against the workspace's binding (PKG-09, ARC-18), binding an unbound
        world to an unbound workspace on first contact."""
        binding = (
            yaml.safe_load(self.binding_path.read_text()) if self.binding_path.exists() else None
        )
        if campaign is not None and (binding is None or campaign != binding["campaign"]):
            raise Refused(
                "world",
                f"The Foundry world {world!r} is bound to another campaign. Open the world bound "
                f"to {self.ws.root.name!r}, or serve that other campaign's workspace.",
            )
        if binding is not None and binding["world"] != world:
            raise Refused(
                "world",
                f"The campaign {self.ws.root.name!r} is bound to the Foundry world "
                f"{binding['world']!r}, not {world!r}.",
            )
        if binding is None:
            binding = {"world": world, "campaign": uuid.uuid4().hex}
            self.binding_path.write_text(yaml.safe_dump(binding, sort_keys=False))
        return binding["campaign"]

    async def endpoint(self, socket: WebSocket) -> None:
        await socket.accept()
        try:
            text = await asyncio.wait_for(socket.receive_text(), HELLO_TIMEOUT)
            try:
                hello = json.loads(text)
            except ValueError:
                hello = None
            campaign = self.check(hello)
        except Refused as refused:
            await socket.send_json(
                {"type": "refused", "reason": refused.reason, "message": str(refused)}
            )
            await socket.close(POLICY_VIOLATION)
            return
        except TimeoutError, WebSocketDisconnect:
            await _close_quietly(socket)
            return
        self.gm = socket
        try:
            await socket.send_json(
                {
                    "type": "welcome",
                    "protocol": PROTOCOL_VERSION,
                    "campaign": campaign,
                    "campaign_language": self.ws.campaign_language,
                }
            )
            while True:  # ponytail: messages after the handshake arrive with #48
                await socket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            self.gm = None


async def _close_quietly(socket: WebSocket) -> None:
    with contextlib.suppress(RuntimeError):  # already closed by the client
        await socket.close()


def routes(ws: Workspace) -> list[BaseRoute]:
    """The `secondchair.connectors` entry point: the bridge served next to the MCP endpoint."""
    return [WebSocketRoute(PATH, Bridge(ws).endpoint)]
