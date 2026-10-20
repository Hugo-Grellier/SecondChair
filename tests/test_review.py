"""The read-only review and prep view `serve` shows (ARC-11, ARC-13)."""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp import Client
from starlette.applications import Starlette
from starlette.testclient import TestClient

from secondchair import review
from secondchair.cli import main
from secondchair.core import delegation, workspace
from secondchair.core.server import build_server
from secondchair.core.workspace import Workspace

BASE = "http://127.0.0.1:7240"
ENTITY = {"names": ["Frère Ezren"], "aliases": ["Ezren"], "description": "Un prêtre voûté."}


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    root = tmp_path / "campaign"
    main(["init", str(root), "--language", "fr", "--calendar", "absalom"])
    return workspace.load(root)


@pytest.fixture
def client(ws: Workspace) -> TestClient:
    return TestClient(Starlette(routes=review.routes(ws)), base_url=BASE)


def call(ws: Workspace, tool: str, arguments: dict[str, Any]) -> Any:
    async def run() -> Any:
        async with Client(build_server(ws)) as c:
            return await c.call_tool(tool, arguments)

    return asyncio.run(run())


def propose_entity(ws: Workspace) -> None:
    path = ws.root / delegation.TABLE_FILE
    table = yaml.safe_load(path.read_text())
    table["prep"]["memory"]["level"] = "propose"
    path.write_text(yaml.safe_dump(table))
    call(ws, "create_entity", {**ENTITY, "agent": "claude-prep"})


def test_a_pending_entry_shows_its_diff_and_the_approve_command(
    ws: Workspace, client: TestClient
) -> None:
    propose_entity(ws)
    found = client.get("/api/review").json()
    (entry,) = found["pending"]
    assert entry["tool"] == "create_entity" and entry["agent"] == "claude-prep"
    assert any(line.startswith("+") and "Frère Ezren" in line for line in entry["diff"])
    root = str(ws.root.resolve())
    assert entry["commands"]["approve"] == f"secondchair approve {entry['id']} -w {root}"
    assert "--reason" in entry["commands"]["reject"]
    (open_call,) = found["calls"]
    assert open_call["entry"]["id"] == entry["id"]

    overview = client.get("/api/overview").json()
    assert overview["pending"] == 1 and overview["open_calls"] == 1
    assert overview["moment"] == "prep" and overview["campaign_language"] == "fr"


def test_an_applied_reversible_entry_shows_its_undo_command(
    ws: Workspace, client: TestClient
) -> None:
    call(ws, "create_entity", {**ENTITY, "agent": "claude-prep"})  # act-then-review in prep
    found = client.get("/api/changes", params={"status": "applied"}).json()
    (entry,) = found["entries"]
    assert entry["commands"] == {
        "undo": f"secondchair log undo {entry['id']} --reason '<reason>' -w {ws.root.resolve()}"
    }
    assert found["tools"] == ["create_entity"]
    assert client.get("/api/changes", params={"tool": "other"}).json()["entries"] == []
    assert client.get("/api/canon", params={"q": "Ezren"}).json()["entities"][0]["names"] == [
        "Frère Ezren"
    ]


def test_prep_lists_markdown_and_desired_state_with_its_report(
    ws: Workspace, client: TestClient
) -> None:
    (ws.root / "prep/session-1").mkdir(parents=True)
    (ws.root / "prep/session-1/handoff.md").write_text("# Séance 1\n")
    (ws.root / "notes/workshop").mkdir(parents=True)
    (ws.root / "notes/workshop/idea.md").write_text("idée")
    (ws.root / "notes/secret.txt").write_text("not markdown")
    (ws.root / "scenes").mkdir()
    desired = "scene: {name: Cave}\n"
    (ws.root / "scenes/cave.yaml").write_text(desired)
    (ws.root / ".secondchair/scenes").mkdir(parents=True)
    report = {"desired": hashlib.sha256(desired.encode()).hexdigest(), "ok": True}
    (ws.root / ".secondchair/scenes/cave.json").write_text(json.dumps(report))

    found = client.get("/api/prep").json()
    assert found["files"] == ["prep/session-1/handoff.md", "notes/workshop/idea.md"]
    assert found["desired"][0]["report"] == {"ok": True, "pending": False}
    text = client.get("/api/file", params={"path": "prep/session-1/handoff.md"}).json()["text"]
    assert text == "# Séance 1\n"


@pytest.mark.parametrize(
    "path",
    [
        "../outside.md",
        "prep/../../outside.md",
        "workspace.yaml",
        "notes/secret.txt",
        "prep/link.md",
    ],
)
def test_no_file_outside_prep_and_notes_is_served(
    ws: Workspace, client: TestClient, path: str
) -> None:
    (ws.root.parent / "outside.md").write_text("secret")
    (ws.root / "notes").mkdir()
    (ws.root / "notes/secret.txt").write_text("secret")
    (ws.root / "prep").mkdir()
    (ws.root / "prep/link.md").symlink_to(ws.root.parent / "outside.md")
    assert client.get("/api/file", params={"path": path}).status_code == 404
    assert "prep/link.md" not in client.get("/api/prep").json()["files"]


def test_a_foreign_host_header_is_refused(client: TestClient) -> None:
    refused = client.get("/api/overview", headers={"Host": "attacker.example:7240"})
    assert refused.status_code == 421
    assert "access-control-allow-origin" not in refused.headers
    assert client.get("/api/overview", headers={"Host": "localhost:7240"}).status_code == 200


def test_the_page_is_for_browsers_and_get_only(client: TestClient) -> None:
    page = client.get("/", headers={"Accept": "text/html"})
    assert page.status_code == 200 and "not an authenticated Surface" in page.text
    assert client.get("/", headers={"Accept": "application/json"}).status_code == 404
    assert client.post("/api/overview").status_code == 405


@pytest.mark.parametrize("endpoint", ["overview", "review", "changes", "prep", "canon", "jobs"])
def test_every_endpoint_answers_on_a_fresh_workspace(client: TestClient, endpoint: str) -> None:
    assert client.get(f"/api/{endpoint}").status_code == 200
