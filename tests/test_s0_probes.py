"""S0 scores its fact and knowledge probes against the frozen gold set, reports continuity errors
(MET-01: from the workspace and its action log only; MET-03: no LLM judge) and fails on any leak
(the leak invariant)."""

from pathlib import Path

import pytest
import yaml

from secondchair.bench import s0
from secondchair.core import canon, delegation, index, knowledge, mystery, workspace
from secondchair.core.workspace import Workspace

SAMPLE = Path(__file__).parents[1] / "sample-campaign"
GOLD = yaml.safe_load((SAMPLE / "gold.yaml").read_text())
START = GOLD["start"]["date"]
NAMES = (
    "Mira Pell",
    "Tovan Reed",
    "Edda Vale",
    "Sella Marr",
    "Orin Doss",
    "Ilex Venn",
    "Lock Council",
    "Reed Union",
    "Sounding Circle",
    "Reedbank",
    "Cistern",
)


def bible(page: str) -> dict[str, str]:
    return {"kind": "source", "source": "sample-campaign/bible.md", "page": page}


def act(ws: Workspace, tool: str, **args: object) -> None:
    [found] = [t for t in core_tools(ws) if t.name == tool]
    delegation.act(ws, found, "s0-rebuild", lambda: found.fn(**args))


def record(ws: Workspace, statement: str, page: str, **fields: object) -> str:
    act(ws, "record_fact", statement=statement, origin=bible(page), **{"entities": [], **fields})
    [found] = [f for f in index.search_facts(ws, text=statement) if f["statement"] == statement]
    return found["id"]


def learn(ws: Workspace, knower: str, fact: str, mode: str = "knows") -> None:
    """Who knows it at start, as the fact's own bible paragraph states."""
    [cited] = [f for f in index.search_facts(ws) if f["id"] == fact]
    origin = bible(cited["origin"]["page"])
    act(ws, "record_knowledge", knower=knower, fact=fact, mode=mode, date=START, origin=origin)


def rebuild(tmp_path: Path) -> tuple[Workspace, dict[str, str], dict[str, str]]:
    """What the rebuild playbook writes from the bible, through the Core: the faction and
    residence paragraphs, the secrets and who knows them. Returns the workspace, entity ids by
    name, and fact ids by the evaluator's vocabulary."""
    config = yaml.safe_load((SAMPLE / "campaign.yaml").read_text())
    ws = workspace.init(tmp_path / "s0", config["campaign_language"], config["calendar"])
    for name in NAMES:
        act(ws, "create_entity", names=[name])
    ids = {e["names"][0]: e["id"] for e in index.search_entities(ws)}
    for npc, faction, page in (
        ("Mira Pell", "Lock Council", "B04"),
        ("Tovan Reed", "Reed Union", "B05"),
        ("Edda Vale", "Sounding Circle", "B06"),
    ):
        record(
            ws,
            f"{npc} belongs to the {faction}.",
            page,
            relation={"type": "member_of", "subject": ids[npc], "object": ids[faction]},
        )
    for npc in ("Mira Pell", "Tovan Reed", "Edda Vale", "Sella Marr", "Orin Doss"):
        record(
            ws,
            f"{npc} lives in Reedbank.",
            "B01",
            relation={"type": "lives_in", "subject": ids[npc], "object": ids["Reedbank"]},
        )
    hidden, edda = ids["Ilex Venn"], ids["Edda Vale"]
    facts = {
        "bell-ringing": record(ws, "The warning bell rings on dry nights.", "B02"),
        "council-controls-gate": record(ws, "The Lock Council controls the gate.", "B02"),
        "secret-name": record(ws, "The Cistern maintainer's only name is Ilex Venn.", "B10"),
        "secret-member": record(
            ws,
            "Ilex Venn belongs to the Sounding Circle.",
            "B11",
            relation={"type": "member_of", "subject": hidden, "object": ids["Sounding Circle"]},
        ),
        "bell-cause": record(ws, "A cracked pressure relay rings the bell.", "B12"),
        "fund-diversion": record(ws, "Mira diverted the relay repair fund.", "B13"),
        "false-warnings": record(
            ws, "The Circle rings false warnings on purpose.", "B14", never_true=True
        ),
    }
    for f in ("bell-ringing", "council-controls-gate"):
        learn(ws, ids["Reedbank"], facts[f])  # common knowledge
    for knower in (hidden, edda):
        learn(ws, knower, facts["secret-name"])
        learn(ws, knower, facts["secret-member"])
    learn(ws, hidden, facts["bell-cause"])
    learn(ws, ids["Mira Pell"], facts["fund-diversion"])
    learn(ws, ids["Tovan Reed"], facts["false-warnings"], mode="believes")
    ids["The Dry Bell"] = rebuild_mystery(ws)
    return ws, ids, facts


MYSTERY = "sample-campaign/bible.md#secret-mystery"
CONCLUSIONS = {
    "conclusion-relay": "A cracked pressure relay at the Cistern causes the dry-night bell.",
    "conclusion-ledger": "Mira diverted the relay repair fund into an unofficial toll reserve.",
}
CLUES = {  # id: (node, place, evidence, conclusion), as the bible's table lists them
    "clue-1": ("node-weir", "Weir", "The dry gauge stays at zero.", "conclusion-relay"),
    "clue-2": ("node-weir", "Weir", "A pressure pulse runs down the conduit.", "conclusion-relay"),
    "clue-3": ("node-archive", "Toll Archive", "The repair account is empty.", "conclusion-ledger"),
    "clue-4": ("node-archive", "Toll Archive", "Mira signed the transfer.", "conclusion-ledger"),
    "clue-5": (
        "node-kiln",
        "Abandoned Kiln",
        "A spare relay bears the account number.",
        "conclusion-ledger",
    ),
    "clue-6": (
        "node-kiln",
        "Abandoned Kiln",
        "A test log ties bells to a crack.",
        "conclusion-relay",
    ),
    "clue-7": (
        "node-cistern",
        "Cistern",
        "The relay's crack pulses with the bell.",
        "conclusion-relay",
    ),
}


def rebuild_mystery(ws: Workspace) -> str:
    """What the rebuild playbook writes for the secret-mystery section, through the Core."""
    origin = {"kind": "source", "source": "sample-campaign/bible.md", "page": "secret-mystery"}
    for name in ("The Dry Bell", "Weir", "Toll Archive", "Abandoned Kiln"):  # Cistern exists
        act(ws, "create_entity", names=[name])
    ids = {e["names"][0]: e["id"] for e in index.search_entities(ws)}

    def fact(statement: str) -> str:
        act(ws, "record_fact", statement=statement, entities=[], origin=origin)
        [found] = index.search_facts(ws, text=statement)
        return found["id"]

    nodes = {node: ids[place] for node, place, _, _ in CLUES.values()}
    act(
        ws,
        "record_mystery",
        mystery=ids["The Dry Bell"],
        conclusions=[{"id": c, "fact": fact(s)} for c, s in CONCLUSIONS.items()],
        nodes=[{"id": n, "entity": e} for n, e in nodes.items()],
        clues=[
            {"id": c, "fact": fact(evidence), "on": node, "points_to": [to]}
            for c, (node, _, evidence, to) in CLUES.items()
        ],
    )
    return ids["The Dry Bell"]


def structure_answer(ws: Workspace, mystery: str) -> dict[str, list[str]]:
    """The structured answer an agent reads from check_mystery."""
    [check] = [t for t in core_tools(ws) if t.name == "check_mystery"]
    report = check.fn(mystery=mystery)
    return {k: [x["id"] for x in report[k]] for k in ("conclusions", "nodes", "clues")}


def core_tools(ws: Workspace) -> list:
    return [*canon.tools(ws), *knowledge.tools(ws), *mystery.tools(ws)]


def answers(ws: Workspace, ids: dict[str, str], facts: dict[str, str]) -> dict:
    """Structured answers read from canon, as an agent answers with search_facts and what_knows."""
    factions: dict[str, list[str]] = {}
    for f in index.search_facts(ws, relation="member_of"):
        factions.setdefault(f["relation"]["object"], []).append(f["relation"]["subject"])
    edda = knowledge.known(ws, ids["Edda Vale"], START)
    circle = knowledge.known(ws, ids["Sounding Circle"], START)
    both = (
        knowledge.known(ws, ids["Sella Marr"], START).keys()
        & knowledge.known(ws, ids["Orin Doss"], START).keys()
    )
    vocabulary = {fact: word for word, fact in facts.items()}
    belief = facts["false-warnings"]
    [lie] = [f for f in index.search_facts(ws) if f["id"] == belief]
    return {
        "factions": factions,
        "mystery-structure": structure_answer(ws, ids["The Dry Bell"]),
        "hidden-name": {"secret_name": "Ilex Venn", "public_name": None},
        "mystery-answer": {
            "cause": "cracked-pressure-relay",
            "money": "unofficial-toll-reserve",
            "sabotage": False,
        },
        "planned-treasure": {
            "treasure-fee": ids["Edda Vale"],
            "treasure-case": "unclaimed",
            "party_owns": [],
        },
        "situations": GOLD["probes"][-1]["expected"],
        "edda-knowledge": {
            "name": facts["secret-name"] in edda,
            "cause": facts["bell-cause"] in edda,
            "diversion": facts["fund-diversion"] in edda,
        },
        "circle-knowledge": {
            "name": facts["secret-name"] in circle,
            "cause": facts["bell-cause"] in circle,
        },
        "common-knowledge": {
            "both_know": [vocabulary[f] for f in both],
            "both_do_not_know": [w for w in ("bell-cause",) if facts[w] not in both],
        },
        "belief": {
            "ever_true": not lie["never_true"],
            "believers": [
                i
                for i in ids.values()
                if knowledge.known(ws, i).get(belief, {}).get("mode") == "believes"
            ],
        },
    }


def test_probes_pass_and_nothing_leaks_when_canon_answers_them(tmp_path: Path) -> None:
    ws, ids, facts = rebuild(tmp_path)

    report = s0.score_probes(ws, GOLD, answers(ws, ids, facts))

    assert report["probes"] == dict.fromkeys(s0.PROBES, True)
    assert report["continuity_errors"]["total"] == 0
    assert report["leaks"] == []
    assert report["passed"]


def test_a_knower_inherits_but_a_faction_never_inherits_from_its_members(tmp_path: Path) -> None:
    ws, ids, facts = rebuild(tmp_path)
    sella = knowledge.known(ws, ids["Sella Marr"], START)
    assert {f: h["via"] for f, h in sella.items()} == {
        facts["bell-ringing"]: ids["Reedbank"],
        facts["council-controls-gate"]: ids["Reedbank"],
    }
    assert knowledge.known(ws, ids["Sounding Circle"]) == {}


def test_any_leak_fails_s0(tmp_path: Path) -> None:
    ws, ids, facts = rebuild(tmp_path)
    marked = record(ws, "CANARY-mystery-1 The relay hides under the Cistern.", "B12")
    learn(ws, "party", marked)
    learn(ws, ids["Tovan Reed"], facts["secret-name"])
    learn(ws, "party", facts["fund-diversion"])

    report = s0.score_probes(ws, GOLD, answers(ws, ids, facts))

    assert not report["passed"]
    assert sorted(report["leaks"]) == sorted(
        [
            f"CANARY-mystery-1 reaches party ({marked})",
            f"B12 known by party at start ({marked})",
            f"'Ilex Venn' reaches npc-tovan ({facts['secret-name']})",
            f"B13 known by party at start ({facts['fund-diversion']})",
        ]
    )


def test_mystery_probes_score_the_graph_recorded_in_canon(tmp_path: Path) -> None:
    ws, ids, _ = rebuild(tmp_path)
    bell = ids["The Dry Bell"]
    structure = structure_answer(ws, bell)
    # Each conclusion has three clues or more, on two nodes or more; the bible marks no entry.
    [check] = [t for t in core_tools(ws) if t.name == "check_mystery"]
    report = check.fn(mystery=bell)
    assert report["problems"] == []
    assert [w["code"] for w in report["warnings"]] == ["mystery-entry"]

    assert s0.score_probes(ws, GOLD, {"mystery-structure": structure})["probes"][
        "mystery-structure"
    ]
    short = {**structure, "clues": structure["clues"][:-1]}
    assert not s0.score_probes(ws, GOLD, {"mystery-structure": short})["probes"][
        "mystery-structure"
    ]


def test_failed_probes_and_refused_contradictions_are_continuity_errors(tmp_path: Path) -> None:
    ws, ids, facts = rebuild(tmp_path)
    given = answers(ws, ids, facts)
    wrong = {"factions": {**given["factions"], ids["Lock Council"]: [ids["Edda Vale"]]}}
    seen = {"kind": "observation", "quote": "Edda paid 12 silver.", "locator": "S1-02"}
    act(ws, "record_fact", statement="Edda paid 12 silver.", entities=[], origin=seen)
    [fee] = index.search_facts(ws, text="silver")
    with pytest.raises(delegation.DelegationError, match="played"):
        act(
            ws,
            "correct_fact",
            fact=fee["id"],
            statement="Edda paid 20 silver.",
            entities=[],
            origin={"kind": "job", "job": "s0-rebuild"},
        )

    report = s0.score_probes(ws, GOLD, wrong)

    assert report["probes"]["factions"] is False
    assert report["probes"]["hidden-name"] is False  # no answer is a failure
    errors = report["continuity_errors"]
    assert errors["refused_contradictions"] == 1
    assert errors["failed_probes"] == len(s0.PROBES)
    assert errors["total"] == 1 + len(s0.PROBES)
    assert report["passed"]  # continuity is reported, not gated, until floors exist (MET-05a)
