import json

import pytest

from secondchair.cli import main
from secondchair.core import campaign_skill, workspace


def test_init_and_existing_workspace_install_and_upgrade(tmp_path, monkeypatch):
    ws = workspace.init(tmp_path, "fr", "absalom")
    custom = ws.root / ".claude/skills/my-campaign/SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_text("Campaign-specific guidance")
    original = campaign_skill.SOURCE.read_bytes()
    for relative in campaign_skill.TARGETS:
        assert (ws.root / relative).read_bytes() == original
    updated = tmp_path / "upstream.md"
    updated.write_bytes(
        original.replace(b'version: "1"', b'version: "2"') + b"\nUpdated protocol.\n"
    )
    monkeypatch.setattr(campaign_skill, "SOURCE", updated)
    assert main(["campaign-skill", "-w", str(tmp_path)]) == 0
    assert custom.read_text() == "Campaign-specific guidance"
    for relative in campaign_skill.TARGETS:
        assert (ws.root / relative).read_bytes() == updated.read_bytes()
    assert json.loads((tmp_path / campaign_skill.MANIFEST).read_text())["version"] == "2"
    assert campaign_skill.install(tmp_path) == []
    # Existing workspaces need no schema migration or pre-existing manifest.
    other = tmp_path / "existing"
    other.mkdir()
    (other / "workspace.yaml").write_text((tmp_path / "workspace.yaml").read_text())
    assert main(["campaign-skill", "-w", str(other)]) == 0


def test_update_preflights_both_hosts_and_preserves_local_edits(tmp_path, monkeypatch):
    workspace.init(tmp_path, "fr", "absalom")
    local = tmp_path / campaign_skill.TARGETS[1]
    local.write_text("local edits")
    snapshot = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    updated = tmp_path / "upstream.md"
    updated.write_text("New managed version")
    monkeypatch.setattr(campaign_skill, "SOURCE", updated)
    assert main(["campaign-skill", "-w", str(tmp_path)]) == 1
    assert all(p.read_bytes() == content for p, content in snapshot.items())


def test_init_refuses_conflicting_skill_before_creating_workspace(tmp_path):
    skill = tmp_path / campaign_skill.TARGETS[0]
    skill.parent.mkdir(parents=True)
    skill.write_text("personal skill")
    with pytest.raises(workspace.WorkspaceError, match="Local skill edits"):
        workspace.init(tmp_path, "fr", "absalom")
    assert not (tmp_path / "workspace.yaml").exists()
    assert skill.read_text() == "personal skill"


def test_skill_symlink_and_manifest_corruption_are_refused(tmp_path):
    workspace.init(tmp_path, "fr", "absalom")
    target = tmp_path / campaign_skill.TARGETS[0]
    target.unlink()
    target.symlink_to(campaign_skill.SOURCE)
    with pytest.raises(workspace.WorkspaceError, match="symlink"):
        campaign_skill.install(tmp_path)
    target.unlink()
    (tmp_path / campaign_skill.MANIFEST).write_text(json.dumps({"files": []}))
    with pytest.raises(workspace.WorkspaceError, match="manifest"):
        campaign_skill.install(tmp_path)


def test_parent_file_conflict_does_not_partially_install(tmp_path):
    (tmp_path / ".claude").write_text("existing campaign file")
    with pytest.raises(workspace.WorkspaceError, match="not a directory"):
        campaign_skill.install(tmp_path)
    assert not (tmp_path / ".agents").exists()
    assert (tmp_path / ".claude").read_text() == "existing campaign file"
