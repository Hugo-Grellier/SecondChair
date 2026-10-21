"""Purchased content (LIC-12, LIC-16): indexed by metadata by default; its content reaches a job's
inputs only with the GM's explicit opt-in in the machine configuration."""

import json
from pathlib import Path

import pytest
import yaml

from secondchair import runner
from secondchair.cli import main
from secondchair.core import jobs, machine, workspace
from secondchair.core.workspace import Workspace

TEXT = "The goblins of the Otari docks hide a PURCHASED-SENTENCE."


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    main(["init", str(tmp_path / "campaign"), "--language", "en", "--calendar", "absalom"])
    return workspace.load(tmp_path / "campaign")


@pytest.fixture
def module(tmp_path: Path) -> Path:
    """A purchased Foundry module, as the GM's install holds it."""
    root = tmp_path / "Data/modules/pf2e-beginner-box"
    (root / "packs/adventure").mkdir(parents=True)
    (root / "module.json").write_text(json.dumps({"id": "pf2e-beginner-box", "description": TEXT}))
    (root / "packs/adventure/000005.ldb").write_text(TEXT)
    return root


def configure(entries: list[dict]) -> None:
    path = machine.config_dir() / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"purchased_content": entries}))


def reached(ws: Workspace, job: dict) -> str:
    """Everything a job's agent is handed: the contract, and each input file it may read."""
    found = [runner.prompt(ws, job)]
    for value in job["inputs"].values():
        path = Path(value)
        files = [path] if path.is_file() else path.rglob("*") if path.is_dir() else []
        found += [f.read_text() for f in files if f.is_file()]
    return "\n".join(found)


@pytest.mark.parametrize("pick", [lambda m: m, lambda m: m / "packs/adventure/000005.ldb"])
def test_without_the_opt_in_only_metadata_reaches_a_job(ws: Workspace, module: Path, pick) -> None:
    configure([{"path": str(module)}])
    job = runner.queue(ws, "realise-a-scene", {"brief": str(pick(module)), "scene": "otari"})
    assert "PURCHASED-SENTENCE" not in reached(ws, job)
    assert str(module) not in json.dumps(job)
    index = yaml.safe_load(Path(job["inputs"]["brief"]).read_text())
    assert index["opt_in"] is False
    assert "000005.ldb" in json.dumps(index["files"])  # indexed by metadata
    assert jobs.read(ws, job["id"])["inputs"] == job["inputs"]


def test_a_directory_holding_purchased_content_is_indexed_too(ws: Workspace, module: Path) -> None:
    configure([{"path": str(module)}])
    job = runner.queue(ws, "realise-a-scene", {"brief": str(module.parents[1]), "scene": "otari"})
    assert "PURCHASED-SENTENCE" not in reached(ws, job)


def test_with_the_opt_in_the_content_reaches_the_job(ws: Workspace, module: Path) -> None:
    configure([{"path": str(module), "opt_in": True}])
    job = runner.queue(ws, "realise-a-scene", {"brief": str(module), "scene": "otari"})
    assert job["inputs"]["brief"] == str(module)
    assert "PURCHASED-SENTENCE" in reached(ws, job)


def test_other_inputs_are_left_alone(ws: Workspace, module: Path, tmp_path: Path) -> None:
    configure([{"path": str(module)}])
    brief = tmp_path / "brief.md"
    brief.write_text("My own brief.")
    job = runner.queue(ws, "realise-a-scene", {"brief": str(brief), "scene": "otari"})
    assert job["inputs"] == {"brief": str(brief), "scene": "otari"}


@pytest.mark.parametrize(
    "entries", [[{"path": 3}], [{"path": "/x", "opt_in": "yes"}], [{"path": "/x", "other": 1}], {}]
)
def test_a_malformed_purchased_content_list_is_refused(ws: Workspace, entries) -> None:
    configure(entries)
    with pytest.raises(machine.MachineConfigError, match="purchased_content"):
        runner.queue(ws, "realise-a-scene", {"brief": "b", "scene": "otari"})
