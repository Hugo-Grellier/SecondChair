"""S0 scores its fact probes against the frozen gold set and reports continuity errors (MET-01:
from the workspace and its action log only; MET-03: no LLM judge)."""

from pathlib import Path

import pytest
import yaml

from secondchair.bench import s0
from secondchair.core import canon, delegation, index, workspace
from secondchair.core.workspace import Workspace

SAMPLE = Path(__file__).parents[1] / "sample-campaign"
GOLD = yaml.safe_load((SAMPLE / "gold.yaml").read_text())
BIBLE = {"kind": "source", "source": "sample-campaign/bible.md", "page": "B04"}


def act(ws: Workspace, tool: str, **args: object) -> None:
    [found] = [t for t in canon.tools(ws) if t.name == tool]
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


def factions_answer(ws: Workspace) -> dict[str, list[str]]:
    """A structured answer read from canon, as an agent answers the probe with search_facts."""
    answer: dict[str, list[str]] = {}
    for f in index.search_facts(ws, relation="member_of"):
        answer.setdefault(f["relation"]["object"], []).append(f["relation"]["subject"])
    return answer


def test_fact_probes_pass_when_canon_answers_them(tmp_path: Path) -> None:
    ws, ids = rebuild(tmp_path)
    answers = {
        "factions": factions_answer(ws),
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
    assert report["continuity_errors"]["total"] == 0


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
