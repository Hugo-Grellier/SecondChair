"""Upgrade by copy and swap, and consent to a destructive migration (ADR 0018, PKG-16)."""

import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from secondchair import cli
from secondchair.cli import main
from secondchair.core import delegation, workspace
from secondchair.core.workspace import Migration, WorkspaceError


def rename_prep(root: Path) -> None:
    ignore = root / ".gitignore"
    ignore.write_text(ignore.read_text() + "# migrated\n")


@pytest.fixture
def old(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A schema 1 workspace, with schema 2 current and a destructive migration to it."""
    root = tmp_path / "camp"
    main(["init", str(root), "--language", "en", "--calendar", "absalom"])
    monkeypatch.setattr(workspace, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(workspace, "MIGRATIONS", {1: Migration(rename_prep, "destructive")})
    return root


def upgrade(root: Path, *argv: str, interactive: bool = True, typed: str | None = None) -> int:
    with (
        patch.object(cli, "interactive", return_value=interactive),
        patch("builtins.input", return_value=typed if typed is not None else root.name),
    ):
        return main(["upgrade", "-w", str(root), *argv])


def test_every_migration_declares_additive_or_destructive() -> None:
    assert all(m.kind in ("additive", "destructive") for m in workspace.MIGRATIONS.values())
    with pytest.raises(ValueError):
        Migration(rename_prep, "other")  # ty: ignore[invalid-argument-type]


def test_preview_prints_the_diff_and_changes_nothing(
    old: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = sorted(
        p.relative_to(old).as_posix() for p in old.rglob("*") if ".secondchair" not in p.parts
    )
    table = (old / ".gitignore").read_text()
    assert upgrade(old, "--preview", interactive=False) == 0  # no consent for a temporary copy
    out = capsys.readouterr().out
    assert "+# migrated" in out and "+schema_version: 2" in out
    assert (
        sorted(
            p.relative_to(old).as_posix() for p in old.rglob("*") if ".secondchair" not in p.parts
        )
        == before
    )
    assert (old / ".gitignore").read_text() == table
    assert not old.with_name("camp.upgrading").exists()


def test_upgrade_snapshots_swaps_and_keeps_the_old_workspace(old: Path) -> None:
    (old / "notes.md").write_text("kept\n")
    assert upgrade(old) == 0
    assert workspace.load(old).schema_version == 2
    assert "# migrated" in (old / ".gitignore").read_text()
    kept = old.with_name("camp.pre-upgrade")
    assert "schema_version: 1" in (kept / "workspace.yaml").read_text()
    assert (old.parent / "camp.pre-upgrade.tar.gz").is_file()
    assert (old / "notes.md").read_text() == "kept\n"
    assert not (old / ".secondchair" / "upgrade-complete").exists()
    assert not (kept / ".secondchair" / "upgrading").exists()


def test_no_snapshot_skips_the_archive(old: Path) -> None:
    assert upgrade(old, "--no-snapshot") == 0
    assert not (old.parent / "camp.pre-upgrade.tar.gz").exists()


def test_destructive_is_refused_non_interactively_and_without_the_typed_name(
    old: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert upgrade(old, interactive=False) == 1
    assert "interactive terminal" in capsys.readouterr().err
    assert upgrade(old, typed="nope") == 1
    assert "schema_version: 1" in (old / "workspace.yaml").read_text()
    assert not old.with_name("camp.upgrading").exists()
    assert not (old / ".secondchair" / "upgrading").exists()


def test_an_additive_migration_needs_no_typed_name(
    old: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workspace, "MIGRATIONS", {1: Migration(lambda root: None, "additive")})
    assert upgrade(old, interactive=False) == 0


def test_a_failing_check_leaves_the_workspace_untouched(
    old: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(root: Path) -> None:
        (root / "delegation.yaml").write_text("{")

    monkeypatch.setattr(workspace, "MIGRATIONS", {1: Migration(broken, "destructive")})
    assert upgrade(old) == 1
    assert "schema_version: 1" in (old / "workspace.yaml").read_text()
    assert not old.with_name("camp.upgrading").exists()
    assert not (old / ".secondchair" / "upgrading").exists()


def test_recovery_of_an_upgrade_interrupted_before_the_swap(old: Path) -> None:
    copy = old.with_name("camp.upgrading")
    copy.mkdir()
    (copy / "half").write_text("x")
    (old / ".secondchair" / "upgrading").write_text("")  # its process died: the lock is free
    assert upgrade(old) == 0  # opens through recovery, then upgrades
    assert not copy.exists()


def test_a_running_upgrade_is_not_recovered(old: Path) -> None:
    (old / ".secondchair" / "upgrading").write_text("")
    with delegation.locked(old), pytest.raises(WorkspaceError, match="is running"):
        workspace.recover_upgrade(old)  # the upgrading process holds the lock; this is another


def test_the_window_is_finished_when_the_copy_is_complete(old: Path) -> None:
    copy, pre = old.with_name("camp.upgrading"), old.with_name("camp.pre-upgrade")
    workspace._copy(old, copy)
    workspace._migrate(copy, 1)
    (copy / ".secondchair").mkdir(exist_ok=True)
    (copy / ".secondchair" / "upgrade-complete").write_text("")
    old.rename(pre)
    ws = workspace.load(old)
    assert ws.schema_version == 2 and pre.is_dir() and not copy.exists()
    assert not (old / ".secondchair" / "upgrade-complete").exists()


def test_the_window_is_rolled_back_when_the_copy_is_incomplete(old: Path) -> None:
    copy, pre = old.with_name("camp.upgrading"), old.with_name("camp.pre-upgrade")
    workspace._copy(old, copy)
    (old / ".secondchair" / "upgrading").write_text("")
    old.rename(pre)
    with pytest.raises(WorkspaceError, match="older than 2"):
        workspace.load(old)
    assert "schema_version: 1" in (old / "workspace.yaml").read_text()
    assert not copy.exists() and not pre.exists()
    assert not (old / ".secondchair" / "upgrading").exists()


def test_a_finished_upgrade_is_reported_on_every_open(
    old: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert upgrade(old) == 0
    capsys.readouterr()
    workspace.load(old)
    assert "camp.pre-upgrade" in capsys.readouterr().err


def test_exchange_swaps_two_directories_when_the_host_can(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "x").write_text("a")
    if not workspace._exchange(a, b):
        pytest.skip("no renameat2(RENAME_EXCHANGE) on this host")
    assert (b / "x").read_text() == "a" and not (a / "x").exists()


def test_a_lock_waiter_retries_on_the_new_directory(old: Path) -> None:
    pre, copy = old.with_name("camp.pre-upgrade"), old.with_name("camp.upgrading")
    workspace._copy(old, copy)
    (copy / ".secondchair").mkdir(exist_ok=True)
    seen: list[int] = []
    started = threading.Event()

    def waiter() -> None:
        started.set()
        with delegation.locked(old):
            seen.append(os.stat(old / ".secondchair" / "delegation.lock").st_ino)

    with delegation.locked(old):
        t = threading.Thread(target=waiter)
        t.start()
        started.wait()
        time.sleep(0.3)  # the waiter is blocked on the old inode
        old.rename(pre)
        copy.rename(old)  # the swap, with the waiter still on the old inode
    t.join(10)
    assert seen == [os.stat(old / ".secondchair" / "delegation.lock").st_ino]
    assert seen[0] != os.stat(pre / ".secondchair" / "delegation.lock").st_ino
