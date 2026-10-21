"""The mystery graph on facts (BVE-02): the v3 mystery-graph test cases (pf2e-open-campaign,
tests/test_mysteries.py and test_mystery_graph.py), ported to the pure check."""

import asyncio
from typing import Any

import pytest
from mcp import Client

from secondchair.cli import main
from secondchair.core import index, mystery, workspace
from secondchair.core.index import CanonError
from secondchair.core.server import build_server

N1, N2, N3 = "node-inn", "node-brand", "node-guild"
C1, C2 = "conclusion-sabotage", "conclusion-guild-pays"
ENTITIES = {"e-inn", "e-brand", "e-guild"}
NODES = [
    {"id": N1, "entity": "e-inn", "entry": True},
    {"id": N2, "entity": "e-brand"},
    {"id": N3, "entity": "e-guild"},
]


def clue(n: int, on: str, *to: str, **extra: Any) -> dict:
    return {"id": f"clue-{n}", "fact": f"f-clue{n}", "on": on, "points_to": list(to), **extra}


# Sound: C1 has 4 clues on 3 nodes; N2 and N3 are each pointed to 3 times.
SOUND = [clue(1, N1, C1, N2, N3), clue(2, N1, C1, N2, N3), clue(3, N2, C1, N3), clue(4, N3, C1, N2)]
# N3 is reached only by clue-4 (on N2) when it is added; clue-3 is on N3.
BRIDGE = [clue(1, N1, C1, N2), clue(2, N2, C1, N1), clue(3, N3, C1)]


def facts(*closed: str, retconned: tuple[str, ...] = ()) -> dict[str, dict]:
    ids = ["f-sabotage", "f-guild-pays", "f-step", *(f"f-clue{n}" for n in range(1, 10))]
    return {
        i: {
            "id": i,
            "valid_to": "4726-02" if i in closed else None,
            "status": "retconned" if i in retconned else "canon",
        }
        for i in ids
    }


def doc(clues=SOUND, nodes=NODES, conclusions=None) -> dict:
    conclusions = conclusions or [{"id": C1, "fact": "f-sabotage"}]
    return {"id": "e-mystery", "conclusions": conclusions, "nodes": nodes, "clues": clues}


def check(d: Any, closed=(), known=(), lose=(), retconned=()) -> dict:
    return mystery.check(d, facts(*closed, retconned=retconned), ENTITIES, set(known), list(lose))


def codes(report: dict) -> list[str]:
    return [w["code"] for w in report["warnings"]]


def test_sound_mystery_is_clean() -> None:
    report = check(doc())
    assert report["problems"] == []
    assert report["warnings"] == []


@pytest.mark.parametrize(
    "bad, needle",
    [
        (clue(1, "node-nowhere", C1), "clue-1: on node-nowhere is not a node of this mystery"),
        (clue(1, N1, "conclusion-x"), "clue-1: points_to conclusion-x is neither a node nor"),
        ({**clue(1, N1, C1), "fact": "f-missing"}, "clue-1: fact f-missing is not in canon"),
    ],
)
def test_clue_references_must_resolve(bad: dict, needle: str) -> None:
    problems = check(doc(clues=[bad, *SOUND[1:]]))["problems"]
    assert any(needle in p for p in problems), problems


def test_nodes_and_conclusions_must_resolve() -> None:
    nodes = [*NODES, {"id": "node-event"}, {"id": "node-ghost", "entity": "e-ghost"}]
    conclusions = [{"id": C1, "fact": "f-sabotage"}, {"id": C2, "fact": "f-nope"}]
    problems = check(doc(nodes=nodes, conclusions=conclusions))["problems"]
    assert any("node-event: an entity or a proactive fact is required" in p for p in problems)
    assert any("node-ghost: entity e-ghost is not in canon" in p for p in problems)
    assert any(f"{C2}: fact f-nope is not in canon" in p for p in problems)


def test_local_ids_are_unique_in_the_mystery() -> None:
    problems = check(doc(clues=[*SOUND, clue(9, N1, C1) | {"id": N2}]))["problems"]
    assert any(f"{N2}: id used twice" in p for p in problems), problems


@pytest.mark.parametrize(
    "change, needle",
    [
        ({"on": [N1, N2]}, "clue-1: on must be a node id"),
        ({"on": {"x": N1}}, "clue-1: on must be a node id"),
        ({"points_to": N2}, "clue-1: points_to must be a list of ids"),
        ({"points_to": {"to": C1}}, "clue-1: points_to must be a list of ids"),
        ({"points_to": [{"to": C1}, N2]}, "clue-1: points_to must be a list of ids"),
    ],
)
def test_malformed_clue_shapes_are_reported_not_raised(change: dict, needle: str) -> None:
    problems = check(doc(clues=[SOUND[0] | change, *SOUND[1:]]))["problems"]
    assert any(needle in p for p in problems), problems


def test_unhashable_references_are_reported_not_raised() -> None:
    nodes = [*NODES, {"id": "node-x", "entity": ["e-inn"]}, {"id": "node-y", "proactive": {"x": 1}}]
    clues = [SOUND[0] | {"fact": ["f-clue1"]}, *SOUND[1:]]
    conclusions = [{"id": C1, "fact": {"f": 1}}]
    problems = check(doc(clues=clues, nodes=nodes, conclusions=conclusions))["problems"]
    for needle in (f"{C1}: fact", "node-x: entity", "node-y: ", "clue-1: fact"):
        assert any(p.startswith(needle) for p in problems), (needle, problems)


def test_malformed_documents_are_reported_not_raised() -> None:
    for bad in ({"id": "e-mystery", "clues": "x"}, {"id": "e-mystery", "nodes": [3]}, []):
        assert check(bad)["problems"]


def test_m1_conclusion_with_two_clues_warns() -> None:
    clues = [clue(1, N1, C1, N2, N3), clue(2, N2, C1, N3), clue(3, N3, N2), clue(4, N1, N2, N3)]
    report = check(doc(clues=clues))
    assert codes(report) == ["mystery-three-clues"]
    assert f"{C1}: 2 live clue(s), 3 expected" in report["warnings"][0]["message"]


@pytest.mark.parametrize(
    "extra, closed, unreachable",
    [
        ([], (), True),  # nothing points to N3
        ([clue(4, N2, N3)], ("f-clue4",), True),  # M5 / E17: the only clue to N3 is lost
        ([clue(4, N2, N3)], (), False),  # the same clue, hidden, is enough
    ],
)
def test_m5_unreachable_node_is_flagged(extra, closed, unreachable) -> None:
    report = check(doc(clues=BRIDGE + extra), closed=closed)
    flagged = [w for w in report["warnings"] if w["code"] == "mystery-unreachable"]
    assert bool(flagged) is unreachable
    assert not flagged or flagged[0]["message"].startswith(f"{N3} is unreachable")


def test_a_retconned_clue_is_lost() -> None:
    report = check(doc(clues=[*BRIDGE, clue(4, N2, N3)]), retconned=("f-clue4",))
    assert "mystery-unreachable" in codes(report)


def test_conclusion_only_on_unreachable_nodes_is_flagged() -> None:
    conclusions = [{"id": C1, "fact": "f-sabotage"}, {"id": C2, "fact": "f-guild-pays"}]
    clues = [*BRIDGE[:2], clue(3, N3, C2)]
    assert "mystery-conclusion" in codes(check(doc(clues=clues, conclusions=conclusions)))


PROACTIVE = [
    {"id": N1, "entity": "e-brand"},
    {"id": N2, "proactive": "f-step"},  # a front's agenda step, held as a fact
]
ON_PROACTIVE = [clue(1, N2, C1, N1), clue(2, N2, C1, N1), clue(3, N2, C1, N1), clue(4, N1, C1)]


@pytest.mark.parametrize("closed, expected", [((), []), (("f-step",), ["mystery-entry"])])
def test_proactive_root_holds_while_its_fact_holds(closed, expected) -> None:
    # One warning when the step is averted, no cascade.
    assert codes(check(doc(nodes=PROACTIVE, clues=ON_PROACTIVE), closed=closed)) == expected


def test_inverted_rule_warns_on_a_node_pointed_twice() -> None:
    clues = [clue(1, N1, C1, N2, N3), clue(2, N1, C1, N2), clue(3, N2, C1, N3), clue(4, N3, C1, N2)]
    report = check(doc(clues=clues))
    assert codes(report) == ["mystery-node-clues"]
    assert f"{N3}: 2 clue(s) point to it, 3 expected" in report["warnings"][0]["message"]


def test_single_point_of_failure_warns() -> None:
    clues = [clue(1, N1, C1, N2, N3), clue(2, N1, C1, N2, N3), clue(5, N1, C1, N2, N3)]
    clues += [clue(3, N2, N3), clue(4, N3, N2)]
    assert codes(check(doc(clues=clues))) == ["mystery-single-node"]


def test_graph_rules_skip_solved_mysteries() -> None:
    # The party knows the only conclusion: the mystery is closed.
    assert check(doc(clues=BRIDGE), known={"f-sabotage"})["warnings"] == []
    assert check(doc(clues=BRIDGE))["warnings"] != []


def test_states_are_derived_from_canon_and_knowledge() -> None:
    report = check(doc(clues=BRIDGE), closed=("f-clue2",), known={"f-clue1"})
    states = {c["id"]: c["state"] for c in report["clues"]}
    assert states == {"clue-1": "found", "clue-2": "lost", "clue-3": "hidden"}
    assert report["conclusions"][0]["state"] == "unknown"


def test_report_counts_clues_on_unreachable_nodes_apart() -> None:
    [c1] = check(doc(clues=BRIDGE))["conclusions"]  # clue-3 is on N3, unreachable
    assert (c1["live_clues"], c1["unreachable_clues"], c1["found_clues"]) == (3, 1, 0)
    assert c1["nodes"] == 3


def test_report_marks_what_is_within_the_party_s_reach() -> None:
    report = check(doc(clues=[clue(1, N1, C1, N2, N3), *SOUND[1:]]), known={"f-clue1"})
    nodes = {n["id"]: n for n in report["nodes"]}
    assert nodes[N2]["reachable"] and nodes[N2]["within_reach"]
    assert nodes[N2]["incoming_clues"] == 3


def test_lose_simulates_the_loss_without_writing() -> None:
    d = doc(clues=[*BRIDGE, clue(4, N2, N3)])
    assert "mystery-unreachable" not in codes(check(d))
    report = check(d, lose=["clue-4"])
    assert "mystery-unreachable" in codes(report)
    assert report["simulated_loss"] == ["clue-4"]
    assert d["clues"][3] == clue(4, N2, N3)


@pytest.mark.parametrize(
    "lose, needle", [("clue-1", "found"), ("clue-2", "already lost"), ("clue-9", "no clue")]
)
def test_lose_refuses_found_lost_or_unknown_clues(lose: str, needle: str) -> None:
    clues = [clue(1, N1, C1, N2), clue(2, N2, C1), clue(3, N1, C1)]
    with pytest.raises(CanonError, match=needle):
        check(doc(clues=clues), closed=("f-clue2",), known={"f-clue1"}, lose=[lose])


# Through the Core's MCP tools, as an agent reaches them.

BIBLE = {"kind": "source", "source": "bible.md", "page": "3"}


@pytest.fixture
def ws(tmp_path):
    main(["init", str(tmp_path / "camp"), "--language", "en", "--calendar", "absalom"])
    return workspace.load(tmp_path / "camp")


def call(ws, tool: str, **arguments: Any) -> Any:
    async def run() -> Any:
        async with Client(build_server(ws)) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def act(ws, tool: str, **arguments: Any) -> Any:
    result = call(ws, tool, agent="claude-prep", **arguments)
    assert not result.is_error, result
    return result.structured_content


def entity(ws, name: str) -> str:
    act(ws, "create_entity", names=[name])
    [found] = call(ws, "search_entities", text=name).structured_content["result"]
    return found["id"]


def fact(ws, statement: str) -> str:
    act(ws, "record_fact", statement=statement, entities=[], origin=BIBLE)
    [found] = call(ws, "search_facts", text=statement).structured_content["result"]
    return found["id"]


def test_the_core_records_a_mystery_and_flags_a_lost_clue(ws) -> None:
    """E17: losing the only clue to a node is written (play wins) and flagged."""
    ids = {n: entity(ws, n) for n in ("Hanged Inn", "Oskel Brand", "Lantern Guild", "Who")}
    sabotage = fact(ws, "Someone sabotages the inn.")
    clues = [fact(ws, f"Clue number {n}.") for n in range(1, 5)]
    graph = {
        "conclusions": [{"id": C1, "fact": sabotage}],
        "nodes": [
            {"id": N1, "entity": ids["Hanged Inn"], "entry": True},
            {"id": N2, "entity": ids["Oskel Brand"]},
            {"id": N3, "entity": ids["Lantern Guild"]},
        ],
        "clues": [c | {"fact": clues[i]} for i, c in enumerate([*BRIDGE, clue(4, N2, N3)])],
    }
    act(ws, "record_mystery", mystery=ids["Who"], **graph)
    report = call(ws, "check_mystery", mystery=ids["Who"]).structured_content
    assert report["problems"] == []
    assert "mystery-unreachable" not in codes(report)

    act(
        ws,
        "record_event",
        description="The register burns.",
        date="4726-02-01",
        origin=BIBLE,
        closes=[clues[3]],
    )
    report = call(ws, "check_mystery", mystery=ids["Who"]).structured_content
    assert "mystery-unreachable" in codes(report)
    assert {c["id"]: c["state"] for c in report["clues"]}["clue-4"] == "lost"


def test_a_clue_the_party_knows_is_found_and_a_suspected_one_is_not(ws) -> None:
    who = entity(ws, "Who")
    inn = entity(ws, "Hanged Inn")
    sabotage = fact(ws, "Someone sabotages the inn.")
    clues = [fact(ws, f"Clue number {n}.") for n in (1, 2)]
    act(
        ws,
        "record_mystery",
        mystery=who,
        conclusions=[{"id": C1, "fact": sabotage}],
        nodes=[{"id": N1, "entity": inn, "entry": True}],
        clues=[clue(n, N1, C1) | {"fact": f} for n, f in zip((1, 2), clues, strict=True)],
    )
    learned = {"origin": BIBLE, "date": "4726-01-01"}
    act(ws, "record_knowledge", knower="party", fact=clues[0], **learned)
    act(ws, "record_knowledge", knower="party", fact=clues[1], mode="suspects", **learned)
    report = call(ws, "check_mystery", mystery=who).structured_content
    states = {c["id"]: c["state"] for c in report["clues"]}
    assert states == {"clue-1": "found", "clue-2": "hidden"}


def test_the_core_refuses_a_mystery_whose_references_do_not_resolve(ws) -> None:
    who = entity(ws, "Who")
    bad = [{"id": C1, "fact": "f-nope"}]
    result = call(ws, "record_mystery", agent="claude-prep", mystery=who, conclusions=bad)
    assert result.is_error
    assert "f-nope is not in canon" in result.content[0].text
    result = call(ws, "record_mystery", agent="claude-prep", mystery="e-nope", conclusions=[])
    assert result.is_error
    assert "e-nope" in result.content[0].text


# A draft: a note under notes/mysteries/ with the graph, statements in place of fact ids (#177).


def draft(ws, slug: str, front: dict | None) -> None:
    path = ws.root / "notes" / "mysteries" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "Just prose.\n" if front is None else index.join_doc(front, "Notes.")
    path.write_text(text)


def draft_graph(inn: str, clues: list[dict]) -> dict:
    return {
        "id": "d-12345678",
        "status": "draft",
        "conclusions": [{"id": C1, "statement": "The steward sabotages the inn."}],
        "nodes": [{"id": N1, "entity": inn, "entry": True}],
        "clues": clues,
    }


def draft_clue(n: int, on: str = N1, **extra: Any) -> dict:
    return {"id": f"clue-{n}", "statement": f"Draft clue {n}.", "on": on, "points_to": [C1]} | extra


def test_a_draft_note_is_checked_like_a_mystery_and_nothing_is_written(ws) -> None:
    inn = entity(ws, "Hanged Inn")
    clues = [draft_clue(n) for n in (1, 2, 3)]
    draft(ws, "stolen-ledger", draft_graph(inn, clues))
    before = sorted(p for p in ws.root.rglob("*") if p.is_file())
    report = call(ws, "check_draft_mystery", mystery="stolen-ledger").structured_content
    assert report["problems"] == []
    assert codes(report) == ["mystery-single-node"]
    assert {c["state"] for c in report["clues"]} == {"hidden"}
    assert sorted(p for p in ws.root.rglob("*") if p.is_file()) == before


def test_a_draft_loses_a_clue_and_a_single_node_conclusion_warns(ws) -> None:
    inn = entity(ws, "Hanged Inn")
    clues = [draft_clue(1), draft_clue(2)]
    draft(ws, "ledger", draft_graph(inn, clues))
    report = call(ws, "check_draft_mystery", mystery="ledger", lose=["clue-1"]).structured_content
    assert "mystery-three-clues" in codes(report)
    assert report["simulated_loss"] == ["clue-1"]
    assert {c["id"]: c["state"] for c in report["clues"]}["clue-1"] == "lost"
    result = call(ws, "check_draft_mystery", mystery="ledger", lose=["clue-9"])
    assert result.is_error


def test_a_draft_mixes_fact_ids_and_statements(ws) -> None:
    inn = entity(ws, "Hanged Inn")
    sabotage = fact(ws, "Someone sabotages the inn.")
    by_fact = {"id": "clue-2", "fact": sabotage, "on": N1, "points_to": [C1]}
    front = draft_graph(inn, [draft_clue(1), by_fact])
    front["conclusions"] = [{"id": C1, "fact": sabotage}]
    draft(ws, "mixed", front)
    report = call(ws, "check_draft_mystery", mystery="mixed").structured_content
    assert report["problems"] == []
    assert {c["id"]: c["fact"] for c in report["clues"]} == {
        "clue-1": "draft:clue-1",
        "clue-2": sabotage,
    }
    assert report["conclusions"][0]["fact"] == sabotage


def test_a_draft_with_an_unknown_fact_or_neither_is_a_problem(ws) -> None:
    inn = entity(ws, "Hanged Inn")
    front = draft_graph(inn, [draft_clue(1, fact="f-nope"), {"id": "clue-2", "on": N1}])
    draft(ws, "bad", front)
    report = call(ws, "check_draft_mystery", mystery="bad").structured_content
    assert any("f-nope is not in canon" in p for p in report["problems"])


def test_a_note_without_the_graph_or_a_missing_draft_is_refused(ws) -> None:
    draft(ws, "prose", None)
    draft(ws, "no-graph", {"id": "d-12345678", "status": "draft"})
    for slug in ("prose", "no-graph", "absent", "../canon/x"):
        assert call(ws, "check_draft_mystery", mystery=slug).is_error


def test_the_cli_checks_a_draft(ws, capsys) -> None:
    inn = entity(ws, "Hanged Inn")
    draft(ws, "cli", draft_graph(inn, [draft_clue(1), draft_clue(2)]))
    assert main(["mystery", "check-draft", "cli", "-w", str(ws.root), "--lose", "clue-1"]) == 0
    assert "mystery-three-clues" in capsys.readouterr().out
    assert main(["mystery", "check-draft", "absent", "-w", str(ws.root)]) == 1
