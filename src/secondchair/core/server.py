"""`secondchair serve`: the Core's MCP server over Streamable HTTP on loopback (PKG-05)."""

import socket

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from secondchair.core import PROTOCOL_VERSION, delegation
from secondchair.core.tools import load_tools
from secondchair.core.workspace import Workspace

LOOPBACK = "127.0.0.1"
MCP_PATH = "/mcp"


def build_server(ws: Workspace) -> MCPServer:
    """The Core's MCP server with every registered tool; `RegistrationError` if one is refused."""
    server = MCPServer("secondchair", version=PROTOCOL_VERSION, log_level="WARNING")
    for tool in load_tools(ws):
        server.add_tool(
            delegation.wrap(ws, tool) if tool.delegated_action else tool.fn,
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
    server.add_tool(
        delegation.approve_proposal(ws),
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False),
        meta={"secondchair/gm_interaction": True},
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

    return server


def serve(ws: Workspace, port: int) -> None:
    server = build_server(ws)
    # Loopback only, unauthenticated (PKG-05, PKG-06); binding beyond it is deferred (PKG-20).
    # The SDK turns on Host/Origin checks against DNS rebinding for a loopback host.
    app = server.streamable_http_app(streamable_http_path=MCP_PATH, host=LOOPBACK)
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((LOOPBACK, port))
    sock.listen()
    print(f"Serving {ws.root} on http://{LOOPBACK}:{sock.getsockname()[1]}", flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
