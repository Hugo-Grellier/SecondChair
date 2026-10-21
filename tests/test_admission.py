"""Admission (ADR 0015, #168): a rank above agent_proposal only on evidence the Core resolves.
Forged evidence is refused, never demoted; legitimate observations, job Sources and indexed
library pages keep their ranks; `secondchair doctor` reports evidence that stopped resolving."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from mcp import Client

from secondchair import cli
from secondchair.cli import main
from secondchair.core import index, jobs, library, observations, workspace
from secondchair.core.server import build_server
from secondchair.core.workspace import Workspace

QUOTE = "The bell rang at noon."
CITED = "no such page and excerpt that a model may read"  # one refusal for every case


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path / "camp"), "--language", "en", "--calendar", "absalom"])
    ws = workspace.load(tmp_path / "camp")
    envelope = {"id": "o1", "session": None, "at": "2026-10-19T20:15:00+00:00", "scene": None}
    envelope |= {"actor": None, "kind": "chat", "visibility": "players"}
    assert observations.record(ws, envelope | {"payload": {"text": QUOTE, "rolls": []}}) is None
    return ws


def call(ws: Workspace, **arguments: Any) -> Any:
    async def run() -> Any:
        async with Client(build_server(ws)) as client:
            return await client.call_tool("record_fact", {"agent": "a", "entities": []} | arguments)

    return asyncio.run(run())


def rank(ws: Workspace, statement: str, origin: dict, **more: Any) -> str:
    result = call(ws, statement=statement, origin=origin, **more)
    assert not result.is_error, result
    [found] = index.search_facts(ws, text=statement)
    return found["rank"]


def refused(ws: Workspace, origin: dict, **more: Any) -> str:
    result = call(ws, statement="Forged.", origin=origin, **more)
    assert result.is_error
    assert not index.search_facts(ws, text="Forged")  # refused, never demoted
    return result.content[0].text


def seen(locator: str, quote: str = QUOTE) -> dict[str, str]:
    return {"kind": "observation", "quote": quote, "locator": locator}


def job_with(ws: Workspace, notes: Path) -> int:
    job = jobs.queue(
        ws,
        playbook="wrap-a-session",
        inputs={"session": "1", "notes": str(notes)},
        expected_output="",
        responsibility="memory",
        tier="standard",
    )["id"]
    jobs.start(ws, job, {"host": "h", "model": "m", "effort": "e"}, manual=True)
    return job


def test_a_quoted_observation_ranks_played_and_a_forged_one_is_refused(ws: Workspace) -> None:
    assert rank(ws, "The bell rang.", seen("observations/outside-sessions.jsonl#o1")) == "played"

    assert "no observation" in refused(ws, seen("observations/outside-sessions.jsonl#nope"))
    assert "quote is not in the observation" in refused(
        ws, seen("observations/outside-sessions.jsonl#o1", "The bell never rang.")
    )
    # A trivial quote, or one matching inside longer words, forges nothing.
    for trivial in ("e", "The bell"):
        assert "at least 3 words" in refused(
            ws, seen("observations/outside-sessions.jsonl#o1", trivial)
        )
    assert "quote is not in" in refused(
        ws, seen("observations/outside-sessions.jsonl#o1", "he bell rang")
    )


def test_a_file_locator_resolves_only_in_the_sources_of_the_job(
    ws: Workspace, tmp_path: Path
) -> None:
    notes = tmp_path / "s1.md"
    notes.write_text("# Session 1\n\nMira joined the Lock Council.\n")
    quote = seen("s1.md:3", "Mira joined the Lock Council.")

    error = refused(ws, quote)  # outside a job, there are no Sources
    assert "not at s1.md:3" in error and "job origin" in error
    job = job_with(ws, notes)
    assert "not at s1.md:2" in refused(ws, seen("s1.md:2", quote["quote"]), job=job)
    assert "not at" in refused(ws, seen("other.md:3", quote["quote"]), job=job)
    assert "at least 3 words" in refused(ws, seen("s1.md:3", "M"), job=job)
    assert "not at" in refused(ws, seen("s1.md:3", "ira joined the"), job=job)

    assert rank(ws, "Mira is on the Council.", quote, job=job) == "played"


def test_an_action_log_locator_and_a_rule_origin_are_the_cores_own(ws: Workspace) -> None:
    disclosure = seen("action-log/000001.yaml", "show_journal Journal.j1")
    assert "action log entry" in refused(ws, disclosure)
    assert "world-turn" in refused(ws, {"kind": "rule", "fact": "f-1", "key": "k"})


def test_a_source_origin_needs_an_indexed_page_and_its_excerpt(
    ws: Workspace, index_source: Any
) -> None:
    index_source(ws, "Locks open at dusk.\nBells ring at noon.", name="rules.txt")
    index_source(ws, "Not indexed yet.", name="shelf.txt", indexed=False)
    index_source(ws, "Indexed for the GM only.", name="private.txt", model=False)
    cite = {"kind": "source", "source": "rules.txt", "page": "1"}

    # Unknown, unindexed, not permitted to models, no such page, no such excerpt: one refusal,
    # so an agent learns nothing of a Source's text it may not read (no page oracle).
    for source in ("unknown.txt", "shelf.txt", "private.txt"):
        assert CITED in refused(ws, cite | {"source": source})
    assert CITED in refused(ws, cite | {"page": "2"})
    assert CITED in refused(ws, cite | {"excerpt": "Locks never open."})
    assert CITED in refused(ws, cite | {"excerpt": "at"})  # a trivial excerpt confirms nothing

    assert rank(ws, "Locks open at dusk.", cite | {"excerpt": "Locks  open at\ndusk."}) == (
        "cited_source"
    )
    # A job origin may carry the shelf's page as evidence: it ranks agent_proposal (#167).
    shelf = {"kind": "job", "job": "rebuild", "source": "shelf.txt", "page": "1"}
    assert rank(ws, "Shelved.", shelf) == "agent_proposal"


def test_evidence_changed_after_admission_stands_and_doctor_reports_it(
    ws: Workspace, index_source: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = index_source(ws, "Bells ring at noon.", name="rules.txt")
    cite = {"kind": "source", "source": "rules.txt", "page": "1", "excerpt": "Bells ring at"}
    assert rank(ws, "Bells ring at noon.", cite) == "cited_source"
    assert main(["doctor", "-w", str(ws.root)]) == 0

    (tmp_path / "library/rules.txt").write_text("Bells are silent.")
    library.build_index(ws, source, replace_changed=True, authenticated=True)

    assert main(["doctor", "-w", str(ws.root)]) == 1
    assert CITED in capsys.readouterr().err
    index.rebuild(ws)  # rebuilding does not check again: the rank stands
    assert index.search_facts(ws, text="Bells")[0]["rank"] == "cited_source"


def test_a_hand_edit_declaring_an_observation_ranks_agent_proposal_until_promoted(
    ws: Workspace,
) -> None:
    front: dict[str, Any] = {"id": "f-hand", "entities": [], "relation": None, "valid_from": None}
    front |= {"valid_to": None, "rank": "played", "origin": seen("s9.md:1", "anything")}
    (ws.root / "canon/facts").mkdir(parents=True, exist_ok=True)
    (ws.root / "canon/facts/f-hand.md").write_text(index.join_doc(front, "Typed by hand."))

    [fact] = index.search_facts(ws, text="hand")
    assert fact["rank"] == "agent_proposal"  # CAN-11: whatever its front matter declares
    assert main(["doctor", "-w", str(ws.root)]) == 0  # it gained no rank to report
    with patch.object(cli, "interactive", return_value=True):
        assert main(["promote", str(fact["admitted_by"]), "-w", str(ws.root)]) == 0
    assert index.search_facts(ws, text="hand")[0]["rank"] == "gm_decision"
