"""S0 scores its fact probes against the frozen gold set and reports continuity errors (MET-01:
from the workspace and its action log only; MET-03: no LLM judge)."""

from pathlib import Path

import pytest
import yaml

from secondchair.bench import s0
from secondchair.core import canon, delegation, index, mystery, workspace
from secondchair.core.workspace import Workspace

SAMPLE = Path(__file__).parents[1] / "sample-campaign"
GOLD = yaml.safe_load((SAMPLE / "gold.yaml").read_text())
BIBLE = {"kind": "source", "source": "sample-campaign/bible.md", "page": "B04"}


def act(ws: Workspace, tool: str, **args: object) -> None:
    [found] = [t for t in canon_tools(ws) if t.name == tool]
    delegation.act(ws, found, "s0-rebuild", lambda: found.fn(**args))


def rebuild(tmp_path: Path) -> tuple[Workspace, dict[str, str]]:
    """What the rebuild playbook writes for the faction paragraphs, through the Core."""
    config = yaml.safe_load((SAMPLE / "campaign.yaml").read_text())
    ws = workspace.init(tmp_path / "s0", config["campaign_language"], config["calendar"])

    names = [
        "Mira Pell",
        "Tovan Reed",
        "Edda Vale",
        "Ilex Venn",
        "Lock Council",
        "Reed Union",
        "Sounding Circle",
    ]
    for name in names:
        act(ws, "create_entity", names=[name])
    ids = {e["names"][0]: e["id"] for e in index.search_entities(ws)}
    for npc, faction in (
        ("Mira Pell", "Lock Council"),
        ("Tovan Reed", "Reed Union"),
        ("Edda Vale", "Sounding Circle"),
        ("Ilex Venn", "Sounding Circle"),
    ):
        act(
            ws,
            "record_fact",
            statement=f"{npc} belongs to the {faction}.",
            entities=[],
            relation={"type": "member_of", "subject": ids[npc], "object": ids[faction]},
            origin=BIBLE,
        )
    return ws, ids


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
    for name in ("The Dry Bell", "Weir", "Toll Archive", "Abandoned Kiln", "Cistern"):
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
    [check] = [t for t in canon_tools(ws) if t.name == "check_mystery"]
    report = check.fn(mystery=mystery)
    return {k: [x["id"] for x in report[k]] for k in ("conclusions", "nodes", "clues")}


def canon_tools(ws: Workspace) -> list:
    return [*canon.tools(ws), *mystery.tools(ws)]


def factions_answer(ws: Workspace) -> dict[str, list[str]]:
    """A structured answer read from canon, as an agent answers the probe with search_facts."""
    answer: dict[str, list[str]] = {}
    for f in index.search_facts(ws, relation="member_of"):
        answer.setdefault(f["relation"]["object"], []).append(f["relation"]["subject"])
    return answer


def test_fact_probes_pass_when_canon_answers_them(tmp_path: Path) -> None:
    ws, ids = rebuild(tmp_path)
    bell = rebuild_mystery(ws)
    answers = {
        "factions": factions_answer(ws),
        "mystery-structure": structure_answer(ws, bell),
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
    }

    report = s0.score_fact_probes(ws, GOLD, answers)

    assert report["probes"] == dict.fromkeys(s0.FACT_PROBES, True)
    assert {"mystery-structure", "mystery-answer"} <= set(report["probes"])
    assert report["continuity_errors"]["total"] == 0


def test_mystery_probes_score_the_graph_recorded_in_canon(tmp_path: Path) -> None:
    ws, _ = rebuild(tmp_path)
    bell = rebuild_mystery(ws)
    structure = structure_answer(ws, bell)
    # Each conclusion has three clues or more, on two nodes or more; the bible marks no entry.
    [check] = [t for t in canon_tools(ws) if t.name == "check_mystery"]
    report = check.fn(mystery=bell)
    assert report["problems"] == []
    assert [w["code"] for w in report["warnings"]] == ["mystery-entry"]

    assert s0.score_fact_probes(ws, GOLD, {"mystery-structure": structure})["probes"][
        "mystery-structure"
    ]
    short = {**structure, "clues": structure["clues"][:-1]}
    assert not s0.score_fact_probes(ws, GOLD, {"mystery-structure": short})["probes"][
        "mystery-structure"
    ]


def test_failed_probes_and_refused_contradictions_are_continuity_errors(tmp_path: Path) -> None:
    ws, ids = rebuild(tmp_path)
    answers = {"factions": {**factions_answer(ws), ids["Lock Council"]: [ids["Edda Vale"]]}}
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

    report = s0.score_fact_probes(ws, GOLD, answers)

    assert report["probes"]["factions"] is False
    assert report["probes"]["hidden-name"] is False  # no answer is a failure
    errors = report["continuity_errors"]
    assert errors["refused_contradictions"] == 1
    assert errors["failed_probes"] == len(s0.FACT_PROBES)
    assert errors["total"] == 1 + len(s0.FACT_PROBES)
