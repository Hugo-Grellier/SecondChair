"""Friction detectors, GM manual acts and the diagnostic playbook (TRC-03, TRC-06; ADR 0012).

The fixtures under fixtures/traces/ are records as the Foundry module sends them
(foundry-bridge.md, "Behaviour traces"): one GM's and one player's, each detector's case spaced
out in time, `t` in milliseconds from T0.
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from test_observations import BRIDGE

from secondchair import runner
from secondchair.core import delegation, frictions, traces
from secondchair.core import workspace as wsmod
from secondchair.core.workspace import WorkspaceError

FIXTURES = Path(__file__).parent / "fixtures/traces"
T0 = 1_760_000_000_000
GM, PLAYER = "gm00000000000001", "alice0000000001"
CAMPAIGN = "c0ffee"


def fixture(name: str) -> list[dict]:
    return [json.loads(line) for line in (FIXTURES / f"{name}.jsonl").read_text().splitlines()]


def message(user: str, name: str, records: list[dict], gm: bool) -> dict:
    sent = {"type": "traces", "user": user, "name": name, "gm": gm, "records": records}
    BRIDGE.validate(sent)
    return sent


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> wsmod.Workspace:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return wsmod.init(tmp_path / "campaign", "en", "absalom")


def report(ws: wsmod.Workspace) -> dict:
    moment, seq = delegation.current_moment(ws)
    text = traces.report(ws, CAMPAIGN, seq, moment).read_text()
    return yaml.safe_load(text.split("---")[1]) | {"body": text.split("---", 2)[2]}


def spans(front: dict, user: str) -> list[tuple[str, int, int]]:
    return [
        (f["detector"], f["from"] - T0, f["to"] - T0)
        for f in front["frictions"]
        if f["user"] == user
    ]


def test_each_detector_fires_on_a_recorded_fixture_and_cites_its_trace_span(
    ws: wsmod.Workspace,
) -> None:
    delegation.start_session(ws)
    traces.record(ws, CAMPAIGN, message(GM, "Gamemaster", fixture("gm"), gm=True))
    traces.record(ws, CAMPAIGN, message(PLAYER, "Alice", fixture("player"), gm=False))
    front = report(ws)
    assert spans(front, GM) == [
        ("rules-lookup", 1000, 1000),
        ("hunting", 10000, 15000),
        ("manual-correction", 20000, 23000),
        ("manual-correction", 30000, 35000),
        ("long-gm-creature-turn", 40000, 140000),
        ("dead-time", 41000, 70000),
    ]
    assert spans(front, PLAYER) == [
        ("long-turn", 1000, 130000),
        ("hunting", 140000, 145000),
        ("cancelled-roll-dialog", 150000, 150000),
        ("rage-clicks", 160000, 161000),
        ("click-on-nothing", 170000, 170000),
        ("late-targeting", 180000, 183000),
        ("rules-lookup", 190000, 190000),
        ("stumbling-input", 200000, 204000),
    ]
    # Every detector of the closed list fires, and every span is the t of traced records.
    assert {d for d, *_ in spans(front, GM)} == set(frictions.GM)
    assert {d for d, *_ in spans(front, PLAYER)} == set(frictions.PLAYER)
    times = {r["t"] for name in ("gm", "player") for r in fixture(name)}
    assert all(f["from"] in times and f["to"] in times for f in front["frictions"])
    assert front["table_friction"] == 8
    assert (
        "late-targeting: Alice, 2025-10-09T08:56:20.000Z to 2025-10-09T08:56:23.000Z."
        in (front["body"])
    )


def test_gm_rules_lookups_count_in_live_play_only(ws: wsmod.Workspace) -> None:
    traces.record(ws, CAMPAIGN, message(GM, "Gamemaster", fixture("gm"), gm=True))
    assert "rules-lookup" not in [d for d, *_ in spans(report(ws), GM)]


def test_an_act_between_windows_is_not_hunting() -> None:
    def window(t: int, w: str) -> list[dict]:
        return [
            {"t": t, "stream": "semantic", "event": "window.open", "window": w},
            {"t": t + 500, "stream": "semantic", "event": "window.close", "window": w},
        ]

    roll = {"t": 2600, "stream": "semantic", "event": "roll", "formulas": ["1d20"]}
    records = [*window(1000, "a"), *window(2000, "b"), roll, *window(3000, "c")]
    assert frictions.detect(records, False, "live-session", frictions.THRESHOLDS) == []


def test_the_directors_desk_is_not_hunting_and_bad_fields_never_stop_the_report() -> None:
    desk = [
        {"t": t, "stream": "semantic", "event": e, "window": "secondchair-desk"}
        for t in (1000, 2000, 3000)
        for e in ("window.open", "window.close")
    ]
    bad = [
        {"t": 4000, "stream": "input", "input": "click", "x": "a", "y": [1], "target": 7},
        {"t": 4001, "stream": "semantic", "event": "window.open", "window": [1]},
        {"t": 4002, "stream": "semantic", "event": "roll", "formulas": [[1]]},
        {"t": 4003, "stream": "semantic", "event": "roll", "formulas": "1d20"},
        {"t": 4004, "stream": "input", "input": "click", "x": 0, "y": 0, "target": "canvas"},
        {"t": 4005, "stream": "input", "input": "click", "x": 0, "y": 0, "target": "canvas"},
        {"t": 4005, "stream": "input", "input": "click", "x": 0, "y": 0, "target": "canvas"},
    ]
    found = frictions.detect(desk + bad, False, "live-session", frictions.THRESHOLDS)
    assert [(f["detector"], f["from"], f["to"]) for f in found] == [("rage-clicks", 4000, 4005)]
    assert frictions.manual_acts(desk + bad) == 2


def test_thresholds_are_tunable_per_campaign(ws: wsmod.Workspace) -> None:
    config = ws.root / wsmod.CONFIG_FILE
    data = yaml.safe_load(config.read_text())
    config.write_text(yaml.safe_dump(data | {"friction_thresholds": {"player_turn_s": 200}}))
    traces.record(ws, CAMPAIGN, message(PLAYER, "Alice", fixture("player"), gm=False))
    assert "long-turn" not in [d for d, *_ in spans(report(ws), PLAYER)]
    config.write_text(yaml.safe_dump(data | {"friction_thresholds": {"turn_s": 200}}))
    with pytest.raises(WorkspaceError, match="friction_thresholds"):
        report(ws)


def test_gm_manual_acts_count_in_gm_effort_and_a_desk_interaction_counts_once(
    ws: wsmod.Workspace,
) -> None:
    delegation.start_session(ws)
    # The GM approves a held move on the Director's Desk: one logged GM interaction.
    delegation.set_hold(ws, "vtt_operations", "live-session", True, "desk", True, None)
    move = {"t": T0 + 2000, "stream": "semantic", "event": "move", "token": "Scene.s.Token.t"}
    records = [
        # The Desk gesture: a click in the Desk, then the VTT write SecondChair made with the
        # GM's client, tagged so it is not the GM's manual act.
        {
            "t": T0 + 1000,
            "stream": "input",
            "input": "click",
            "button": 0,
            "x": 9,
            "y": 9,
            "target": "button[data-action=approve]",
        },
        move | {"secondchair": True},
        # Then the GM's own acts in the VTT.
        move | {"t": T0 + 5000},
        {"t": T0 + 6000, "stream": "semantic", "event": "roll", "formulas": ["1d20+4"]},
        {"t": T0 + 7000, "stream": "semantic", "event": "pf2e.strike"},
        {"t": T0 + 8000, "stream": "semantic", "event": "window.open", "window": "w"},
    ]
    traces.record(ws, CAMPAIGN, message(GM, "Gamemaster", records, gm=True))
    # A player's acts are not GM effort.
    traces.record(ws, CAMPAIGN, message(PLAYER, "Alice", [move], gm=False))
    front = report(ws)
    assert front["gm_effort"] == {"interactions": 1, "manual_acts": 3}
    assert "4: 1 interactions with SecondChair" in front["body"]


def test_a_moments_report_is_written_once_the_next_moment_has_traces(
    ws: wsmod.Workspace,
) -> None:
    traces.record(ws, CAMPAIGN, message(PLAYER, "Alice", fixture("player"), gm=False))
    assert not (ws.root / "frictions/000001.md").exists()
    delegation.start_session(ws)
    traces.record(ws, CAMPAIGN, message(PLAYER, "Alice", fixture("player")[:1], gm=False))
    front = yaml.safe_load((ws.root / "frictions/000001.md").read_text().split("---")[1])
    assert front["moment"] == "prep" and front["table_friction"] == 8
    assert not (ws.root / "frictions/000002.md").exists()


def test_erasing_a_players_traces_removes_their_frictions(ws: wsmod.Workspace) -> None:
    traces.record(ws, CAMPAIGN, message(PLAYER, "Alice", fixture("player"), gm=False))
    assert report(ws)["table_friction"] == 8
    traces.erase(ws, CAMPAIGN, PLAYER)
    text = (ws.root / "frictions/000001.md").read_text()
    assert "Alice" not in text and "table_friction: 0" in text


# The diagnostic playbook (TRC-06)

PLAYBOOK = next(s for s in runner.skills() if s.name == "diagnose-frictions") / "SKILL.md"
# The only SecondChair tools it may name: taking and closing its job.
JOB_TOOLS = {"start_job", "finish_job"}


def test_the_diagnostic_playbook_only_proposes_delegation_table_changes() -> None:
    text = PLAYBOOK.read_text()
    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", text))
    assert named - {"campaign_language", "gm_effort", "manual_acts", "table_friction"} <= JOB_TOOLS
    assert "You propose only" in text
    assert "never change the delegation table" in text
    assert runner.playbook("diagnose-frictions")["inputs"] == "report"
    # It names every detector of the closed list.
    for detector in {*frictions.GM, *frictions.PLAYER}:
        assert f"`{detector}`" in text
