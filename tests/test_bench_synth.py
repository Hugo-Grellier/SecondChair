"""The synthetic campaign generator, the scaling bench and the temporal recall bench (#195)."""

import importlib.util
from pathlib import Path

import pytest

from secondchair.bench import recall, scale, synth
from secondchair.core import delegation, index, world
from secondchair.core.workspace import STATE_DIR

SCRIPTS = Path(__file__).parents[1] / "scripts"


def tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and STATE_DIR not in p.parts
    }


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> synth.Synth:
    return synth.generate(tmp_path_factory.mktemp("synth") / "workspace", "S")


def test_two_runs_with_one_seed_write_byte_identical_workspaces(
    made: synth.Synth, tmp_path: Path
) -> None:
    again = synth.generate(tmp_path / "workspace", "S")
    assert tree(again.ws.root) == tree(made.ws.root)
    assert again.gold == made.gold
    other = synth.generate(tmp_path / "other", 3, seed=1)
    assert tree(other.ws.root) != tree(made.ws.root)


def test_a_campaign_has_what_the_note_describes(made: synth.Synth) -> None:
    ws = made.ws
    assert delegation.last_session(ws) == made.sessions == synth.SIZES["S"]
    assert not index.rebuild(ws)  # every document is valid canon
    assert made.stats["retcons"] >= 1 and made.stats["rumours"] >= 1
    assert made.stats["promises"] >= 1 and made.stats["pairs"] >= 1
    events = index.search_events(ws)
    assert "replaced" in {e["status"] for e in events}  # a confirmed retcon
    assert len(world.state(ws)["fronts"]) >= 3
    assert len(list((ws.root / "action-log").glob("*.yaml"))) > 100
    dates = [e["date"] for e in events]
    assert dates and max(dates) <= made.final_date


def test_the_living_world_follows_the_generator_model(made: synth.Synth) -> None:
    ws, cal = made.ws, made.ws.calendar
    for front in made.fronts:
        ticks, day = 0, cal.add(front["anchor"], f"{front['every']}d")
        while cal.diff(day, made.final_date) >= 0 and ticks < front["capacity"]:
            ticks, day = ticks + 1, cal.add(day, f"{front['every']}d")
        seen = world.state(ws)["fronts"][front["entity"]]
        assert seen["clock"] == ticks
        assert seen["agenda"]["turning-point"] == (
            "done" if ticks >= front["step_at"] else "pending"
        )


def test_the_setting_is_original(made: synth.Synth) -> None:
    spec = importlib.util.spec_from_file_location("guard", SCRIPTS / "guard_sample_campaign.py")
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    for folder in ("canon", "action-log", "occurrences", "jobs"):
        assert guard.offences(made.ws.root / folder) == []


def test_the_core_answers_the_generated_gold_set(made: synth.Synth) -> None:
    found = recall.score(made.ws, made.gold)
    assert found["failures"] == []
    assert found["invariants"]
    kinds = {kind for kind, _ in found["tally"]}
    assert kinds >= {"current_relation", "retcon", "delayed_revelation", "promise", "belief"}
    assert {view for _, view in found["tally"]} == {"gm", "party"}


def test_a_wrong_gold_answer_is_a_failure_and_breaks_an_invariant(made: synth.Synth) -> None:
    wrong = [
        {**q, "expect": not q["expect"]} if q["kind"] == "delayed_revelation" else q
        for q in made.gold
    ]
    found = recall.score(made.ws, wrong)
    assert found["failures"] and not found["invariants"]


def test_the_scaling_report_has_a_row_per_size(tmp_path: Path) -> None:
    row = scale.measure("S")
    assert row["Size"] == "S (10)"
    assert int(row["Files"]) > 100 and int(row["Bytes"]) > 0
    for column in ("search_facts p50 / p95 (ms)", "what_knows p50 / p95 (ms)"):
        p50, p95 = (float(v) for v in row[column].split(" / "))
        assert 0 < p50 <= p95
    assert recall.run(["S"])[0]
