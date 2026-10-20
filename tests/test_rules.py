"""Rules checks on recorded traces, discrepancies and house rules (RUL-13..20, RUL-23, RUL-24)."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from test_calls import gm, log, open_calls, set_cell, ws  # noqa: F401 (fixture)

from secondchair.core import calls, delegation, observations, rules
from secondchair.core.workspace import Workspace
from secondchair_pf2e import checks, readers

ROOT = Path(__file__).parents[1]
OUTCOME = json.loads((ROOT / "docs/contracts/pf2e-outcome.schema.json").read_text())
ENVELOPE = json.loads((ROOT / "docs/contracts/event-envelope.schema.json").read_text())
RECORDED = yaml.safe_load((ROOT / "tests/fixtures/pf2e-outcomes.yaml").read_text())
SESSION = [case["envelope"] for case in RECORDED]


def replay(envelope: dict, session: list[dict] = SESSION) -> list[str]:
    return [kind for kind, _ in checks.check(envelope, lambda: session)]


def by_id(id_: str) -> dict:
    return copy.deepcopy(next(e for e in SESSION if e["id"] == id_))


@pytest.mark.parametrize("case", RECORDED, ids=[c["envelope"]["id"] for c in RECORDED])
def test_each_recorded_trace_replays_to_its_expected_checks(case: dict) -> None:
    jsonschema.validate(case["envelope"], ENVELOPE, format_checker=jsonschema.FormatChecker())
    jsonschema.validate(case["envelope"]["payload"], OUTCOME)
    assert replay(case["envelope"]) == case["expect"]


def test_every_check_kind_has_a_failing_recorded_trace() -> None:
    assert {kind for case in RECORDED for kind in case["expect"]} == set(checks.CHECKS)


def test_a_discrepancy_names_its_inconsistency() -> None:
    [(_, text)] = checks.check(by_id("damage-unresisted"), lambda: SESSION)
    assert "15 damage with -5 from IWR should cost 10 HP" in text and "15 HP were lost" in text


def test_a_house_rule_in_the_trace_is_consistent() -> None:
    """Evasion recorded in dosAdjustments raises the degree: consistent (RUL-23)."""
    assert replay(by_id("save-evasion")) == []
    raised = by_id("save-evasion")
    raised["payload"]["flags"]["pf2e"]["dosAdjustments"] = {}
    assert replay(raised) == ["degree"]


def test_an_unknown_toolbelt_format_is_silent_and_the_pf2e_trace_is_still_checked() -> None:
    drifted = by_id("toolbelt-save")
    helper = drifted["payload"]["flags"]["pf2e-toolbelt"]["targetHelper"]
    helper["saveVariants"] = {"fortitude": {"dc": "25", "saves": {}}}  # a new format
    assert readers.toolbelt_saves(drifted["payload"]) is None
    assert replay(drifted) == []
    summed = by_id("strike-sum")
    summed["payload"]["flags"]["pf2e-toolbelt"] = {"targetHelper": {"saves": [1]}}
    assert replay(summed) == ["modifiers"]


def test_unknown_dos_adjustments_fall_back_to_the_unadjusted_degree() -> None:
    raised = by_id("degree-raised")
    raised["payload"]["flags"]["pf2e"]["dosAdjustments"] = {"failure": {"amount": "up"}}
    assert readers.dos_adjustments(raised["payload"]) is None
    assert replay(raised) == []  # the adjusted degree is unchecked without its reader
    raised["payload"]["unadjusted"] = "success"  # but the pf2e trace alone still is
    assert replay(raised) == ["degree"]


def test_readers_of_visibility_cover_and_reactions() -> None:
    payload = {
        "flags": {
            "pf2e-visioner": {"visibility": {"t2": "hidden"}, "cover": {"t2": "standard"}},
            "pf2e-reaction": {"state": True},
            "pf2e-combater": {"reactionUsed": True},
        }
    }
    seen = {"visibility": {"t2": "hidden"}, "cover": {"t2": "standard"}}
    assert readers.visioner(payload) == seen
    assert readers.reaction_used(payload) is True
    assert readers.reaction_used({"flags": {"sundry": {"effects": ["effect-mage-armor"]}}}) is False
    assert readers.reaction_used({"flags": {"pf2e-combater": {"reactionUsed": "yes"}}}) is None
    assert readers.visioner({"flags": {"pf2e-visioner": {"visibility": {"t2": {"v": 2}}}}}) is None


def test_a_planted_inconsistency_is_a_discrepancy_held_for_the_break(ws: Workspace) -> None:  # noqa: F811
    delegation.start_session(ws)
    assert observations.record(ws, by_id("degree-raised")) is None
    assert observations.record(ws, by_id("degree-raised")) is None  # resent: checked once
    [call] = open_calls(ws)
    assert call["kind"] == "discrepancy" and call["responsibility"] == "rules_and_combat"
    assert (call["deadline"], call["interruption"], call["check"]) == ("break", False, "degree")
    assert call["observation"] == "observations/000001.jsonl#degree-raised"
    calls.move_on(ws)
    assert open_calls(ws)[0]["status"] == "open"
    assert [c["id"] for c in calls.take_break(ws)] == [call["id"]]


def test_a_discrepancy_can_be_forced_now(ws: Workspace) -> None:  # noqa: F811
    set_cell(ws, "rules_and_combat", deadline="now")
    delegation.start_session(ws)
    observations.record(ws, by_id("strike-sum"))
    [call] = open_calls(ws)
    assert (call["deadline"], call["interruption"]) == ("now", True)


def test_fixing_a_discrepancy_is_a_proposal_whatever_the_level(ws: Workspace) -> None:  # noqa: F811
    set_cell(ws, "rules_and_combat", level="autonomous")
    delegation.start_session(ws)
    observations.record(ws, by_id("damage-unresisted"))
    [discrepancy] = open_calls(ws)
    hp = {"system.attributes.hp.value": 10}
    done = rules.propose_fix(ws, discrepancy["id"], "set_actor", "Actor.sella", hp, "claude-rules")
    assert done["status"] == "pending"
    entry = log(ws)[-1]
    assert (entry["op"], entry["target"], entry["after"]) == ("set_actor", "Actor.sella", hp)
    found = {c["id"]: c for c in open_calls(ws)}
    assert found[discrepancy["id"]]["status"] == "answered"
    proposal = found[discrepancy["id"] + 1]
    assert proposal["kind"] == "proposal" and proposal["entry"] == entry["id"]
    assert proposal["message"].startswith(f"fix for discrepancy {discrepancy['id']}: ")
    with pytest.raises(delegation.DelegationError, match="not an open discrepancy"):
        rules.propose_fix(ws, discrepancy["id"], "set_actor", "Actor.sella", hp, "claude-rules")


def test_a_house_rule_silences_its_check_until_removed(ws: Workspace, capsys) -> None:  # noqa: F811
    delegation.start_session(ws)
    observations.record(ws, by_id("degree-raised"))
    [call] = open_calls(ws)
    mark = ("house-rule", "mark", str(call["id"]), "Heroic nudge")
    assert gm(*mark, root=ws.root, interactive=False) == 1
    assert "authenticated" in capsys.readouterr().err
    assert gm(*mark, root=ws.root) == 0
    assert open_calls(ws)[0]["status"] == "answered"
    assert gm("house-rule", "list", root=ws.root) == 0
    assert "Heroic nudge  silences degree checks" in capsys.readouterr().out
    again = by_id("degree-raised") | {"id": "degree-raised-again"}
    observations.record(ws, again)
    assert len(open_calls(ws)) == 1  # silenced
    observations.record(ws, by_id("strike-sum"))  # another kind still raises
    assert [c["check"] for c in open_calls(ws)[1:]] == ["modifiers"]
    assert gm("house-rule", "remove", "Heroic nudge", root=ws.root, interactive=False) == 0
    observations.record(ws, by_id("degree-raised") | {"id": "degree-raised-third"})
    assert [c["check"] for c in open_calls(ws)[1:]] == ["modifiers", "degree"]
    added, removed = (e for e in log(ws) if e["kind"] == "gm_interaction")
    assert (added["interaction"], removed["interaction"]) == ("add_house_rule", "remove_house_rule")
    assert added["house_rule"] == {"name": "Heroic nudge", "check": "degree", "call": call["id"]}
    assert yaml.safe_load((ws.root / rules.HOUSE_RULES_FILE).read_text()) == {"house_rules": []}


def test_a_broken_checker_never_loses_the_observation(ws: Workspace, capsys) -> None:  # noqa: F811
    delegation.start_session(ws)
    broken = by_id("strike-ok")
    broken["payload"]["roll"] = {"total": 3}
    assert observations.record(ws, broken) is None
    assert observations.find(ws, "observations/000001.jsonl#strike-ok") is not None
    assert "rules check failed on strike-ok" in capsys.readouterr().err
    assert open_calls(ws) == []


def test_unreadable_house_rules_never_lose_the_observation(ws: Workspace, capsys) -> None:  # noqa: F811
    delegation.start_session(ws)
    (ws.root / rules.HOUSE_RULES_FILE).write_text("house_rules: foo\n")
    assert observations.record(ws, by_id("strike-sum")) is None
    assert observations.find(ws, "observations/000001.jsonl#strike-sum") is not None
    assert "rules checks not run on strike-sum" in capsys.readouterr().err


def test_a_standing_lifecycle_break_is_reported_once() -> None:
    stuck = by_id("frightened-zero")
    stuck["payload"]["conditions"] = {
        "before": {"frightened": 0},
        "after": {"frightened": 0, "off-guard": None},
    }
    assert replay(stuck) == []
    stuck["payload"]["conditions"]["after"]["dying"] = 1
    assert replay(stuck) == ["conditions"]


def test_an_activity_is_held_only_to_the_next_condition_change_of_its_target() -> None:
    applied = by_id("frightened-zero") | {"id": "frightened-one"}
    applied["payload"]["conditions"] = {"before": {}, "after": {"frightened": 1}}
    later = by_id("frightened-two")
    session = [*SESSION[:-1], applied, later]
    assert replay(applied, session) == []
    assert replay(later, session) == []  # a later fright is not the demoralize's
