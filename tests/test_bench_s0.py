"""The S0 harness (BEN-01..04, MET-01, MET-03, MET-05, MET-05a, ARC-30), driven through the
`secondchair bench` CLI against the scripted fake runner, as CI runs it (BEN-06)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from secondchair import cli
from secondchair.bench import harness, s0
from secondchair.core import canon, delegation, workspace

SAMPLE = Path(__file__).parents[1] / "sample-campaign"
METRICS = (
    "gm_effort",
    "entity_recall",
    "entity_precision",
    "leaks",
    "narrative_direction",
    "fact_probes",
    "continuity_errors",
)


def bench(*args: str) -> int:
    return cli.main(["bench", *args])


def report(out: Path) -> dict:
    return json.loads((out / "report.json").read_text())


@pytest.fixture(scope="module")
def scripted(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("bench") / "s0"
    assert bench("s0", str(out), "--sample", str(SAMPLE), "--runner", "fake/scripted/none") == 0
    return out


def test_report_compares_the_delegated_table_with_the_baseline(scripted: Path) -> None:
    found = report(scripted)
    assert found["passed"] is True
    assert found["runner_configuration"] == {"host": "fake", "model": "scripted", "effort": "none"}
    for table in ("delegated", "baseline"):
        assert len(found["tables"][table]["runs"]) == 3
        for metric in METRICS:
            assert set(found["tables"][table][metric]) == {"median", "min", "max"}
    delegated, baseline = found["tables"]["delegated"], found["tables"]["baseline"]
    # The scripted GM creates by hand the 26 named entities of the gold set (BEN-03).
    assert baseline["gm_effort"] == {"median": 26, "min": 26, "max": 26}
    assert delegated["gm_effort"]["median"] == 0  # memory is act-then-review at prep
    assert found["gain"] == {"gm_effort": True}
    # The fake creates the 26 named entities and one extra, the festival month.
    assert delegated["entity_recall"]["median"] == 1.0
    assert delegated["entity_precision"]["median"] == pytest.approx(26 / 27)
    assert delegated["leaks"] == {"median": 0, "min": 0, "max": 0}
    assert (scripted / "report.md").read_text().startswith("# S0 bench report")


def test_the_fact_probes_are_asked_and_scored_but_not_gated(scripted: Path) -> None:
    found = report(scripted)
    asked = yaml.safe_load((scripted / "delegated/1/probes.yaml").read_text())
    assert list(asked) == list(s0.FACT_PROBES)
    assert "expected" not in str(asked) and "npc-mira" not in str(asked)  # never the gold
    # The fake records the factions and situations, and answers those two probes from canon.
    for run in found["tables"]["delegated"]["runs"]:
        assert [p for p, ok in run["probes"].items() if ok] == ["factions", "situations"]
        assert run["continuity_errors"] == len(s0.FACT_PROBES) - 2
    assert found["tables"]["delegated"]["fact_probes"]["median"] == 2
    # The baseline's hand-made canon holds no fact: every probe fails, and the run still passes.
    assert found["tables"]["baseline"]["fact_probes"]["max"] == 0
    assert found["passed"] is True


def test_a_reply_answers_with_its_last_json_object() -> None:
    reply = 'Done: 2 probes.\n{"factions": {"e-1": ["e-2"]}, "situations": {}}\n'
    assert s0.parse_answers(reply) == {"factions": {"e-1": ["e-2"]}, "situations": {}}
    assert s0.parse_answers("I could not answer.") == {}


def test_a_passing_run_writes_the_mapping_in_runner_configuration_format(scripted: Path) -> None:
    mapping = yaml.safe_load((scripted / "mapping.yaml").read_text())
    config = {"host": "fake", "model": "scripted", "effort": "none"}
    assert mapping["runners"] == {tier: [config] for tier in ("fast", "standard", "deep")}


def test_the_report_is_recomputed_from_the_stored_action_logs(
    scripted: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "s0"
    shutil.copytree(scripted, copy)
    expected = report(copy)
    (copy / "report.json").unlink()
    for stored in copy.glob("*/*/workspace/canon"):
        shutil.rmtree(stored)  # only the action log remains
    # No agent can run: the runner is not importable while the report is recomputed.
    script = (
        "import sys; from pathlib import Path; sys.modules['secondchair.runner'] = None; "
        "from secondchair.bench import report; report.recompute(Path(sys.argv[1]))"
    )
    subprocess.run([sys.executable, "-c", script, str(copy)], check=True)
    assert report(copy) == expected


def test_a_planted_canary_in_an_agent_output_fails_the_run(tmp_path: Path) -> None:
    out = tmp_path / "s0"
    assert bench("s0", str(out), "--sample", str(SAMPLE), "--runner", "fake/leaky/none") == 1
    found = report(out)
    assert found["passed"] is False
    assert found["tables"]["delegated"]["leaks"]["min"] >= 1
    assert not (out / "mapping.yaml").exists()


def test_no_other_metric_fails_the_run(tmp_path: Path) -> None:
    out = tmp_path / "s0"
    assert bench("s0", str(out), "--sample", str(SAMPLE), "--runner", "fake/idle/none") == 0
    found = report(out)
    assert found["passed"] is True
    assert found["tables"]["delegated"]["entity_recall"]["max"] == 0


def test_the_scripted_gm_approves_gold_entities_and_rejects_the_rest(tmp_path: Path) -> None:
    gold = yaml.safe_load((SAMPLE / "gold.yaml").read_text())
    campaign = yaml.safe_load((SAMPLE / "campaign.yaml").read_text())
    ws = workspace.init(tmp_path / "ws", campaign["campaign_language"], campaign["calendar"])
    table = yaml.safe_load((ws.root / delegation.TABLE_FILE).read_text())
    table["prep"]["memory"]["level"] = "propose"
    (ws.root / delegation.TABLE_FILE).write_text(yaml.safe_dump(table))
    [tool] = [t for t in canon.tools(ws) if t.name == "create_entity"]
    entries = [
        delegation.act(ws, tool, "agent", lambda n=name: tool.fn(names=[n]))["entry"]
        for name in ("Mira Pell", "Bellnight")
    ]
    harness.answer_calls(ws, gold)
    statuses = [delegation.read_entry(ws, e)["status"] for e in entries]
    assert statuses == ["applied", "rejected"]
