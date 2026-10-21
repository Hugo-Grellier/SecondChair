import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import jsonschema
import pytest
import yaml
from mcp import Client

from secondchair import cli
from secondchair.cli import main
from secondchair.core import delegation, workspace
from secondchair.core.server import build_server
from secondchair.core.tools import RESPONSIBILITIES
from secondchair.core.workspace import Workspace

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "docs/contracts/action-log-entry.schema.json").read_text()
)
ENTITY = {"names": ["Frère Ezren"], "aliases": ["Ezren"], "description": "Un prêtre voûté."}


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path), "--language", "fr", "--calendar", "absalom"])
    return workspace.load(tmp_path)


def set_level(ws: Workspace, moment: str, responsibility: str, level: str) -> None:
    path = ws.root / delegation.TABLE_FILE
    table = yaml.safe_load(path.read_text())
    table[moment][responsibility]["level"] = level
    path.write_text(yaml.safe_dump(table))


def call(ws: Workspace, tool: str, arguments: dict[str, Any]) -> Any:
    async def run() -> Any:
        async with Client(build_server(ws)) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def create_entity(ws: Workspace) -> Any:
    return call(ws, "create_entity", {**ENTITY, "agent": "claude-prep"})


def entities(ws: Workspace) -> list[Path]:
    return sorted((ws.root / "canon/entities").glob("*.md"))


def log(ws: Workspace) -> list[dict]:
    entries = [yaml.safe_load(p.read_text()) for p in sorted((ws.root / "action-log").glob("*"))]
    for entry in entries:
        jsonschema.validate(entry, SCHEMA)
    return entries


def gm(*argv: str, root: Path, interactive: bool = True) -> int:
    """Run a GM CLI command, at an interactive terminal or not."""
    with patch.object(cli, "interactive", return_value=interactive):
        return main([*argv, "--workspace", str(root)])


def test_a_fresh_table_is_prep_play_prep_with_every_deadline_auto(ws: Workspace) -> None:
    table = yaml.safe_load((ws.root / "delegation.yaml").read_text())
    base = delegation.BASE_PROFILES
    assert table == {
        "prep": base["prep"],
        "live-session": base["play"],
        "between-sessions": base["prep"],
    }
    assert table["prep"]["memory"] == {"level": "act-then-review", "deadline": "auto", "hold": True}
    assert table["live-session"]["rules_and_combat"]["level"] == "act-then-review"
    assert {c["deadline"] for p in base.values() for c in p.values()} == {"auto"}
    assert {c["hold"] for p in base.values() for c in p.values()} == {True}  # DEL-09a
    assert all(base["read"][r]["level"] == "manual" for r in RESPONSIBILITIES)
    assert delegation.current_moment(ws) == ("prep", 1)


def test_at_act_then_review_an_agent_creates_an_entity_and_it_is_logged(ws: Workspace) -> None:
    result = create_entity(ws)

    assert not result.is_error, result
    assert result.structured_content == {"entry": 1, "status": "applied"}
    [path] = entities(ws)
    front = yaml.safe_load(path.read_text().split("---")[1])
    assert front["names"] == ["Frère Ezren"] and front["aliases"] == ["Ezren"]
    [entry] = log(ws)
    assert entry["responsibility"] == "memory"
    assert entry["effective_level"] == "act-then-review"
    assert entry["override_lowered"] is False
    assert entry["agent"] == "claude-prep"
    assert entry["before"] is None and entry["after"] == path.read_text()
    assert entry["target"] == str(path.relative_to(ws.root))
    assert entry["approval"] is None


def test_undo_removes_the_entity_and_logs_a_gm_interaction(ws: Workspace) -> None:
    create_entity(ws)

    assert gm("log", "undo", "1", "--reason", "tone", root=ws.root) == 0

    assert entities(ws) == []
    action, undo = log(ws)
    assert action["status"] == "undone"
    assert undo["kind"] == "gm_interaction"
    assert (undo["interaction"], undo["entry"], undo["reason"]) == ("undo", 1, "tone")
    assert undo["channel"] == "cli" and undo["authenticated"] is True


def test_undo_refuses_a_reason_outside_the_closed_list(ws: Workspace) -> None:
    create_entity(ws)

    with pytest.raises(SystemExit):
        gm("log", "undo", "1", "--reason", "boring", root=ws.root)
    with pytest.raises(delegation.DelegationError, match="boring"):
        delegation.undo(ws, 1, "boring", "cli", True)
    assert len(entities(ws)) == 1


def test_undo_refuses_to_overwrite_a_hand_edit(ws: Workspace) -> None:
    create_entity(ws)
    [path] = entities(ws)
    path.write_text(path.read_text() + "GM note\n")

    assert gm("log", "undo", "1", "--reason", "other", root=ws.root) == 1
    assert path.exists()
    assert len(log(ws)) == 1


def test_the_gm_approves_several_pending_actions_in_one_command(ws: Workspace) -> None:
    set_level(ws, "prep", "memory", "propose")
    create_entity(ws)
    call(ws, "create_entity", {**ENTITY, "names": ["Other"], "agent": "claude-prep"})

    assert gm("approve", "1", "2", root=ws.root) == 0
    assert len(entities(ws)) == 2


def test_at_propose_the_entity_appears_only_after_cli_approval(ws: Workspace) -> None:
    set_level(ws, "prep", "memory", "propose")

    assert create_entity(ws).structured_content == {"entry": 1, "status": "pending"}
    assert entities(ws) == []

    assert gm("approve", "1", root=ws.root) == 0
    assert len(entities(ws)) == 1
    action, approval = log(ws)
    assert action["status"] == "applied"
    assert action["approval"] == {
        "channel": "cli",
        "authenticated": True,
        "quote": None,
        "interaction": 2,
    }
    assert approval["interaction"] == "approve"


def test_at_propose_an_agent_relays_the_gm_approval_with_quoted_words(ws: Workspace) -> None:
    set_level(ws, "prep", "memory", "propose")
    create_entity(ws)

    refused = call(ws, "approve_proposal", {"entry": 1, "gm_words": " "})
    assert refused.is_error and entities(ws) == []

    result = call(ws, "approve_proposal", {"entry": 1, "gm_words": "Oui, garde-le."})
    assert result.structured_content == {"entry": 1, "status": "applied"}
    assert len(entities(ws)) == 1
    action, approval = log(ws)
    assert action["approval"]["channel"] == "via agent"
    assert action["approval"]["quote"] == "Oui, garde-le."
    assert (approval["channel"], approval["authenticated"]) == ("via agent", False)


def test_a_rejected_proposal_writes_nothing(ws: Workspace) -> None:
    set_level(ws, "prep", "memory", "propose")
    create_entity(ws)

    assert gm("reject", "1", "--reason", "contradiction", root=ws.root) == 0
    assert gm("approve", "1", root=ws.root) == 1
    assert entities(ws) == []
    assert [e.get("status", e.get("reason")) for e in log(ws)] == ["rejected", "contradiction"]


def test_at_manual_the_action_is_refused_and_nothing_is_written(ws: Workspace) -> None:
    set_level(ws, "prep", "memory", "manual")

    result = create_entity(ws)

    assert result.is_error
    assert "manual" in result.content[0].text
    assert entities(ws) == []
    assert not (ws.root / "action-log").exists()


def test_an_irreversible_action_is_held_at_propose(ws: Workspace) -> None:
    assert delegation.effective_level(ws, "disclosure", "prep", reversible=False) == "propose"
    set_level(ws, "prep", "disclosure", "autonomous")
    assert delegation.effective_level(ws, "disclosure", "prep", reversible=False) == "propose"
    assert delegation.effective_level(ws, "disclosure", "prep", reversible=True) == "autonomous"


def test_changing_the_moment_needs_an_interactive_terminal(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gm("moment", "between-sessions", root=ws.root, interactive=False) == 1
    assert "interactive terminal" in capsys.readouterr().err
    assert delegation.current_moment(ws) == ("prep", 1)

    assert gm("moment", "between-sessions", root=ws.root) == 0
    assert gm("moment", "prep", root=ws.root, interactive=False) == 1
    assert delegation.current_moment(ws) == ("between-sessions", 2)


def test_after_a_moment_change_the_previous_log_is_frozen(ws: Workspace) -> None:
    create_entity(ws)
    gm("moment", "between-sessions", root=ws.root)
    gm("moment", "prep", root=ws.root)

    assert gm("log", "undo", "1", "--reason", "tone", root=ws.root) == 1
    assert len(entities(ws)) == 1
    assert log(ws)[0]["status"] == "applied"


def test_a_live_session_must_end_before_prep_opens(ws: Workspace) -> None:
    assert gm("moment", "live-session", root=ws.root) == 0
    assert gm("moment", "prep", root=ws.root) == 1
    assert gm("moment", "between-sessions", root=ws.root) == 0
    assert gm("moment", "prep", root=ws.root) == 0


def test_moment_from_a_non_interactive_process_is_refused(ws: Workspace) -> None:
    run = subprocess.run(
        [sys.executable, "-m", "secondchair.cli", "moment", "prep", "-w", str(ws.root)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1
    assert "interactive terminal" in run.stderr


def test_create_entity_asks_the_agent_for_its_name(ws: Workspace) -> None:
    async def list_tools() -> Any:
        async with Client(build_server(ws)) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(list_tools())}
    schema = tools["create_entity"].input_schema
    assert set(schema["required"]) == {"names", "agent"}
    assert "aliases" in schema["properties"]
    assert tools["approve_proposal"].meta == {"secondchair/gm_interaction": True}


@pytest.mark.parametrize(
    "target",
    [
        "delegation.yaml",
        "moment.yaml",
        "action-log/000009.yaml",
        "observations/000001.jsonl",
        "capture/k1.yaml",
        "time.yaml",
        "house-rules.yaml",
        "library.yaml",
        "foundry.yaml",
        "sources/s-1a2b3c4d.yaml",
        "speakers.yaml",
        ".agents/skills/campaign-workshop/SKILL.md",
        ".claude/skills/campaign-workshop/SKILL.md",
        ".secondchair-skills.json",
        ".git/hooks/pre-commit",
        ".gitignore",
    ],
)
def test_a_delegated_action_cannot_write_the_core_files(ws: Workspace, target: str) -> None:
    with pytest.raises(delegation.DelegationError, match="belongs to the Core"):
        delegation._target(ws, target)


def test_the_core_paths_name_what_their_owners_write() -> None:
    """The literals other Core modules own (CORE_PATHS) stay their constants."""
    from secondchair import transcribe
    from secondchair.core import campaign_skill, capture, library, rules
    from secondchair_foundry import bridge

    for owned in (
        capture.CAPTURE_DIR,
        capture.TIME_FILE,
        rules.HOUSE_RULES_FILE,
        library.REFERENCE_FILE,
        bridge.BINDING_FILE,
        transcribe.SOURCES_DIR,
        transcribe.SPEAKERS_FILE,
        campaign_skill.MANIFEST,
    ):
        assert owned in delegation.CORE_PATHS, owned


def _key(ws: Workspace, directory: str) -> str:
    return str((ws.root / directory).resolve())


def test_next_id_stays_monotonic_unique_across_holds_and_recovery(ws: Workspace) -> None:
    with delegation.locked(ws):
        ids = [delegation._append(ws, {"kind": "t"})["id"] for _ in range(30)]
        assert ids == list(range(1, 31))
        delegation._save(ws, {"id": 99, "kind": "t"})  # a write the cache did not make
        assert delegation._append(ws, {"kind": "t"})["id"] == 100
        delegation._save(ws, {"id": 7, "kind": "t"})  # a lower id cannot rewind the cache
        assert delegation._append(ws, {"kind": "t"})["id"] == 101
    delegation._log_path(ws, 150).write_text("id: 150\n")  # another process, between holds
    with delegation.locked(ws):  # the first acquisition recovers
        assert delegation._append(ws, {"kind": "t"})["id"] == 151


def test_next_id_outside_a_hold_is_never_cached(ws: Workspace) -> None:
    assert delegation._next_id(ws, delegation.LOG_DIR) == 1
    delegation._log_path(ws, 5).parent.mkdir(exist_ok=True)
    delegation._log_path(ws, 5).write_text("id: 5\n")  # another writer
    with delegation.locked(ws):
        assert delegation._next_id(ws, delegation.LOG_DIR) == 6


def test_a_record_made_by_hand_during_a_hold_is_never_overwritten(ws: Workspace) -> None:
    with delegation.locked(ws):
        assert delegation._append(ws, {"kind": "t"})["id"] == 1
        delegation._log_path(ws, 2).write_text("id: 2\nhand: true\n")
        with pytest.raises(delegation.DelegationError):
            delegation._append(ws, {"kind": "t"})
    assert "hand" in delegation._log_path(ws, 2).read_text()


def test_the_cache_does_not_survive_an_exception_in_a_hold(ws: Workspace) -> None:
    with pytest.raises(RuntimeError), delegation.locked(ws):
        delegation._append(ws, {"kind": "t"})
        raise RuntimeError
    assert delegation._FILE_IDS == {}
    delegation._log_path(ws, 9).write_text("id: 9\n")
    with delegation.locked(ws):
        assert delegation._next_id(ws, delegation.LOG_DIR) == 10


def test_another_directory_has_its_own_ids(ws: Workspace) -> None:
    with delegation.locked(ws):
        assert [delegation._append(ws, {"k": 1}, delegation.JOBS_DIR)["id"] for _ in range(3)] == [
            1,
            2,
            3,
        ]
        assert delegation._append(ws, {"kind": "t"})["id"] == 1
        assert delegation._next_id(ws, delegation.JOBS_DIR) == 4


def test_undo_through_apply_drops_the_cached_directory(ws: Workspace) -> None:
    create_entity(ws)
    [path] = entities(ws)
    with delegation.locked(ws):
        delegation._next_id(ws, str(path.parent.relative_to(ws.root)))  # primes the cache
        assert _key(ws, str(path.parent.relative_to(ws.root))) in delegation._FILE_IDS
        delegation.undo(ws, 1, "tone", "cli", True)  # _apply unlinks the entity file
        assert _key(ws, str(path.parent.relative_to(ws.root))) not in delegation._FILE_IDS


def test_a_journal_removal_drops_the_cached_directory(ws: Workspace) -> None:
    from secondchair.core import journal

    with delegation.locked(ws):
        delegation._append(ws, {"kind": "t"})
        assert _key(ws, delegation.LOG_DIR) in delegation._FILE_IDS
        journal._put(delegation._log_path(ws, 1), None)
        assert _key(ws, delegation.LOG_DIR) not in delegation._FILE_IDS
        assert delegation._append(ws, {"kind": "t"})["id"] == 1
