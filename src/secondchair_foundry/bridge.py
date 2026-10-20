"""The bridge endpoint and handshake (ARC-06, docs/contracts/foundry-bridge.md).

The `secondchair-foundry` module, in the active GM's browser, dials `/foundry` on the loopback
Core (PKG-07). The Core never dials Foundry, so a remotely hosted Foundry connects the same way.
"""

import asyncio
import contextlib
import hmac
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml
from starlette.routing import BaseRoute, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from secondchair.core import (
    PROTOCOL_VERSION,
    capture,
    delegation,
    knowledge,
    observations,
    traces,
    vtt,
)
from secondchair.core.index import CanonError
from secondchair.core.machine import foundry_token
from secondchair.core.vtt import CeilingRefusal, VttError
from secondchair.core.workspace import Workspace, WorkspaceError
from secondchair_foundry import desk
from secondchair_foundry.tools import REPORTS_DIR, SCENES_DIR, digest

PATH = "/foundry"
BINDING_FILE = "foundry.yaml"
HELLO_TIMEOUT = 10  # seconds the module has to say hello once the socket is open
REPLY_TIMEOUT = 15  # seconds the GM client has to take an action and answer
POLL = 1  # seconds between two looks at the live session, and at the desired scenes
REALISE_TIMEOUT = 120  # seconds the GM client has to realise a scene (actor imports included)
POLICY_VIOLATION = 1008
NO_GM = (
    "No GM client is connected: open the campaign's world as GM in Foundry, with the SecondChair "
    "module enabled."
)
RULES_CONTEXT = "rules_context"  # recorded at the start of each moment and when it changes
CLOCK_TARGET = "time"  # what `set_date` acts on: the world clock, not a document


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
        self.loop: asyncio.AbstractEventLoop | None = None
        self.waiting: dict[str, asyncio.Future[dict]] = {}  # replies awaited, by request id
        self.rules_context: tuple[int, object] | None = None  # (moment seq, last one recorded)

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
        self.loop = asyncio.get_running_loop()
        watch: asyncio.Task | None = None
        realising: asyncio.Task | None = None
        gestures: set[asyncio.Task] = set()  # kept referenced until done
        try:
            await socket.send_json(
                {
                    "type": "welcome",
                    "protocol": PROTOCOL_VERSION,
                    "campaign": campaign,
                    "campaign_language": self.ws.campaign_language,
                }
            )
            watch = asyncio.create_task(self._watch(socket))
            realising = asyncio.create_task(self._realise(socket))
            while True:
                try:
                    message = json.loads(await socket.receive_text())
                    kind = message["type"]
                    waiting = (
                        self.waiting.get(message["id"]) if kind in ("reply", "realised") else None
                    )
                except ValueError, KeyError, TypeError:
                    continue  # not a message the Core waits for
                if kind == "observation":
                    await self._observe(socket, message.get("envelope"))
                elif kind in ("traces", "erase_traces"):
                    await self._trace(campaign, message)
                elif kind == "gesture":  # in a task: an approval may wait on a VTT reply
                    gestures.add(task := asyncio.create_task(self._gesture(socket, message)))
                    task.add_done_callback(gestures.discard)
                elif waiting and not waiting.done():
                    waiting.set_result(message)
        except WebSocketDisconnect:
            pass
        finally:
            if watch is not None:
                watch.cancel()
            self.gm = None
            if realising is not None:
                realising.cancel()
            for waiting in self.waiting.values():
                if not waiting.done():
                    waiting.set_exception(VttError(NO_GM))

    async def _watch(self, socket: WebSocket) -> None:
        """Tell the GM client the live session id, now and whenever `secondchair session` opens
        or ends one, so it captures observations tagged with it (CAP-03, DEL-03); and send the
        Director's Desk its state whenever the moment or the calls due now change (ARC-14); and
        record the rules context now and at the start of each moment (RUL-22)."""
        last_session: object = ...
        last_desk: object = ...
        last_seq = None
        reading: set[asyncio.Task] = set()  # rules context reads, never holding up the rest
        while True:
            # ponytail: polls moment.yaml and calls/ every second; events in the first second of
            # a session are missed, and the poll reads every call: index calls if they pile up.
            session = delegation.current_session(self.ws)
            if session != last_session:
                await socket.send_json({"type": "session", "session": session})
                last_session = session
            try:  # every new log entry may be a decision to confirm
                now = await asyncio.to_thread(
                    lambda: (
                        delegation.current_moment(self.ws),
                        desk.due_now(self.ws),
                        knowledge.active_cue(self.ws),
                        self.turn_driver,
                        len(list((self.ws.root / delegation.LOG_DIR).glob("*.yaml"))),
                    )
                )
                if now != last_desk:
                    await self._send_desk(socket)
                    last_desk = now
                if now[0][1] != last_seq:  # a new moment: its rules context
                    last_seq = now[0][1]
                    task = asyncio.create_task(self._record_rules_context(socket))
                    reading.add(task)
                    task.add_done_callback(reading.discard)
            except (WorkspaceError, CanonError, OSError) as e:  # keep the session id flowing
                print(f"SecondChair: Director's Desk not refreshed: {e}", file=sys.stderr)
            await asyncio.sleep(POLL)

    @property
    def turn_driver(self) -> str | None:
        """The turn driver the last rules context names (RUL-11), if any."""
        context = self.rules_context and self.rules_context[1]
        found = context.get("turn_driver") if isinstance(context, dict) else None
        return found if isinstance(found, str) else None

    async def _send_desk(self, socket: WebSocket) -> None:
        await socket.send_json(await asyncio.to_thread(desk.state, self.ws, self.turn_driver))

    async def _gesture(self, socket: WebSocket, message: dict) -> None:
        """Take a GM gesture from the Director's Desk, answer it, then refresh the Desk. In a
        worker thread: approving a VTT action waits on this event loop for the GM client."""
        try:
            result = await asyncio.to_thread(desk.take, self.ws, message)
        except Exception as e:  # the GM still gets an answer, never a gesture left hanging
            error = f"The Core could not take this gesture: {e}"
            result = {"type": "result", "id": str(message.get("id")), "ok": False, "error": error}
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):  # the GM client left
            await socket.send_json(result)
            await self._send_desk(socket)

    async def _record_rules_context(self, socket: WebSocket) -> None:
        """Read the rules context from the GM client and record it, unless this moment already
        recorded the same one (RUL-22). Without a system adapter there is none. Waits on the
        event loop, not in a worker thread, so a GM client slow to answer holds no thread."""
        read = {"type": "read", "id": uuid.uuid4().hex, "op": RULES_CONTEXT, "params": {}}
        try:
            reply = await asyncio.wait_for(self._request(socket, read), REPLY_TIMEOUT)
        except TimeoutError, VttError:
            return
        if reply.get("ok") is True and isinstance(reply.get("result"), dict):
            await asyncio.to_thread(self._record, RULES_CONTEXT, reply["result"])

    def _record(self, kind: str, payload: dict) -> None:
        """Record an observation the Core makes itself through the GM client, as the module's
        are recorded; a rules context only when it changed in this moment. Called from a
        worker thread."""
        seq = delegation.current_moment(self.ws)[1]
        if kind == RULES_CONTEXT:
            if self.rules_context == (seq, payload):
                return
            self.rules_context = (seq, payload)
        envelope = {
            "id": uuid.uuid4().hex,
            "session": delegation.current_session(self.ws),
            "at": datetime.now(UTC).isoformat(),
            "scene": None,
            "actor": None,
            "kind": kind,
            "visibility": "gm",
            "payload": payload,
        }
        try:
            if problem := observations.record(self.ws, envelope):
                print(f"SecondChair: {kind} not recorded: {problem}", file=sys.stderr)
        except OSError as e:
            print(f"SecondChair: {kind} not recorded: {e}", file=sys.stderr)

    def session_started(self) -> str:
        """The Core's `vtt.session_started`: push the campaign's current date into a synced
        calendar's world clock as a prep desired state, keeping Foundry's time of day, and
        record that clock as the session's start (CAL-10, CAL-11, CAL-14)."""
        calendar = self.ws.calendar.name
        if calendar is None:  # a declared calendar has no VTT sync (CAL-10)
            return ""
        date = capture.time(self.ws)["current_date"]
        if date is None:
            return (
                "The campaign has no current date (`secondchair date <date>`): the VTT clock was "
                "not pushed."
            )
        try:
            before, after = self.perform(
                "set_date", CLOCK_TARGET, {"calendar": calendar, "date": date}, None, None
            )
        except VttError as e:  # a failed action: the VTT did not take it (CAL-13)
            return f"The current date {date} was not pushed to the VTT clock: {e}"
        self._record(capture.CLOCK, after)
        return f"VTT clock set from {before.get('date')} to {date}, keeping its time of day."

    async def _observe(self, socket: WebSocket, envelope: object) -> None:
        """Record one observation durably, then acknowledge it so the module drops its copy."""
        if isinstance(envelope, dict) and envelope.get("kind") == RULES_CONTEXT:
            # A rules setting changed in Foundry: what the next moment's context is compared to.
            seq = delegation.current_moment(self.ws)[1]
            self.rules_context = (seq, envelope.get("payload"))
        try:
            problem = await asyncio.to_thread(observations.record, self.ws, envelope)
        except OSError as e:
            # Not acknowledged: the module keeps it and resends it on the next connection.
            print(f"SecondChair: observation not recorded: {e}", file=sys.stderr)
            return
        id_ = envelope.get("id") if isinstance(envelope, dict) else None
        ack = {"type": "ack", "id": str(id_), "ok": problem is None}
        await socket.send_json(ack if problem is None else ack | {"error": problem})

    async def _trace(self, campaign: str, message: dict) -> None:
        """Keep a consenting user's traces on this machine (TRC-04), or erase them all (TRC-01).
        There is no ack: a trace that cannot be kept is lost like one sent with no GM client
        (TRC-05), and never drops the GM connection."""
        try:
            if message["type"] == "erase_traces":
                await asyncio.to_thread(traces.erase, self.ws, campaign, message.get("user"))
            elif reason := traces.problem(message):
                print(f"SecondChair: traces refused: {reason}", file=sys.stderr)
            else:
                await asyncio.to_thread(traces.record, self.ws, campaign, message)
        except (OSError, WorkspaceError) as e:
            print(f"SecondChair: traces not kept or erased: {e}", file=sys.stderr)

    def perform(
        self, op: str, target: str, params: dict, expect: dict | None, level: str | None
    ) -> tuple[dict, dict]:
        """Have the GM client take one action (the Core's `vtt.perform`). Called from a worker
        thread, never from the event loop, which it waits on."""
        socket, loop = self.gm, self.loop
        if socket is None or loop is None:
            raise VttError(NO_GM)
        request = {
            "type": "request",
            "id": uuid.uuid4().hex,
            "op": op,
            "target": target,
            "params": params,
            "expect": expect,
            "level": level,
        }
        future = asyncio.run_coroutine_threadsafe(self._request(socket, request), loop)
        try:
            reply = future.result(REPLY_TIMEOUT)
        except TimeoutError:
            future.cancel()
            raise VttError(
                f"The GM client did not answer within {REPLY_TIMEOUT} s: check the VTT, the "
                "action may have been taken."
            ) from None
        before, after = reply.get("before"), reply.get("after")
        if (
            reply.get("ok") is not True
            or not isinstance(before, dict)
            or not isinstance(after, dict)
        ):
            if reply.get("reason") == "ceiling":
                raise CeilingRefusal(str(reply.get("error")))
            raise VttError(
                str(reply.get("error") or f"The GM client sent a malformed reply: {reply}")
            )
        return before, after

    def read(self, op: str, params: dict) -> object:
        """Ask the GM client what only the VTT knows (the Core's `vtt.read`), such as an
        official name from the GM's install (CAN-20). Called from a worker thread."""
        socket, loop = self.gm, self.loop
        if socket is None or loop is None:
            raise VttError(NO_GM)
        request = {"type": "read", "id": uuid.uuid4().hex, "op": op, "params": params}
        future = asyncio.run_coroutine_threadsafe(self._request(socket, request), loop)
        try:
            reply = future.result(REPLY_TIMEOUT)
        except TimeoutError:
            future.cancel()
            raise VttError(f"The GM client did not answer within {REPLY_TIMEOUT} s.") from None
        if reply.get("ok") is not True or "result" not in reply:
            raise VttError(
                str(reply.get("error") or f"The GM client sent a malformed reply: {reply}")
            )
        return reply["result"]

    async def _realise(self, socket: WebSocket) -> None:
        """Send the GM client every desired scene it has not realised in this connection, then
        each one prep changes, and record its report (ARC-10). With no GM client the desired
        state waits: every connection starts by realising them all, which changes nothing in a
        scene already realised. One scene at a time."""
        sent: dict[str, str] = {}  # scene key -> digest of the desired state sent
        reports = self.ws.root / REPORTS_DIR
        # ponytail: polls the scenes directory; a file watcher if many scenes make it costly.
        while True:
            for path in sorted((self.ws.root / SCENES_DIR).glob("*.yaml")):
                try:
                    text = path.read_text()
                except FileNotFoundError:
                    continue  # removed meanwhile (an undone first preparation)
                if sent.get(path.stem) == digest(text):
                    continue
                sent[path.stem] = digest(text)
                try:
                    desired = yaml.safe_load(text)
                    request = {"type": "realise", "id": uuid.uuid4().hex, "scene": path.stem}
                    reply = await asyncio.wait_for(
                        self._request(socket, {**request, "desired": desired}), REALISE_TIMEOUT
                    )
                    record = {k: reply[k] for k in ("ok", "report", "error") if k in reply}
                except yaml.YAMLError as e:
                    record = {"ok": False, "error": f"{path.name} is not valid YAML: {e}"}
                except TimeoutError:
                    del sent[path.stem]  # sent again: realising twice changes nothing more
                    record = {"ok": False, "error": "The GM client did not answer: check the VTT."}
                except VttError:
                    return  # the GM client left: the next connection realises it
                reports.mkdir(parents=True, exist_ok=True)
                record = {"desired": digest(text), **record}
                (reports / f"{path.stem}.json").write_text(json.dumps(record, ensure_ascii=False))
            await asyncio.sleep(POLL)

    async def _request(self, socket: WebSocket, request: dict) -> dict:
        waiting = asyncio.get_running_loop().create_future()
        self.waiting[request["id"]] = waiting
        try:
            try:
                await socket.send_json(request)
            except (WebSocketDisconnect, RuntimeError) as e:
                raise VttError(NO_GM) from e
            return await waiting
        finally:
            del self.waiting[request["id"]]


async def _close_quietly(socket: WebSocket) -> None:
    with contextlib.suppress(RuntimeError):  # already closed by the client
        await socket.close()


def routes(ws: Workspace) -> list[BaseRoute]:
    """The `secondchair.connectors` entry point: the bridge served next to the MCP endpoint,
    plugged into the Core as the VTT that takes its VTT actions."""
    bridge = Bridge(ws)
    vtt.connect(bridge.perform, bridge.read, bridge.session_started)
    return [WebSocketRoute(PATH, bridge.endpoint)]
