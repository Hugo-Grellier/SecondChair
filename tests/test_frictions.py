"""Friction detectors and GM effort from behaviour traces (TRC-03, TRC-06; ADR 0012)."""

import asyncio
import json
import re
from pathlib import Path

import pytest
import yaml
from mcp import Client

from secondchair import runner
from secondchair.cli import main
from secondchair.core import delegation, frictions, traces
from secondchair.core import workspace as wsmod
from secondchair.core.server import build_server

FIXTURES = Path(__file__).parent / "fixtures/frictions"
T0 = 1_760_000_000_000
GM, ALICE = "gm00000000000001", "alice0000000001"


def recorded(name: str) -> list[dict]:
    return [json.loads(line) for line in (FIXTURES / f"{name}.jsonl").read_text().splitlines()]


def spans(found: list[dict]) -> list[tuple[str, int, int]]:
    return [(f["detector"], f["from"] - T0, f["to"] - T0) for f in found]


def test_each_gm_detector_fires_on_the_recorded_fixture_and_cites_its_span() -> None:
    found = frictions.detect(recorded("gm"), GM, True, "live-session", frictions.DEFAULTS)
    assert sorted(spans(found), key=lambda s: s[1]) == [
        ("rules_lookup", 0, 5_000),
        ("hunting", 100_000, 120_000),
        ("manual_correction", 200_000, 205_000),
        ("manual_correction", 210_000, 210_000),
        ("long_creature_turn", 300_000, 400_000),
        ("dead_time", 301_000, 330_000),
    ]
    assert {f["detector"] for f in found} == set(frictions.GM_DETECTORS)


def test_each_player_detector_fires_on_the_recorded_fixture_and_cites_its_span() -> None:
    found = frictions.detect(recorded("player"), ALICE, False, "live-session", frictions.DEFAULTS)
    assert sorted(spans(found), key=lambda s: s[1]) == [
        ("long_turn", 0, 150_000),
        ("hunting", 200_000, 220_000),
        ("cancelled_roll_dialog", 300_000, 300_000),
        ("targeting_fixed", 400_000, 403_000),
        ("rage_clicks", 500_000, 501_000),
        ("click_on_nothing", 600_000, 600_000),
        ("rules_lookup", 700_000, 702_000),
        ("stumbling_input", 800_000, 801_800),
    ]
    assert {f["detector"] for f in found} == set(frictions.PLAYER_DETECTORS)


def test_gm_rules_lookups_count_only_in_live_play() -> None:
    found = frictions.detect(recorded("gm"), GM, True, "prep", frictions.DEFAULTS)
    assert "rules_lookup" not in {f["detector"] for f in found}


def test_thresholds_are_tunable_per_campaign(tmp_path: Path) -> None:
    ws = wsmod.init(tmp_path, "en", "absalom")
    config = tmp_path / "workspace.yaml"
    config.write_text(config.read_text() + "frictions:\n  long_creature_turn: {over: 120}\n")
    limits = frictions.thresholds(ws)
    assert limits["long_creature_turn"] == {"over": 120}
    assert limits["hunting"] == frictions.DEFAULTS["hunting"]
    found = frictions.detect(recorded("gm"), GM, True, "live-session", limits)
    assert "long_creature_turn" not in {f["detector"] for f in found}
    config.write_text(config.read_text() + "  hunted: {}\n")
    with pytest.raises(wsmod.WorkspaceError, match="hunted"):
        frictions.thresholds(ws)


def test_secondchair_own_windows_and_acts_are_not_manual_acts() -> None:
    # Two rolls; the Desk's windows and the move SecondChair made through this client are not.
    assert frictions.manual_acts(recorded("gm")) == 2


def _store(campaign: str, user: str, name: str, gm: bool, records: list[dict]) -> None:
    traces.record_lines(campaign, user, name, gm, records)


def test_the_report_counts_gm_effort_and_table_friction(
    tmp_path: Path, machine_config: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", machine_config["XDG_DATA_HOME"])
    ws = wsmod.init(tmp_path / "ws", "en", "absalom")
    delegation.change_moment(ws, "live-session")
    (ws.root / "foundry.yaml").write_text("world: w\ncampaign: c0ffee\n")
    _store("c0ffee", GM, "Gamemaster", True, recorded("gm"))
    _store("c0ffee", ALICE, "Alice", False, recorded("player"))
    # One Director's Desk approval: one GM interaction, its trace events counted nowhere else.
    delegation._interaction(ws, "approve", None, "cli", True, None, None)
    path = traces.report(ws, "c0ffee", 2, "live-session")
    front = yaml.safe_load(path.read_text().split("---")[1])
    assert front["gm_effort"] == {"interactions": 1, "manual_acts": 2, "frictions": 6}
    assert front["table_friction"] == 8
    first = next(f for f in front["frictions"] if f["role"] == "gm")
    assert first == {
        "id": 2,  # after Alice's long turn, which starts at the same time
        "detector": "rules_lookup",
        "user": GM,
        "name": "Gamemaster",
        "role": "gm",
        "from": T0,
        "to": T0 + 5_000,
    }
    body = path.read_text().split("---", 2)[2]
    assert "Alice" in body and "Gamemaster" in body


def test_ending_a_moment_writes_its_report(
    tmp_path: Path, machine_config: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", machine_config["XDG_DATA_HOME"])
    ws = wsmod.init(tmp_path / "ws", "en", "absalom")
    delegation.change_moment(ws, "live-session")
    (ws.root / "foundry.yaml").write_text("world: w\ncampaign: c0ffee\n")
    _store("c0ffee", ALICE, "Alice", False, recorded("player"))
    delegation.change_moment(ws, "between-sessions")
    assert (ws.root / "frictions/000002.md").is_file()
    assert not (ws.root / "frictions/000003.md").exists()  # no traces in it yet


def test_the_cli_writes_a_moments_report_on_demand(
    tmp_path: Path, machine_config: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", machine_config["XDG_DATA_HOME"])
    ws = wsmod.init(tmp_path / "ws", "en", "absalom")
    delegation.change_moment(ws, "live-session")
    (ws.root / "foundry.yaml").write_text("world: w\ncampaign: c0ffee\n")
    _store("c0ffee", ALICE, "Alice", False, recorded("player"))
    assert main(["frictions", "-w", str(ws.root)]) == 0
    assert (ws.root / "frictions/000002.md").is_file()
    assert main(["frictions", "-w", str(ws.root), "1"]) == 1  # no traces in prep


def test_the_diagnostic_playbook_only_proposes(tmp_path: Path) -> None:
    """TRC-06: the playbook names no tool that changes anything but its own job's status, and
    leaves the delegation table to the GM."""
    ws = wsmod.init(tmp_path, "en", "absalom")

    async def list_tools() -> list:
        async with Client(build_server(ws)) as client:
            return (await client.list_tools()).tools

    writes = {
        t.name
        for t in asyncio.run(list_tools())
        if {"secondchair/delegated_action", "secondchair/gm_interaction", "secondchair/job"}
        & {k for k, v in (t.meta or {}).items() if v}
    } - {"start_job", "finish_job"}
    assert {"add_entity_override", "approve_proposal", "record_fact"} <= writes
    [skill] = [s for s in runner.skills() if s.name == "diagnose-frictions"]
    text = (skill / "SKILL.md").read_text()
    assert not set(re.findall(r"`([a-z_]+)`", text)) & writes
    assert "never edit `delegation.yaml`" in text
    assert runner.playbook("diagnose-frictions")["inputs"] == "report"
