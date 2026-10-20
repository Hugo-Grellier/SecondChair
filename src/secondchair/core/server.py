"""`secondchair serve`: the Core's MCP server over Streamable HTTP on loopback (PKG-05)."""

import hmac
import json
import socket
from collections.abc import Sequence
from importlib.metadata import entry_points

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute

from secondchair.core import (
    PROTOCOL_VERSION,
    capture,
    delegation,
    jobs,
    machine,
    rules,
    vtt,
    world,
)
from secondchair.core.delegation import DelegationError
from secondchair.core.tools import RegistrationError, load_tools
from secondchair.core.workspace import STATE_DIR, Workspace, WorkspaceError

LOOPBACK = "127.0.0.1"
MCP_PATH = "/mcp"
GM_PATH = "/gm"
SERVE_FILE = "serve.json"
CONNECTOR_GROUP = "secondchair.connectors"


def load_connector_routes(ws: Workspace) -> list[BaseRoute]:
    """The routes VTT connectors serve next to the MCP endpoint (ARC-02, ARC-06), each from a
    `secondchair.connectors` entry point called with the served workspace."""
    routes: list[BaseRoute] = []
    for ep in entry_points(group=CONNECTOR_GROUP):
        try:
            routes.extend(ep.load()(ws))
        except Exception as e:  # a connector's failure stops `serve` cleanly, as for tools
            raise RegistrationError(f"connector {ep.name!r} ({ep.value}): refused: {e}") from e
    return routes


def build_server(ws: Workspace) -> MCPServer:
    """The Core's MCP server with every registered tool; `RegistrationError` if one is refused."""
    server = MCPServer("secondchair", version=PROTOCOL_VERSION, log_level="WARNING")
    for tool in load_tools(ws):
        server.add_tool(
            delegation.wrap(ws, tool) if tool.delegated_action else delegation.wrap_read(tool.fn),
            annotations=ToolAnnotations(
                read_only_hint=not tool.delegated_action,
                destructive_hint=tool.delegated_action and not tool.reversible,
            ),
            meta={
                "secondchair/responsibility": tool.responsibility,
                "secondchair/delegated_action": tool.delegated_action,
                "secondchair/reversible": tool.reversible,
            },
        )
    # A GM interaction relayed by an agent: neither a read nor a delegated action (DEL-27).
    for fn in (
        delegation.approve_proposal(ws),
        delegation.override_tool(ws),
        delegation.hold_tool(ws),
    ):
        server.add_tool(
            fn,
            annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False),
            meta={"secondchair/gm_interaction": True},
        )
    # A discrepancy's fix, always held for the GM's approval (RUL-17): a delegated action whose
    # level the Core caps, so not one of a block's tools.
    for fn in rules.agent_tools(ws):
        server.add_tool(
            fn,
            annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False),
            meta={
                "secondchair/responsibility": rules.RESPONSIBILITY,
                "secondchair/delegated_action": True,
                "secondchair/reversible": True,
            },
        )
    # A session taking and closing a queued job (ARC-29): job state, not canon. A settle-an-unless
    # job's answer and the wrap job's candidates (CAP-04) reach canon through the action log.
    for fn in [*jobs.agent_tools(ws), *world.agent_tools(ws), *capture.agent_tools(ws)]:
        server.add_tool(
            fn,
            annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False),
            meta={"secondchair/job": True},
        )

    @server.custom_route("/", methods=["GET"])
    async def about(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "service": "secondchair",
                "campaign_language": ws.campaign_language,
                "protocol_version": PROTOCOL_VERSION,
            }
        )

    @server.custom_route(GM_PATH, methods=["POST"])
    async def gm_gesture(request: Request) -> JSONResponse:
        """A GM gesture the CLI relays: only this process holds the GM client a VTT action
        needs. Authenticated by the machine's token, which only the GM's account can read."""
        token = machine.foundry_token()
        given = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token is None or not hmac.compare_digest(given.encode(), token.encode()):
            return JSONResponse({"error": "Wrong or missing token."}, status_code=401)
        try:
            body = await request.json()
            gesture = body["gesture"]
            if gesture == "session_start":  # the GM started a live session: the VTT follows
                entry, auth = 0, True
            else:
                entry, auth = body["entry"], body["authenticated"]
            if type(entry) is not int or type(auth) is not bool:
                raise TypeError
        except ValueError, KeyError, TypeError:
            return JSONResponse({"error": "Malformed gesture."}, status_code=400)
        if body.get("workspace") != str(ws.root.resolve()):
            return JSONResponse({"error": f"This Core serves {ws.root}."}, status_code=409)
        if gesture == "session_start":  # CAL-11
            message = await run_in_threadpool(vtt.session_started)
            return JSONResponse({"ok": True, "message": message})
        gestures = {
            "approve": lambda: delegation.approve(ws, entry, "cli", auth),
            "undo": lambda: delegation.undo(ws, entry, str(body.get("reason")), "cli", auth),
        }
        if gesture not in gestures:
            return JSONResponse({"error": f"Unknown gesture {gesture!r}."}, status_code=400)
        try:  # in a worker thread: the VTT action waits on this event loop
            await run_in_threadpool(gestures[gesture])
        except (DelegationError, WorkspaceError) as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return JSONResponse({"ok": True})

    return server


def serve(ws: Workspace, port: int, surface: Sequence[BaseRoute] = ()) -> None:
    """Serve `ws` on loopback, with a Surface's read-only `surface` routes ahead of the Core's."""
    server = build_server(ws)
    # Loopback only, unauthenticated (PKG-05, PKG-06); binding beyond it is deferred (PKG-20).
    # The SDK turns on Host/Origin checks against DNS rebinding for a loopback host.
    app = server.streamable_http_app(streamable_http_path=MCP_PATH, host=LOOPBACK)
    app.router.routes.extend(load_connector_routes(ws))
    app.router.routes[:0] = surface
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((LOOPBACK, port))
    sock.listen()
    # Where the CLI relays GM gestures to (GM_PATH); derived state, stale once serve stops.
    (ws.root / STATE_DIR).mkdir(exist_ok=True)
    serve_file = ws.root / STATE_DIR / SERVE_FILE
    serve_file.write_text(json.dumps({"port": sock.getsockname()[1]}))
    url = f"http://{LOOPBACK}:{sock.getsockname()[1]}"
    print(f"Serving {ws.root} on {url}", flush=True)
    if surface:
        print(f"Review changes and read your prep at {url}/ (read-only)", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
    finally:  # the CLI must not relay a gesture (and the token) to a later listener
        serve_file.unlink(missing_ok=True)
