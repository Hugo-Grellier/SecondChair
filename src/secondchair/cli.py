"""The `secondchair` command line."""

import argparse
import contextlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from secondchair import workspace
from secondchair.workspace import Workspace, WorkspaceError

DEFAULT_PORT = 7240
LOOPBACK = "127.0.0.1"


def machine_config_dir() -> Path:
    """The machine configuration (PKG-13): never inside a workspace."""
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "secondchair"


class MachineConfigError(Exception):
    """A machine configuration `serve` cannot use."""


def configured_port() -> int:
    path = machine_config_dir() / "config.yaml"
    if not path.is_file():
        return DEFAULT_PORT
    try:
        config = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise MachineConfigError(f"{path} is not valid YAML: {e}") from e
    port = config.get("port", DEFAULT_PORT) if isinstance(config, dict) else None
    if type(port) is not int or not 0 <= port <= 65535:
        raise MachineConfigError(f"{path}: port must be an integer between 0 and 65535.")
    return port


def serve(ws: Workspace, port: int) -> None:
    body = json.dumps({"service": "secondchair", "campaign_language": ws.campaign_language})

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

    # Loopback only (PKG-05); binding beyond it is deferred (PKG-20).
    with ThreadingHTTPServer((LOOPBACK, port), Handler) as server:
        print(f"Serving {ws.root} on http://{LOOPBACK}:{server.server_port}", flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secondchair")
    commands = parser.add_subparsers(dest="command", required=True)
    init_cmd = commands.add_parser("init", help="create a campaign workspace")
    init_cmd.add_argument("workspace", type=Path)
    init_cmd.add_argument(
        "--language", required=True, help="campaign language, a BCP 47 tag; fixed once set"
    )
    serve_cmd = commands.add_parser("serve", help="serve a campaign workspace on 127.0.0.1")
    serve_cmd.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            ws = workspace.init(args.workspace, args.language)
            print(
                f"Created campaign workspace {ws.root} (campaign language {ws.campaign_language})"
            )
        else:
            serve(workspace.load(args.workspace), configured_port())
    except (WorkspaceError, MachineConfigError, OSError) as e:
        print(f"secondchair: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
