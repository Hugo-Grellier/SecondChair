"""The read-only review and prep view `serve` shows on its loopback port: what agents changed and
what awaits the GM, the prep to read at the table, canon and jobs.

Not an authenticated Surface (ARC-13): it approves nothing and shows the CLI command instead. It
holds no state (ARC-11): every response is read from the workspace at request time.
"""

import difflib
import hashlib
import json
import shlex
from collections.abc import Awaitable, Callable
from contextlib import closing
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import BaseRoute, Match, Route
from starlette.types import Scope

from secondchair.core import calls, capture, delegation, index, jobs
from secondchair.core.workspace import STATE_DIR, Workspace, WorkspaceError

PAGE_SIZE = 50
READABLE = ("prep", "notes")  # the Markdown the page renders; nothing else is served
DESIRED = ("scenes", "documents")  # desired Foundry state, with its last reconciliation report

# What the page shows of an action log entry, besides its diff and the GM's commands.
SHOWN = [
    "id",
    "at",
    "kind",
    "moment",
    "status",
    "tool",
    "agent",
    "responsibility",
    "target",
    "reversible",
    "effective_level",
    "job",
    "interaction",
    "entry",
    "reason",
    "error",
    "refusal",
    "rank",
]

type Handler = Callable[[Request], Awaitable[Response]]


class _PageRoute(Route):
    """`/` for a browser only: other clients keep the Core's JSON `about` there."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        accept = dict(scope.get("headers") or []).get(b"accept", b"")
        return super().matches(scope) if b"text/html" in accept else (Match.NONE, {})


def _guarded(handler: Handler) -> Handler:
    """Refuse a Host other than this loopback port, against DNS rebinding; send no CORS header."""

    async def guarded(request: Request) -> Response:
        port = request.scope["server"][1]
        if request.headers.get("host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return JSONResponse({"error": "Wrong Host header."}, status_code=421)
        try:
            return await handler(request)
        except WorkspaceError as e:
            return JSONResponse({"error": str(e)}, status_code=409)

    return guarded


def command(ws: Workspace, *argv: str | int) -> str:
    """The CLI command the GM runs, aimed at this workspace from any directory."""
    return shlex.join(["secondchair", *map(str, argv), "-w", str(ws.root.resolve())])


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return yaml.safe_dump(content, allow_unicode=True, sort_keys=False)


def _diff(entry: dict) -> list[str]:
    before, after = _text(entry.get("before")), _text(entry.get("after"))
    lines = difflib.unified_diff(
        before.splitlines(), after.splitlines(), "before", "after", lineterm=""
    )
    return list(lines)[2:]  # the ---/+++ header says nothing the page does not


def _entry(ws: Workspace, entry: dict, seq: int) -> dict:
    """An action log entry as the page shows it: who did what, its diff, the GM's commands."""
    view = {k: entry.get(k) for k in SHOWN if k in entry}
    view["diff"] = _diff(entry) if "before" in entry or "after" in entry else []
    commands = {}
    if entry.get("kind") == "action" and entry.get("status") == "pending":
        commands["approve"] = command(ws, "approve", entry["id"])
        commands["reject"] = command(ws, "reject", entry["id"], "--reason", "<reason>")
    if (
        entry.get("kind") == "action"
        and entry.get("status") == "applied"
        and entry.get("reversible")
        and entry.get("moment_seq") == seq  # the moment's log freezes when it ends (DEL-25)
    ):
        commands["undo"] = command(ws, "log", "undo", entry["id"], "--reason", "<reason>")
    if entry.get("kind") == "hand_edit" and entry.get("rank") == "agent_proposal":
        commands["promote"] = command(ws, "promote", entry["id"])
    view["commands"] = commands
    return view


def _log(ws: Workspace) -> tuple[list[dict], int]:
    seq = delegation.current_moment(ws)[1]
    return [_entry(ws, e, seq) for e in reversed(delegation.read_log(ws)[0])], seq


def _jobs(ws: Workspace) -> list[dict]:
    paths = sorted((ws.root / delegation.JOBS_DIR).glob("*.yaml"))
    return [jobs.read(ws, int(p.stem)) for p in paths if p.stem.isdigit()]


def routes(ws: Workspace) -> list[BaseRoute]:
    """The page at `/` and its JSON under `/api/`, GET only."""
    root = ws.root.resolve()

    async def page(_: Request) -> Response:
        return HTMLResponse(files("secondchair").joinpath("review.html").read_text())

    async def overview(_: Request) -> Response:
        moment, seq = delegation.current_moment(ws)
        live = delegation.current_session(ws)
        time = capture.time(ws)
        held = [e["id"] for e in delegation.read_log(ws)[0] if e.get("status") == "pending"]
        to_do = jobs.pending(ws)
        entities, facts, events = index.counts(ws)
        played = delegation.last_session(ws)
        unwrapped = (
            played
            if played and not live and not time["sessions"].get(played, {}).get("wrapped")
            else None
        )
        handoff = f"prep/session-{played + 1}/handoff.md"
        return JSONResponse(
            {
                "workspace": str(root),
                "campaign_language": ws.campaign_language,
                "moment": moment,
                "moment_seq": seq,
                "session": live,
                "current_date": time["current_date"],
                "counts": {"entities": entities, "facts": facts, "events": events},
                "open_calls": sum(c["status"] == "open" for c in calls.read_calls(ws)),
                "pending": len(held),
                "unfinished_jobs": len(to_do),  # queued or started
                # The GM's next steps, as `secondchair status` gives them.
                "next": {
                    # play needs a campaign date (CAL-14): set it first
                    "date": None if live or time["current_date"] else command(ws, "date", "<date>"),
                    "unwrapped_session": unwrapped,
                    "wrap": unwrapped and command(ws, "wrap", unwrapped),
                    "jobs": [
                        {
                            "id": j["id"],
                            "status": j["status"],
                            "playbook": j["playbook"],
                            "ask": f'ask your agent: "start SecondChair job {j["id"]}"',
                        }
                        for j in to_do
                    ],
                    "pending_entries": held,
                    "approve": command(ws, "approve", *held) if held else None,
                    "next_session": played + 1,
                    "handoff": handoff if (root / handoff).is_file() else None,
                },
            }
        )

    async def review(_: Request) -> Response:
        log, _seq = _log(ws)
        by_id = {e["id"]: e for e in log}
        open_calls = []
        for call in calls.read_calls(ws):
            if call["status"] != "open":
                continue
            view = {**call, "entry": by_id.get(call["entry"]), "commands": {}}
            if call["kind"] == "discrepancy":  # RUL-24
                view["commands"]["house rule"] = command(
                    ws, "house-rule", "mark", call["id"], "<name>"
                )
            open_calls.append(view)
        pending = [e for e in log if e.get("status") == "pending"]
        return JSONResponse({"pending": pending, "calls": open_calls})

    async def changes(request: Request) -> Response:
        log, _seq = _log(ws)
        tools = sorted({e["tool"] for e in log if e.get("tool")})
        for key in ("moment", "status", "tool"):
            if value := request.query_params.get(key):
                log = [e for e in log if e.get(key) == value]
        try:
            number = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            number = 1
        start = (number - 1) * PAGE_SIZE
        return JSONResponse(
            {
                "entries": log[start : start + PAGE_SIZE],
                "page": number,
                "pages": max(1, -(-len(log) // PAGE_SIZE)),
                "total": len(log),
                "tools": tools,
                "moments": delegation.MOMENTS,
                "statuses": sorted({e["status"] for e in log if e.get("status")}),
            }
        )

    async def prep(_: Request) -> Response:
        readable = [
            str(p.relative_to(root))
            for top in READABLE
            for p in sorted((root / top).rglob("*.md"))
            if _inside(root, p)
        ]
        desired = []
        for kind in DESIRED:
            for p in sorted((root / kind).glob("*.yaml")):
                text = p.read_text()
                report_path = root / STATE_DIR / kind / f"{p.stem}.json"
                report = None
                if report_path.is_file():
                    report = json.loads(report_path.read_text())
                    # pending: the desired state changed since this realisation (ARC-10)
                    digest = report.pop("desired", None)
                    report["pending"] = digest != hashlib.sha256(text.encode()).hexdigest()
                desired.append(
                    {"kind": kind, "key": p.stem, "content": text, **_realised(text, report)}
                )
        return JSONResponse({"files": readable, "desired": desired})

    async def read_file(request: Request) -> Response:
        relative = request.query_params.get("path", "")
        path = (root / relative).resolve()
        if not (path.suffix == ".md" and path.is_file() and _inside(root, path)):
            return JSONResponse({"error": "No such prep or notes file."}, status_code=404)
        return JSONResponse({"path": str(path.relative_to(root)), "text": path.read_text()})

    async def canon(request: Request) -> Response:
        text = request.query_params.get("q", "")
        facts = index.search_facts(ws, text)
        with closing(index.connect(ws)) as conn:
            rows = conn.execute("select fact, knower, mode, date from knowledge").fetchall()
        knowers: dict[str, list[dict]] = {}
        for fact, knower, mode, date in rows:
            knowers.setdefault(fact, []).append({"knower": knower, "mode": mode, "date": date})
        return JSONResponse(
            {
                "entities": index.search_entities(ws, text),
                "facts": [{**f, "knowers": knowers.get(f["id"], [])} for f in facts],
                "events": index.search_events(ws, text),
            }
        )

    async def job_list(_: Request) -> Response:
        return JSONResponse({"jobs": _jobs(ws)[::-1]})

    endpoints: dict[str, Handler] = {
        "overview": overview,
        "review": review,
        "changes": changes,
        "prep": prep,
        "file": read_file,
        "canon": canon,
        "jobs": job_list,
    }
    return [
        _PageRoute("/", _guarded(page), methods=["GET"]),
        *(Route(f"/api/{name}", _guarded(fn), methods=["GET"]) for name, fn in endpoints.items()),
    ]


def _realised(text: str, report: dict | None) -> dict:
    """What the left list says of a desired VTT document: its type, how its last realisation
    went, and how many conflicts and errors it reported."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        data = None
    data = data if isinstance(data, dict) else {}
    kind = "Scene" if "scene" in data else data.get("type")
    if report is None:
        status = "not realised"
    elif report.get("ok") is False:
        status = "failed"
    else:
        status = "pending" if report["pending"] else "realised"
    detail = (report or {}).get("report") or {}
    actions = detail.get("actions") or []
    return {
        "type": kind if isinstance(kind, str) else None,
        "report": report,
        "status": status,
        "conflicts": sum(isinstance(a, dict) and a.get("action") == "conflict" for a in actions),
        "errors": len(detail.get("errors") or []) + bool((report or {}).get("error")),
    }


def _inside(root: Path, path: Path) -> bool:
    """Whether `path`, symlinks resolved, is a file under one of the readable directories."""
    resolved = path.resolve()
    return any(resolved.is_relative_to(root / top) for top in READABLE)
