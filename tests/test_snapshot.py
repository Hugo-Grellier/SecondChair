"""Backup and restore (ADR 0018): the restore rehearsal, and the refusals."""

import io
import json
import re
import stat
import tarfile
from pathlib import Path

import pytest
from test_s0_probes import GOLD, START, rebuild_world

from secondchair import cli
from secondchair.core import delegation, jobs, snapshot, workspace, world
from secondchair.core.workspace import WorkspaceError

REF = "r-" + "a" * 24


def populated(tmp_path: Path) -> workspace.Workspace:
    ws, _ = rebuild_world(tmp_path)
    world.world_turn(ws, "0302-05-01", since=START)
    (ws.root / "library.yaml").write_text(f"{REF}: setting.pdf\n")
    (ws.root / "foundry.yaml").write_text("world: bench\ncampaign: c0ffee\n")
    return ws


def tree(root: Path, folders: tuple[str, ...]) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for f in folders
        for p in (root / f).rglob("*")
        if p.is_file()
    }


def fresh_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "new-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "new-data"))


def test_restore_rehearsal_is_byte_identical_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert GOLD["status"] == "frozen"
    ws = populated(tmp_path / "old")
    archive = tmp_path / "backup.tar.gz"
    cli.main(["backup", str(ws.root), str(archive), "--foundry-backup-at", "2026-10-21T10:00:00Z"])
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    with tarfile.open(archive) as tar:
        assert not any(n.startswith("workspace/.secondchair/") for n in tar.getnames())
    fresh_host(tmp_path, monkeypatch)
    new = tmp_path / "new" / "campaign"
    capsys.readouterr()

    assert cli.main(["restore", str(archive), str(new)]) == 0

    out = capsys.readouterr().out
    folders = ("canon", "action-log", "occurrences", "jobs")
    assert tree(new, folders) == tree(ws.root, folders) != {}
    assert (new / "workspace.yaml").read_bytes() == (ws.root / "workspace.yaml").read_bytes()
    assert "world 'bench'" in out and "2026-10-21T10:00:00Z" in out
    assert "secondchair token" in out
    assert "1 reference(s) in library.yaml have no path or permission" in out
    assert cli.check(workspace.load(new)) == 0


def test_backup_refuses_an_unquiet_workspace(tmp_path: Path) -> None:
    ws = populated(tmp_path / "old")
    [job] = jobs.pending(ws)[:1]
    jobs.start(ws, job["id"], {"host": "h", "model": "m", "effort": "e"}, manual=True)
    with pytest.raises(WorkspaceError, match="job"):
        snapshot.backup(ws, tmp_path / "a.tar.gz")
    assert not (tmp_path / "a.tar.gz").exists()
    [path] = sorted((ws.root / delegation.LOG_DIR).glob("*.yaml"))[:1]
    path.write_text(re.sub(r"^status: .*$", "status: unknown", path.read_text(), flags=re.M))
    with pytest.raises(WorkspaceError, match="action"):
        snapshot.backup(ws, tmp_path / "b.tar.gz")


def test_restore_refuses_a_used_directory_and_a_corrupt_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = populated(tmp_path / "old")
    archive = tmp_path / "a.tar.gz"
    snapshot.backup(ws, archive)
    fresh_host(tmp_path, monkeypatch)
    used = tmp_path / "used"
    used.mkdir()
    (used / "x").write_text("x")
    with pytest.raises(WorkspaceError, match="not empty"):
        snapshot.restore(archive, used)
    with pytest.raises(WorkspaceError, match="outside the workspace"):
        snapshot.backup(ws, ws.root / "in.tar.gz")

    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(archive) as src, tarfile.open(bad, "w:gz") as dst:
        for m in src.getmembers():
            data = src.extractfile(m)
            assert data
            if m.name == "workspace/workspace.yaml":
                m.size += 1
                data = io.BytesIO(data.read() + b"#")
            dst.addfile(m, data)
    target = tmp_path / "restored"
    with pytest.raises(WorkspaceError, match="hash mismatch"):
        snapshot.restore(bad, target)
    assert not target.exists() and not list(tmp_path.glob(".restore-*"))
    with tarfile.open(archive) as tar:
        member = tar.extractfile("manifest.json")
        assert member
        manifest = json.loads(member.read())
    assert manifest["schema_version"] == 1 and manifest["files"]["workspace.yaml"]
