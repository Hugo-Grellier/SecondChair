"""Who knows what and the audience guard (CAN-13..16), through the Core's MCP tools."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from test_canon import JOB, act, call, entity, fact, refused

from secondchair.cli import main
from secondchair.core import index, workspace
from secondchair.core.workspace import Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    main(["init", str(tmp_path / "camp"), "--language", "en", "--calendar", "absalom"])
    return workspace.load(tmp_path / "camp")


def learn(ws: Workspace, knower: str, fact_id: str, **fields: Any) -> None:
    act(
        ws,
        "record_knowledge",
        knower=knower,
        fact=fact_id,
        origin=JOB,
        **{"date": "4725", **fields},
    )


def knows(ws: Workspace, knower: str, **args: Any) -> dict:
    result = call(ws, "what_knows", knower=knower, **args)
    assert not result.is_error, result
    return result.structured_content


def check(ws: Workspace, audience: str, text: str, cites: list[str]) -> Any:
    return call(ws, "check_audience_content", audience=audience, text=text, cites=cites)


def test_a_belief_is_a_never_true_fact_the_knower_believes(ws: Workspace) -> None:
    tovan, circle = entity(ws, "Tovan Reed"), entity(ws, "Sounding Circle")
    lie = fact(
        ws, "The Circle rings false warnings on purpose.", entities=[circle], never_true=True
    )
    learn(ws, tovan, lie, mode="believes")

    [doc] = (ws.root / "canon/knowledge").glob("*.md")
    front, _ = index.split_doc(doc.read_text())
    assert front | {"id": None} == {
        "id": None,
        "knower": tovan,
        "fact": lie,
        "mode": "believes",
        "date": "4725",
        "event": None,
        "rank": "agent_proposal",
        "origin": JOB,
    }
    assert yaml.safe_load((ws.root / f"canon/facts/{lie}.md").read_text().split("---")[1])[
        "never_true"
    ]
    assert knows(ws, tovan)[lie]["mode"] == "believes"
    assert "never true" in refused(
        ws, "record_knowledge", knower=tovan, fact=lie, origin=JOB, date="4725"
    )
    assert index.search_facts(ws, at="4725-06-01") == []  # never valid at any date
    assert "validity" in refused(
        ws,
        "record_fact",
        statement="x",
        entities=[],
        origin=JOB,
        never_true=True,
        valid_from="4725",
    )


def test_a_knower_inherits_its_factions_and_its_places_common_knowledge(ws: Workspace) -> None:
    edda, ilex = entity(ws, "Edda Vale"), entity(ws, "Ilex Venn")
    circle, reedbank = entity(ws, "Sounding Circle"), entity(ws, "Reedbank")
    for npc in (edda, ilex):
        fact(
            ws, f"{npc} belongs.", relation={"type": "member_of", "subject": npc, "object": circle}
        )
    fact(ws, "Edda lives here.", relation={"type": "lives_in", "subject": edda, "object": reedbank})
    bell = fact(ws, "The bell rings on dry nights.", entities=[reedbank])
    duty = fact(ws, "The Circle keeps the bell.", entities=[circle])
    cause = fact(ws, "A cracked relay rings the bell.", entities=[])
    learn(ws, reedbank, bell)  # common knowledge
    learn(ws, circle, duty, date="4725-05-01")
    learn(ws, ilex, cause)  # a member's private knowledge

    held = knows(ws, edda)
    assert {f: h["via"] for f, h in held.items()} == {bell: reedbank, duty: circle}
    assert cause not in knows(ws, circle)  # a faction never inherits from its members
    assert set(knows(ws, edda, at="4725-04-30")) == {bell}  # learned later
    assert knows(ws, "party") == {}  # closed world


def test_audience_content_must_cite_facts_the_audience_holds(ws: Workspace) -> None:
    mira, ilex = entity(ws, "Mira Pell"), entity(ws, "Ilex Venn")
    gate = fact(ws, "Mira Pell controls the gate.", entities=[mira])
    secret = fact(ws, "Ilex Venn tends the relay.", entities=[ilex])
    learn(ws, "party", gate)

    ok = check(ws, "party", "Mira Pell holds the key to the gate.", [gate])
    assert not ok.is_error and ok.structured_content == {gate: "knows"}

    for text, cites, reason in (
        ("The relay is tended.", [secret], f"party does not know ['{secret}']"),
        ("Something.", ["f-00000000"], "unknown fact ids ['f-00000000']"),
        ("CANARY-identity-1 Mira Pell", [gate], "canary markers ['CANARY-identity-1']"),
        ("Ask Ilex Venn about the gate.", [gate], "names party holds no fact about: ['Ilex Venn']"),
    ):
        result = check(ws, "party", text, cites)
        assert result.is_error and reason in result.content[0].text, result
    # Ilex may say its own name; Mira may not, knowing nothing that names Ilex.
    assert not check(ws, ilex, "I am Ilex Venn.", []).is_error
    assert check(ws, mira, "Ilex Venn?", []).is_error


def test_knowledge_needs_a_knower_a_fact_and_when_it_was_learned(ws: Workspace) -> None:
    mira = entity(ws, "Mira Pell")
    gate = fact(ws, "Mira Pell controls the gate.", entities=[mira])
    assert "neither" in refused(
        ws, "record_knowledge", knower="pc-ada", fact=gate, origin=JOB, date="4725"
    )
    assert "unknown fact" in refused(
        ws, "record_knowledge", knower=mira, fact="f-0", origin=JOB, date="4725"
    )
    assert "date" in refused(ws, "record_knowledge", knower=mira, fact=gate, origin=JOB)
    learn(ws, mira, gate)
    assert "already" in refused(
        ws, "record_knowledge", knower=mira, fact=gate, origin=JOB, date="4725"
    )


def test_hand_written_knowledge_is_checked_against_canon(ws: Workspace) -> None:
    tovan = entity(ws, "Tovan Reed")
    lie = fact(ws, "The Circle lies.", never_true=True)
    assert "never true" in refused(
        ws, "record_event", description="x", date="4725", origin=JOB, opens=[lie]
    )
    record = {
        "id": "k-00000000",
        "knower": tovan,
        "fact": lie,
        "mode": "knows",
        "date": "4725",
        "event": None,
        "rank": "agent_proposal",
        "origin": JOB,
    }
    (ws.root / "canon/knowledge").mkdir(exist_ok=True)
    (ws.root / "canon/knowledge/k-00000000.md").write_text(index.join_doc(record, ""))
    assert index.rebuild(ws) == [
        f"canon/knowledge/k-00000000.md: {lie} is never true: it can be believed or suspected,"
        " not known"
    ]
    assert knows(ws, tovan) == {}
