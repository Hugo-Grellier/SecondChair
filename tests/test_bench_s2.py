"""The S2 harness (BEN-05, 10-success-bench.md), Beginner Box prep, driven through the
`secondchair bench` CLI against the scripted fake runner and a stand-in bench world restore: CI
has no Foundry and no Beginner Box (BEN-06), so the scenario here is synthetic."""

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from secondchair import cli
from secondchair.core import machine

TEXT = "PURCHASED-SENTENCE of the Beginner Box."


@pytest.fixture
def scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private S2 scenario: the purchased module, the restore command and the gold set."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    module = tmp_path / "Data/modules/pf2e-beginner-box"
    (module / "packs/adventure").mkdir(parents=True)
    (module / "packs/adventure/000005.ldb").write_text(TEXT)
    config = machine.config_dir() / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(yaml.safe_dump({"purchased_content": [{"path": str(module)}]}))
    restored = tmp_path / "restored.log"
    restore = "import sys; open(sys.argv[1], 'a').write('restored\\n')"
    found = tmp_path / "s2"
    found.mkdir()
    definition = {
        "campaign_language": "en",
        "calendar": "absalom",
        "restore": [sys.executable, "-c", restore, str(restored)],
        "inputs": {
            "adventure": str(module),
            "party": "level 1, 4 PCs",
            "encounters": "goblin-ambush: the docks ambush; otari-cellar: the cellar",
        },
    }
    (found / "scenario.yaml").write_text(yaml.safe_dump(definition))
    keep = ["scenes/goblin-ambush.yaml", "scenes/otari-cellar.yaml"]
    (found / "gold.yaml").write_text(yaml.safe_dump({"keep": keep}))
    return found


def bench(*args: str) -> int:
    return cli.main(["bench", *args])


def test_s2_restores_its_world_each_run_and_reports_prep_metrics(
    scenario: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    assert bench("s2", str(out), "--scenario", str(scenario), "--runner", "fake/prep/none") == 0
    assert (tmp_path / "restored.log").read_text() == "restored\n" * 3
    found = json.loads((out / "report.json").read_text())
    assert found["scenario"] == "S2" and found["passed"] is True
    runs = found["runs"]
    assert len(runs) == 3
    # The fake prepares both gold encounters and one extra, which the scripted GM undoes, and
    # tries a door with no GM client connected: one failed action (ARC-09).
    assert found["prep_gm_effort"] == {"median": 1, "min": 1, "max": 1}
    assert found["baseline_gm_effort"] == 2  # one hand operation per gold operation (BEN-03)
    assert found["gain"] == {"prep_gm_effort": True}
    assert found["failed_actions"] == {"median": 1, "min": 1, "max": 1}
    assert found["acceptance_rate"]["median"] == pytest.approx(2 / 3)
    assert runs[0]["failed_by_responsibility"] == {"vtt_operations": 1}
    assert runs[0]["acceptance_by_responsibility"] == {"prep": pytest.approx(2 / 3)}
    assert (out / "report.md").read_text().startswith("# S2 bench report: passed")


def test_no_purchased_text_reaches_the_prep_job(scenario: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert (
        bench("s2", str(out), "--scenario", str(scenario), "-n", "1", "--runner", "fake/prep/none")
        == 0
    )
    [job] = list(out.glob("delegated/1/workspace/jobs/*.yaml"))
    inputs = yaml.safe_load(job.read_text())["inputs"]
    assert TEXT not in Path(inputs["adventure"]).read_text()
    assert "pf2e-beginner-box" not in json.dumps(inputs)


def test_the_report_is_recomputed_from_the_stored_action_logs(
    scenario: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    assert (
        bench("s2", str(out), "--scenario", str(scenario), "-n", "1", "--runner", "fake/prep/none")
        == 0
    )
    expected = json.loads((out / "report.json").read_text())
    shutil.rmtree(out / "delegated/1/workspace/scenes")
    (out / "report.json").unlink()
    assert bench("report", str(out)) == 0
    assert json.loads((out / "report.json").read_text()) == expected


def test_a_failed_restore_stops_the_bench(
    scenario: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    definition = yaml.safe_load((scenario / "scenario.yaml").read_text())
    definition["restore"] = [sys.executable, "-c", "raise SystemExit(3)"]
    (scenario / "scenario.yaml").write_text(yaml.safe_dump(definition))
    out = tmp_path / "out"
    assert bench("s2", str(out), "--scenario", str(scenario), "--runner", "fake/prep/none") == 1
    assert "bench world" in capsys.readouterr().err
    assert not list(out.glob("delegated/*/workspace"))
