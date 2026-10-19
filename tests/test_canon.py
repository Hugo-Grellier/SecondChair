"""Facts, events, ranks and the derived index (CAN-01, CAN-03..08, CAN-10..12), check and
upgrade (PKG-15, PKG-16), through the Core's MCP tools and the CLI, as an agent and the GM
reach them."""

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


def test_an_official_reference_stores_the_english_key_and_the_pack_only_on_collision(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    act(ws, "create_entity", names=["Gobelin guerrier"], official_reference={"key": "goblin"})
    act(
        ws,
        "create_entity",
        names=["Gobelin guerrier"],
        aliases=["Grak"],
        official_reference={"key": "goblin", "pack": "pf2e.pathfinder-bestiary"},
    )
    refs = [e["official_reference"] for e in read(ws, "search_entities", text="Gobelin")]
    assert sorted(refs, key=lambda r: r["pack"] or "") == [
        {"key": "goblin", "pack": None},
        {"key": "goblin", "pack": "pf2e.pathfinder-bestiary"},
    ]

    # A translated name is never stored as the key; nor is anything but the key and its pack.
    assert "English key" in refused(
        ws, "create_entity", names=["Gobelin"], official_reference={"key": "Gobelin guerrière"}
    )
    assert "key" in refused(
        ws,
        "create_entity",
        names=["Gobelin"],
        official_reference={"key": "goblin", "name": "Gobelin guerrier"},
    )
    # The index refuses a hand-edited file that stores a translation too.
    [path, *_] = sorted((ws.root / "canon/entities").glob("*.md"))
    path.write_text(path.read_text().replace("key: goblin", "key: Gobelin guerrière"))
    assert main(["check", "-w", str(ws.root)]) == 1
    assert path.name in capsys.readouterr().err


# Hand edits (CAN-11), check (PKG-15) and upgrade (PKG-16)


def gm(ws: Workspace, *argv: str, interactive: bool = True) -> int:
    with patch.object(cli, "interactive", return_value=interactive):
        return main([*argv, "-w", str(ws.root)])


def the_fact(ws: Workspace, fact_id: str) -> dict:
    [found] = [f for f in read(ws, "search_facts", include_retconned=True) if f["id"] == fact_id]
    return found


def test_a_hand_edited_fact_is_logged_as_an_agent_proposal_until_the_gm_promotes_it(
    ws: Workspace,
) -> None:
    mira = entity(ws, "Mira Pell")
    played = fact(ws, "Mira sits on the Lock Council.", entities=[mira], origin=SEEN)
    path = ws.root / f"canon/facts/{played}.md"
    path.write_text(path.read_text().replace("Lock Council", "Harbour Council"))

    edited = the_fact(ws, played)
    assert edited["statement"] == "Mira sits on the Harbour Council."
    assert edited["rank"] == "agent_proposal"  # whatever the front matter says
    *_, hand_edit = log(ws)
    assert hand_edit["kind"] == "hand_edit"
    assert hand_edit["target"] == f"canon/facts/{played}.md"
    assert hand_edit["rank"] == "agent_proposal"
    assert "Lock Council" in hand_edit["before"] and "Harbour" in hand_edit["after"]
    assert edited["admitted_by"] == hand_edit["id"]
    assert len(log(ws)) == 3  # reading again logs nothing new

    assert gm(ws, "promote", str(hand_edit["id"]), interactive=False) == 1
    assert the_fact(ws, played)["rank"] == "agent_proposal"

    assert gm(ws, "promote", str(hand_edit["id"])) == 0
    assert the_fact(ws, played)["rank"] == "gm_decision"
    *_, promoted, interaction = log(ws)
    assert promoted["rank"] == "gm_decision" and promoted["promotion"] == interaction["id"]
    assert (interaction["interaction"], interaction["entry"]) == ("promote", hand_edit["id"])
    assert interaction["authenticated"] is True
    assert gm(ws, "promote", str(hand_edit["id"])) == 1  # once only


def test_a_new_file_and_a_deleted_file_written_by_hand_are_logged(ws: Workspace) -> None:
    mira = entity(ws, "Mira Pell")
    entity_file = next((ws.root / "canon/entities").glob("*.md"))
    (ws.root / "canon/facts").mkdir()
    (ws.root / "canon/facts/f-0000beef.md").write_text(
        f"---\nid: f-0000beef\nentities: [{mira}]\nrank: played\n"
        "origin: {kind: gm, words: Mira is a smuggler.}\n---\nMira smuggles salt.\n"
    )
    assert the_fact(ws, "f-0000beef")["rank"] == "agent_proposal"

    entity_file.unlink()
    read(ws, "search_entities")
    deleted = log(ws)[-1]
    assert (deleted["kind"], deleted["after"]) == ("hand_edit", None)
    assert deleted["target"] == entity_file.relative_to(ws.root).as_posix()


def test_core_writes_undo_and_approval_are_not_hand_edits(ws: Workspace) -> None:
    mira = entity(ws, "Mira Pell")
    played = fact(ws, "Mira sits on the Lock Council.", entities=[mira], origin=SEEN)
    act(
        ws,
        "record_event",
        description="Mira resigns.",
        date="4725-06",
        closes=[played],
        origin=SEEN,
    )
    assert gm(ws, "log", "undo", "3", "--reason", "other") == 0
    read(ws, "search_events")
    assert [e["kind"] for e in log(ws)] == ["action", "action", "action", "gm_interaction"]


def test_check_lists_hand_edits_awaiting_promotion(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    entity(ws, "Mira Pell")
    path = next((ws.root / "canon/entities").glob("*.md"))
    path.write_text(path.read_text() + "Tall.\n")

    assert gm(ws, "check") == 0
    out = capsys.readouterr().out
    assert "secondchair promote 2" in out and path.name in out


def test_check_passes_on_a_valid_workspace_and_names_each_invalid_file(
    ws: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    entity(ws, "Mira Pell")
    assert gm(ws, "check") == 0
    capsys.readouterr()

    (ws.root / "canon/facts").mkdir()
    (ws.root / "canon/facts/f-broken.md").write_text("no front matter\n")
    (ws.root / "action-log/000099.yaml").write_text("id: [unclosed\n")
    (ws.root / "moment.yaml").write_text("moment: lunch\nseq: 1\n")
    (ws.root / "delegation.yaml").write_text("prep: {}\n")
    for folder in ("jobs", "calls"):
        (ws.root / folder).mkdir(exist_ok=True)
        (ws.root / folder / "000098.yaml").write_text(f"- not a {folder} mapping\n")

    assert gm(ws, "check") == 1
    err = capsys.readouterr().err
    for name in ("f-broken.md", "000099.yaml", "moment.yaml", "delegation.yaml"):
        assert name in err
    for name in ("jobs/000098.yaml", "calls/000098.yaml"):
        assert name in err


def git(ws: Workspace, *argv: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ws.root), *argv], check=True, capture_output=True, text=True
    ).stdout


def test_an_older_schema_blocks_serve_until_upgrade_migrates_it_as_a_git_diff(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    git(ws, "init", "-q")
    git(ws, "add", "-A")
    git(ws, "-c", "user.name=GM", "-c", "user.email=gm@example.org", "commit", "-qm", "v1")

    def rename_prep(root: Path) -> None:  # a synthetic migration from schema 1 to 2
        table = root / "delegation.yaml"
        table.write_text(table.read_text().replace("prep:", "preparation:", 1))

    monkeypatch.setattr(workspace, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(workspace, "MIGRATIONS", {1: rename_prep})

    assert main(["serve", str(ws.root)]) == 1
    assert "secondchair upgrade" in capsys.readouterr().err

    assert gm(ws, "upgrade") == 0
    diff = git(ws, "diff")
    assert "-schema_version: 1\n+schema_version: 2" in diff
    assert "+preparation:" in diff
    assert workspace.load(ws.root).schema_version == 2
    assert gm(ws, "upgrade") == 0  # already current
    assert "already" in capsys.readouterr().out.lower()


def test_upgrade_refuses_a_newer_schema(ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    config = ws.root / "workspace.yaml"
    config.write_text(config.read_text().replace("schema_version: 1", "schema_version: 9"))
    assert gm(ws, "upgrade") == 1
    assert "newer" in capsys.readouterr().err
