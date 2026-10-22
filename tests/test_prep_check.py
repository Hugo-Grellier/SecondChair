"""`check_prep` (a prep note's index block) and `check_prep_guide` (a whole note for the party)."""

import copy
from collections.abc import Iterator
from typing import Any

import pytest
import yaml
from test_canon import call, entity, fact
from test_knowledge import learn, ws  # noqa: F401  (ws is a fixture)

from secondchair.cli import main
from secondchair.core import vtt
from secondchair.core.workspace import Workspace

UUID = "Compendium.sys.bestiary.Actor.abc123"
GOB = {"uuid": UUID, "name": "Gob", "level": 1}
GOOD: dict[str, Any] = {
    "creatures": [GOB],
    "encounters": [
        {"id": "ambush", "level": 1, "party_size": 4, "xp": 80, "threat": "moderate"}
        | {"creatures": [GOB, GOB]}
    ],
    "treasure": [{"level": 1, "party_size": 4, "total_gp": 175}],
    "clues": ["clue-1"],
    "scenes": ["s1-warehouse"],
}


def note(
    camp: Workspace, block: dict[str, Any], name: str = "dossier", body: str = "# Notes\n"
) -> None:
    path = camp.root / f"prep/adventure-x/{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{body}\n```yaml\n{yaml.safe_dump(block)}```\n")
    (camp.root / "scenes").mkdir(exist_ok=True)
    (camp.root / "scenes/s1-warehouse.yaml").write_text("scene: {name: Warehouse}\nitems: []\n")
    (camp.root / "notes").mkdir(exist_ok=True)
    (camp.root / "notes/m.md").write_text("---\nclues: [{id: clue-1}]\n---\nDraft\n")


def lint(camp: Workspace, block: dict[str, Any]) -> dict[str, Any]:
    note(camp, block)
    result = call(camp, "check_prep", path="adventure-x/dossier.md")
    assert not result.is_error, result
    return result.structured_content


@pytest.fixture
def client() -> Iterator[None]:
    """A connected GM client whose compendium holds one creature."""
    vtt.connect(None, lambda op, params: [GOB] if params["query"] == "Gob" else [])
    yield
    vtt.connect(None)


def test_a_good_file_is_clean(ws: Workspace, client: None) -> None:  # noqa: F811
    result = lint(ws, GOOD)

    assert result == {
        "ok": True,
        "problems": [],
        "unchecked": [],
        "encounters": [{"id": "ambush", "xp": 80, "threat": "moderate"}],
        "treasure": [{"level": 1, "total_gp": 175, "budget_gp": 175}],
    }


def test_an_xp_or_threat_mismatch_is_reported_not_fixed(ws: Workspace, client: None) -> None:  # noqa: F811
    block = copy.deepcopy(GOOD)
    block["encounters"][0] |= {"xp": 60, "threat": "low"}

    result = lint(ws, block)

    assert not result["ok"]
    assert "states 60 XP, GM Core gives 80" in result["problems"][0]
    assert "states low threat, GM Core gives moderate" in result["problems"][1]
    assert (
        yaml.safe_load(
            (ws.root / "prep/adventure-x/dossier.md")
            .read_text()
            .split("```yaml\n")[1]
            .rsplit("```", 1)[0]
        )["encounters"][0]["xp"]
        == 60
    )


def test_treasure_clue_and_scene_problems(ws: Workspace, client: None) -> None:  # noqa: F811
    block = copy.deepcopy(GOOD) | {"clues": ["clue-9"], "scenes": ["s2-nowhere"]}
    block["treasure"] = [{"level": 1, "party_size": 4, "total_gp": 400}]

    problems = lint(ws, block)["problems"]

    assert problems == [
        "treasure level 1: 400 gp over the 175 gp budget",
        "clue clue-9 is in no mystery or draft note",
        "scene s2-nowhere: no desired state in scenes/",
    ]


def test_an_unresolved_uuid_or_a_wrong_level_is_reported(ws: Workspace, client: None) -> None:  # noqa: F811
    block = copy.deepcopy(GOOD)
    block["creatures"] = [{"uuid": "Compendium.sys.bestiary.Actor.zzz", "name": "Gob"}]
    block["encounters"][0]["creatures"][0]["level"] = 2

    problems = lint(ws, block)["problems"]

    assert "Actor.zzz (creatures): not found in the compendium" in problems[0]
    assert "level 2 but the entry is 1" in problems[1]


def test_without_a_client_uuids_are_unchecked_not_failed(ws: Workspace) -> None:  # noqa: F811
    result = lint(ws, GOOD)

    assert result["ok"]
    assert len(result["unchecked"]) == 3 and "no GM client" in result["unchecked"][0]
    assert result["encounters"][0]["xp"] == 80  # the maths still runs


def guide(camp: Workspace, text: str, cites: list[str]) -> Any:
    note(camp, {"cites": cites}, "players-guide", text)
    return call(camp, "check_prep_guide", path="adventure-x/players-guide.md")


def test_the_guide_guard_refuses_a_planted_secret_and_a_canary(ws: Workspace) -> None:  # noqa: F811
    tovan, mira = entity(ws, "Tovan Reed"), entity(ws, "Mira Pell")
    known = fact(ws, "Tovan Reed keeps the lighthouse.", entities=[tovan])
    learn(ws, "party", known)
    fact(ws, "Mira Pell sold the gate key.", entities=[mira])

    leak = guide(ws, "Beware Mira Pell. CANARY-guide-7", [known])

    assert leak.is_error
    assert "Mira Pell" in leak.content[0].text and "CANARY-guide-7" in leak.content[0].text


def test_the_guide_guard_refuses_a_cited_fact_the_party_does_not_know(ws: Workspace) -> None:  # noqa: F811
    secret = fact(ws, "The mayor is a cultist.", entities=[])

    refused = guide(ws, "A quiet town.", [secret])

    assert refused.is_error and "does not know" in refused.content[0].text


def test_a_clean_guide_passes(ws: Workspace) -> None:  # noqa: F811
    tovan = entity(ws, "Tovan Reed")
    known = fact(ws, "Tovan Reed keeps the lighthouse.", entities=[tovan])
    learn(ws, "party", known)

    clean = guide(ws, "Tovan Reed keeps the lighthouse; bring a lantern.", [known])

    assert not clean.is_error
    assert clean.structured_content == {known: "knows"}


def test_the_cli(ws: Workspace, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    note(ws, GOOD | {"clues": ["clue-9"]})
    assert main(["prep", "check", "adventure-x/dossier.md", "-w", str(ws.root)]) == 1
    assert "clue-9" in capsys.readouterr().out

    note(ws, {"cites": []}, "players-guide", "Bring a lantern. CANARY-g-1")
    assert main(["prep", "guard", "adventure-x/players-guide.md", "-w", str(ws.root)]) == 1
    assert "CANARY-g-1" in capsys.readouterr().err


def test_the_playbook_is_a_standard_prep_task() -> None:
    from secondchair import runner

    meta = runner.playbook("prepare-an-adventure")
    assert (meta["tier"], meta["responsibility"]) == ("standard", "prep")


def test_adventure_and_session_playbooks_onboard_the_gm() -> None:
    """A title (never a path), one up-front question, a plan before the deep run."""
    from secondchair import runner

    assert "session_count?" in runner.playbook("prepare-an-adventure")["inputs"]
    skills = {s.name: (s / "SKILL.md").read_text() for s in runner.skills()}
    adventure = skills["prepare-an-adventure"]
    assert "never invent a path" in adventure and "## Ask once, up front" in adventure
    assert "check_prep_guide" in adventure
    session = skills["prepare-a-session"]
    assert "## Plan first" in session and "check_audience_content" in session
    assert "call `finish_job` listing the candidate titles" in adventure
    assert "starts with `notes/` and ends in `.md`" in adventure
    assert "write no encounter blocks" in adventure
    assert "there is no job id" in session
    assert session.index("## What canon says") < session.index("## Plan first")
    assert session.index("## Plan first") < session.index("## The handoff")
    assert "or a note that `supersedes` one that had it" in adventure
    assert "leaving out any note that another note `supersedes`" in adventure
    direction = skills["develop-campaign-direction"]
    assert direction.count("keeps `alternatives: campaign-direction`") == 2
