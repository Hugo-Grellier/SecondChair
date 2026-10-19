"""Facts, events, ranks and the derived index (CAN-01, CAN-03..08, CAN-10, CAN-12), through the
Core's MCP tools and the CLI, as an agent and the GM reach them."""

import asyncio
import json
import shutil
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
from secondchair.core import workspace
from secondchair.core.server import build_server
from secondchair.core.workspace import Workspace

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "docs/contracts/action-log-entry.schema.json").read_text()
)
SEEN = {"kind": "observation", "quote": "Mira joined the Lock Council.", "locator": "s1.md:3"}
JOB = {"kind": "job", "job": "s0-rebuild"}
GM_WORDS = {"kind": "gm", "words": "Actually Sella opened it, not the party."}


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path / "camp"), "--language", "en", "--calendar", "absalom"])
    return workspace.load(tmp_path / "camp")


def call(ws: Workspace, tool: str, **arguments: Any) -> Any:
    async def run() -> Any:
        async with Client(build_server(ws)) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def act(ws: Workspace, tool: str, **arguments: Any) -> dict:
    result = call(ws, tool, agent="claude-prep", **arguments)
    assert not result.is_error, result
    return result.structured_content


def read(ws: Workspace, tool: str, **arguments: Any) -> list[dict]:
    result = call(ws, tool, **arguments)
    assert not result.is_error, result
    return result.structured_content["result"]


def refused(ws: Workspace, tool: str, **arguments: Any) -> str:
    result = call(ws, tool, agent="claude-prep", **arguments)
    assert result.is_error
    return result.content[0].text


def entity(ws: Workspace, name: str) -> str:
    act(ws, "create_entity", names=[name])
    [found] = [e for e in read(ws, "search_entities", text=name) if e["names"] == [name]]
    return found["id"]


def fact(ws: Workspace, statement: str, **fields: Any) -> str:
    act(ws, "record_fact", statement=statement, **{"origin": JOB, "entities": [], **fields})
    [found] = read(ws, "search_facts", text=statement, include_retconned=True)
    return found["id"]


def confirm(doc: str, ws: Workspace, interactive: bool = True) -> int:
    """`secondchair confirm`, at an interactive terminal or not."""
    with patch.object(cli, "interactive", return_value=interactive):
        return main(["confirm", doc, "-w", str(ws.root)])


def log(ws: Workspace) -> list[dict]:
    entries = [yaml.safe_load(p.read_text()) for p in sorted((ws.root / "action-log").glob("*"))]
    for e in entries:
        jsonschema.validate(e, SCHEMA)
    return entries


def test_a_fact_is_markdown_with_relation_validity_rank_and_provenance(ws: Workspace) -> None:
    mira, council = entity(ws, "Mira Pell"), entity(ws, "Lock Council")

    act(
        ws,
        "record_fact",
        statement="Mira Pell sits on the Lock Council.",
        entities=[mira],
        relation={"type": "member_of", "subject": mira, "object": council},
        valid_from="4725-03",
        origin=SEEN,
    )

    [path] = (ws.root / "canon/facts").glob("f-*.md")
    front, body = path.read_text().split("---\n")[1:]
    front = yaml.safe_load(front)
    assert body == "Mira Pell sits on the Lock Council.\n"
    assert front["entities"] == [mira, council]
    assert front["relation"] == {"type": "member_of", "subject": mira, "object": council}
    assert (front["valid_from"], front["valid_to"]) == ("4725-03", None)
    assert front["rank"] == "played" and front["origin"] == SEEN
    [found] = read(ws, "search_facts", entity=council)
    assert found["id"] == front["id"] == path.stem
    assert found["admitted_by"] == log(ws)[-1]["id"]
    assert found["rank"] == "played"


def test_ranks_come_from_the_origin_and_an_agent_never_reaches_gm_decision(ws: Workspace) -> None:
    cited = {"kind": "source", "source": "Core Rulebook", "page": "12"}
    for origin, rank in ((cited, "cited_source"), (JOB, "agent_proposal")):
        fid = fact(ws, f"A {rank} fact.", origin=origin)
        assert read(ws, "search_facts", text=f"A {rank} fact.")[0]["rank"] == rank, fid
    fact(ws, "The GM said so.", origin=GM_WORDS)
    assert read(ws, "search_facts", text="GM said")[0]["rank"] == "agent_proposal"
    assert "quote" in refused(
        ws, "record_fact", statement="x", entities=[], origin={"kind": "observation"}
    )


def test_an_approved_agent_proposal_keeps_the_agent_proposal_rank(ws: Workspace) -> None:
    table = ws.root / "delegation.yaml"
    data = yaml.safe_load(table.read_text())
    data["prep"]["memory"]["level"] = "propose"
    table.write_text(yaml.safe_dump(data))
    pending = act(ws, "record_fact", statement="The ferry rope is frayed.", entities=[], origin=JOB)
    assert pending["status"] == "pending"

    assert act(ws, "approve_proposal", entry=pending["entry"], gm_words="ok") is not None
    [found] = read(ws, "search_facts", text="ferry rope")
    assert found["rank"] == "agent_proposal"


def test_the_gm_confirms_a_relayed_decision_in_one_gesture_at_a_terminal(ws: Workspace) -> None:
    decided = fact(ws, "Sella holds the bypass key.", origin=GM_WORDS)
    [relayed] = read(ws, "search_facts", text="bypass key")
    assert relayed["rank"] == "agent_proposal"

    assert confirm(decided, ws, interactive=False) == 1  # DEL-29: an authenticated Surface only
    assert read(ws, "search_facts", text="bypass key")[0]["rank"] == "agent_proposal"

    assert confirm(decided, ws) == 0
    [found] = read(ws, "search_facts", text="bypass key")
    *_, entry = log(ws)
    assert found["rank"] == "gm_decision" and found["origin"] == GM_WORDS
    assert entry["kind"] == "gm_interaction" and entry["interaction"] == "confirm"
    assert entry["authenticated"] and entry["entry"] == relayed["admitted_by"]
    assert entry["target"] == f"canon/facts/{decided}.md"
    assert "agent_proposal" in entry["before"] and "gm_decision" in entry["after"]
    assert found["admitted_by"] == entry["id"]
    assert confirm(decided, ws) == 1  # already a decision

    # An agent relaying the GM's words again cannot override the decision it now is.
    assert "gm_decision" in refused(
        ws, "correct_fact", fact=decided, statement="Edda holds it.", entities=[], origin=GM_WORDS
    )


def test_only_the_gms_words_can_be_confirmed(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    job = fact(ws, "The rope is frayed.", origin=JOB)
    played = fact(ws, "Edda paid 12 silver.", origin=SEEN)
    for doc in (job, played, "f-00000000"):
        assert confirm(doc, ws) == 1
    assert "GM's words" in capsys.readouterr().err
    ranks = {f["id"]: f["rank"] for f in read(ws, "search_facts")}
    assert ranks == {job: "agent_proposal", played: "played"}


def test_confirm_from_a_non_interactive_process_is_refused(ws: Workspace) -> None:
    decided = fact(ws, "Sella holds the bypass key.", origin=GM_WORDS)
    run = subprocess.run(
        [sys.executable, "-m", "secondchair.cli", "confirm", decided, "-w", str(ws.root)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1 and "interactive terminal" in run.stderr
    assert read(ws, "search_facts", text="bypass key")[0]["rank"] == "agent_proposal"


def test_a_relation_outside_the_core_list_is_refused_unless_an_extension_registers_it(
    ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = entity(ws, "Ada Fen"), entity(ws, "Beren Pike")
    worships = {"type": "worships", "subject": a, "object": b}

    assert "worships" in refused(
        ws,
        "record_fact",
        statement="Ada worships Beren.",
        entities=[],
        relation=worships,
        origin=JOB,
    )

    site = tmp_path / "site"
    dist = site / "relext-0.1.dist-info"
    dist.mkdir(parents=True)
    (site / "relext.py").write_text("RELATIONS = ['worships']\n")
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: relext\nVersion: 0.1\n")
    (dist / "entry_points.txt").write_text("[secondchair.relations]\nrelext = relext:RELATIONS\n")
    monkeypatch.setattr(sys, "path", [str(site), *sys.path])

    act(
        ws,
        "record_fact",
        statement="Ada worships Beren.",
        entities=[],
        relation=worships,
        origin=JOB,
    )
    assert read(ws, "search_facts", relation="worships")[0]["entities"] == [a, b]


def test_an_evolution_closes_the_old_fact_and_opens_the_new_one(ws: Workspace) -> None:
    closed = fact(ws, "The bypass is closed.", valid_from="4725-01-01", origin=SEEN)
    opened = fact(ws, "The bypass is open.", origin=SEEN)

    act(
        ws,
        "record_event",
        description="The party opened the bypass.",
        date="4725-05-01",
        kind="played",
        opens=[opened],
        closes=[closed],
        origin=SEEN,
    )

    def at(date: str) -> list[str]:
        return [f["statement"] for f in read(ws, "search_facts", text="bypass", at=date)]

    assert at("4725-04-30") == ["The bypass is closed."]
    assert at("4725-05-01") == ["The bypass is open."]  # start-inclusive, end-exclusive
    [ended] = read(ws, "search_facts", text="closed")
    assert (ended["valid_from"], ended["valid_to"]) == ("4725-01-01", "4725-05-01")
    [event] = read(ws, "search_events", fact=closed)
    assert event["closes"] == [closed] and event["rank"] == "played"


def test_a_retcon_keeps_the_earlier_event_on_record(ws: Workspace) -> None:
    party = fact(ws, "The party opened the bypass.", origin=SEEN)
    act(
        ws,
        "record_event",
        description="Bypass opened.",
        date="4725-05-01",
        kind="played",
        opens=[party],
        origin=SEEN,
    )
    [played] = read(ws, "search_events", fact=party)
    sella = fact(ws, "Sella opened the bypass.", origin=GM_WORDS)

    assert "GM" in refused(
        ws,
        "record_event",
        description="Sella did it.",
        date="4725-05-01",
        opens=[sella],
        replaces=played["id"],
        origin=JOB,
    )
    act(
        ws,
        "record_event",
        description="Sella did it.",
        date="4725-05-01",
        opens=[sella],
        replaces=played["id"],
        origin=GM_WORDS,
    )

    # Relayed by an agent the retcon is an agent proposal: on record, not yet in effect (#38).
    events = {e["id"]: e for e in read(ws, "search_events", text="")}
    retcon = next(e for e in events.values() if e["replaces"] == played["id"])
    assert retcon["status"] == "pending_retcon" and events[played["id"]]["status"] == "canon"

    # Once the GM confirms it as a decision, it replaces the played event, which stays on record.
    assert confirm(retcon["id"], ws) == 0
    events = {e["id"]: e for e in read(ws, "search_events", text="")}
    assert events[played["id"]]["status"] == "replaced"
    assert events[played["id"]]["replaced_by"] == retcon["id"]
    assert (ws.root / "canon/events" / f"{played['id']}.md").exists()
    assert [f["id"] for f in read(ws, "search_facts", text="opened the bypass")] == [sella]
    history = read(ws, "search_facts", text="opened the bypass", include_retconned=True)
    assert {f["id"]: f["status"] for f in history} == {party: "retconned", sella: "canon"}


def test_a_correction_contradicting_a_played_fact_is_refused_and_logged(ws: Workspace) -> None:
    played = fact(ws, "Edda paid 12 silver.", origin=SEEN)
    proposed = fact(ws, "Edda paid 21 silver.", origin=JOB)

    message = refused(
        ws, "correct_fact", fact=played, statement="Edda paid 10 silver.", entities=[], origin=JOB
    )
    assert "played" in message
    assert read(ws, "search_facts", text="Edda paid 12")[0]["statement"] == "Edda paid 12 silver."
    *_, entry = log(ws)
    assert entry["status"] == "refused" and "played" in entry["refusal"]

    act(
        ws, "correct_fact", fact=proposed, statement="Edda paid 20 silver.", entities=[], origin=JOB
    )
    [corrected] = read(ws, "search_facts", text="Edda paid 20")
    assert corrected["id"] == proposed
    assert read(ws, "search_events", fact=proposed) == []  # a correction is not an event
    assert "21 silver" in log(ws)[-1]["before"]  # nothing is deleted


def test_full_text_and_structured_search(ws: Workspace) -> None:
    tovan = entity(ws, "Tovan Reed")
    fact(ws, "Tovan believes the Circle rings false warnings.", entities=[tovan])
    fact(ws, "The weir gauge stayed at zero.")

    assert [f["statement"] for f in read(ws, "search_facts", text="false warnings")] == [
        "Tovan believes the Circle rings false warnings."
    ]
    assert len(read(ws, "search_facts", entity=tovan)) == 1
    assert len(read(ws, "search_facts")) == 2
    assert read(ws, "search_facts", text='"unbalanced (quote') == []


def test_deleting_the_derived_index_and_running_check_gives_identical_results(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mira, council = entity(ws, "Mira Pell"), entity(ws, "Lock Council")
    old = fact(
        ws,
        "Mira sits on the Lock Council.",
        entities=[mira],
        relation={"type": "member_of", "subject": mira, "object": council},
        origin=SEEN,
    )
    act(ws, "record_event", description="Mira resigns.", date="4725-06", closes=[old], origin=SEEN)

    def snapshot() -> list:
        return [
            read(ws, tool, **args)
            for tool, args in (
                ("search_entities", {}),
                ("search_facts", {"include_retconned": True}),
                ("search_facts", {"text": "Lock Council", "at": "4725-05-30"}),
                ("search_events", {}),
            )
        ]

    before = snapshot()
    shutil.rmtree(ws.root / ".secondchair")
    monkeypatch.chdir(ws.root)

    assert main(["check"]) == 0
    assert "2 entities, 1 facts, 1 events" in capsys.readouterr().out
    assert snapshot() == before


def test_check_names_an_invalid_canon_file(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    (ws.root / "canon/facts").mkdir(parents=True)
    (ws.root / "canon/facts/f-broken.md").write_text("---\nid: f-broken\nrank: royal\n---\nx\n")

    assert main(["check", "-w", str(ws.root)]) == 1
    assert "f-broken.md" in capsys.readouterr().err
