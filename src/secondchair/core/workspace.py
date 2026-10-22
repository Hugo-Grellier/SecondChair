"""The campaign workspace: its layout and `workspace.yaml` (docs/contracts/workspace-layout.md)."""

import ctypes
import difflib
import fcntl
import json
import os
import re
import shutil
import socket
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from secondchair.core.calendar import Calendar, CalendarError, from_config

SCHEMA_VERSION = 1
# Version n -> the migration of a workspace root from n to n + 1 (PKG-16), which declares whether
# it only adds (`additive`) or removes, rewrites or merges authoritative content (`destructive`,
# ADR 0018).
MIGRATIONS: dict[int, Migration] = {}
CONFIG_FILE = "workspace.yaml"
STATE_DIR = ".secondchair"

# ponytail: shape check of a BCP 47 tag (language, then subtags), not a registry lookup.
_BCP47 = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")


@dataclass(frozen=True)
class Migration:
    run: Callable[[Path], None]
    kind: Literal["additive", "destructive"]

    def __post_init__(self) -> None:
        if self.kind not in ("additive", "destructive"):
            raise ValueError(f"a migration is additive or destructive, not {self.kind!r}")


class WorkspaceError(Exception):
    """A workspace that cannot be created or served, with a message for the GM."""


@dataclass(frozen=True)
class Workspace:
    root: Path
    schema_version: int
    campaign_language: str
    calendar: Calendar


def init(root: Path, language: str, calendar: str | dict) -> Workspace:
    """Create a campaign workspace in `root`. The campaign language and calendar are fixed from
    then on (CAN-18, CAL-01). `calendar` is a System extension's calendar name or an inline
    declaration, as `workspace.yaml` stores it (CAL-03)."""
    config = root / CONFIG_FILE
    if config.exists():
        existing = _read(config).get("campaign_language")
        raise WorkspaceError(
            f"{root} is already a campaign workspace (campaign language {existing!r}); "
            "the campaign language and calendar are fixed at creation and cannot be changed."
        )
    if not _BCP47.match(language):
        raise WorkspaceError(
            f"{language!r} is not a BCP 47 language tag (for example: en, fr, de, en-GB)."
        )
    _calendar(calendar, "--calendar")

    from secondchair.core import campaign_skill

    campaign_skill.plan(root)
    (root / STATE_DIR).mkdir(parents=True, exist_ok=True)
    config.write_text(
        yaml.safe_dump(
            {"schema_version": SCHEMA_VERSION, "campaign_language": language, "calendar": calendar},
            sort_keys=False,
        )
    )
    from secondchair.core import delegation  # it builds on this module

    delegation.seed(root)
    campaign_skill.install(root)
    gitignore = root / ".gitignore"
    lines = gitignore.read_text().splitlines() if gitignore.exists() else []
    if f"{STATE_DIR}/" not in lines:
        gitignore.write_text("\n".join([*lines, f"{STATE_DIR}/"]) + "\n")
    return load(root)


def load(root: Path) -> Workspace:
    """Open the workspace in `root`, refusing a schema this version cannot serve. First settles
    an interrupted upgrade, and reports the `.pre-upgrade` copy a finished one keeps."""
    recover_upgrade(root)
    if (kept := _sibling(root.resolve(), PRE_UPGRADE)).exists():
        print(
            f"secondchair: {kept} is the workspace before the last upgrade; delete it, or "
            "rename it back to roll the upgrade back.",
            file=sys.stderr,
        )
    config, data, version = _versioned(root)
    if version < SCHEMA_VERSION:
        raise WorkspaceError(
            f"{config} declares schema version {version}, older than {SCHEMA_VERSION}. "
            "Run `secondchair upgrade` to migrate it first."
        )
    language = data.get("campaign_language")
    if not isinstance(language, str):
        raise WorkspaceError(f"{config} has no campaign_language.")
    if "calendar" not in data:
        raise WorkspaceError(f"{config} has no calendar.")
    return Workspace(root, version, language, _calendar(data["calendar"], str(config)))


def upgrade(
    root: Path,
    check: Callable[[Workspace], int],
    consent: Callable[[Path, list[int]], bool],
    *,
    preview: bool = False,
    snapshot: bool = True,
) -> tuple[int, int, str]:
    """Migrate the workspace in `root` to the current schema, one version at a time, on a sibling
    copy swapped in by two renames once `check` passes (PKG-16, ADR 0018). The versions before and
    after, and with `preview` the diff, changing nothing. `consent` is asked, before anything is
    taken, for the versions whose migration is destructive."""
    from secondchair.core import delegation  # they build on this module
    from secondchair.core import snapshot as snapshots

    root = root.resolve()
    recover_upgrade(root)
    config, _, start = _versioned(root)
    pending = range(start, SCHEMA_VERSION)
    if missing := [v for v in pending if v not in MIGRATIONS]:
        raise WorkspaceError(f"No migration from workspace schema version {missing[0]}.")
    if not pending:
        return start, start, ""
    if preview:
        with delegation.locked(root), tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / root.name
            _copy(root, copy)
            _migrate(copy, start)
            return start, SCHEMA_VERSION, _diff(root, copy)
    destructive = [v for v in pending if MIGRATIONS[v].kind == "destructive"]
    if destructive and not consent(root, destructive):
        raise WorkspaceError("The destructive migration was not confirmed; nothing was changed.")
    if _serving(root):
        raise WorkspaceError(f"`secondchair serve` runs on {root}: stop it, then upgrade.")
    copy, old = _sibling(root, UPGRADING), _sibling(root, PRE_UPGRADE)
    archive = root.with_name(root.name + PRE_UPGRADE + ".tar.gz")
    if copy.exists() or old.exists() or (snapshot and archive.exists()):
        raise WorkspaceError(f"{copy}, {old} or {archive} already exists: move or delete it.")
    marker = root / STATE_DIR / UPGRADING_MARKER
    with delegation.locked(root):  # held until the swap ends: waiters retry on the new directory
        if snapshot:
            data = _read(config)
            calendar = _calendar(data.get("calendar"), str(config))
            snapshots.backup(
                Workspace(root, start, str(data.get("campaign_language")), calendar), archive
            )
        marker.write_text("")
        try:
            _copy(root, copy)
            _migrate(copy, start)
            if check(load(copy)):
                raise WorkspaceError(
                    "check failed on the migrated copy; the workspace is unchanged."
                )
            (copy / STATE_DIR).mkdir(exist_ok=True)
            (copy / STATE_DIR / UPGRADE_COMPLETE).write_text("")
        except BaseException:
            shutil.rmtree(copy, ignore_errors=True)
            marker.unlink(missing_ok=True)
            raise
        if _exchange(root, copy):  # the window never opens
            copy.rename(old)
        else:
            root.rename(old)  # until the next line nothing exists at `root`
            copy.rename(root)
        (old / STATE_DIR / UPGRADING_MARKER).unlink(missing_ok=True)
        (root / STATE_DIR / UPGRADE_COMPLETE).unlink(missing_ok=True)
    return start, SCHEMA_VERSION, ""


UPGRADING = ".upgrading"
PRE_UPGRADE = ".pre-upgrade"
UPGRADING_MARKER = "upgrading"
UPGRADE_COMPLETE = "upgrade-complete"


def _sibling(root: Path, suffix: str) -> Path:
    return root.with_name(root.name + suffix)


def _copy(root: Path, copy: Path) -> None:
    """The workspace with its `.git` and without `.secondchair/` (rebuilt by `check`)."""
    shutil.copytree(
        root,
        copy,
        symlinks=True,
        ignore=lambda d, names: [STATE_DIR] if Path(d) == root else [],
    )


def _migrate(root: Path, version: int) -> None:
    config = root / CONFIG_FILE
    while version < SCHEMA_VERSION:
        MIGRATIONS[version].run(root)
        version += 1
        # Only the version line changes, so the diff shows the migration and nothing else.
        config.write_text(
            re.sub(
                r"^schema_version:.*$",
                f"schema_version: {version}",
                config.read_text(),
                count=1,
                flags=re.M,
            )
        )


def _tree(root: Path) -> dict[str, Path]:
    return {
        p.relative_to(root).as_posix(): p
        for p in root.rglob("*")
        if p.is_file() and p.relative_to(root).parts[0] not in (".git", STATE_DIR)
    }


def _diff(before: Path, after: Path) -> str:
    """A unified diff of the two workspaces' files (not `.git`, not `.secondchair/`)."""
    old, new = _tree(before), _tree(after)
    out = []
    for name in sorted(old | new):
        a = old[name].read_text(errors="replace").splitlines(True) if name in old else []
        b = new[name].read_text(errors="replace").splitlines(True) if name in new else []
        out += difflib.unified_diff(a, b, f"a/{name}", f"b/{name}")
    return "".join(out)


def _serving(root: Path) -> bool:
    """Whether a `serve` answers on the port its state file names."""
    from secondchair.core.server import LOOPBACK, SERVE_FILE

    try:
        port = json.loads((root / STATE_DIR / SERVE_FILE).read_text())["port"]
        socket.create_connection((LOOPBACK, port), timeout=0.5).close()
    except OSError, ValueError, KeyError, TypeError:
        return False
    return True


def _exchange(a: Path, b: Path) -> bool:
    """Swap two directories atomically with Linux `renameat2(RENAME_EXCHANGE)`; False when this
    host cannot (the two renames then run, and recovery covers the window)."""
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
        at_fdcwd, rename_exchange = -100, 2
        return renameat2(at_fdcwd, os.fsencode(a), at_fdcwd, os.fsencode(b), rename_exchange) == 0
    except AttributeError, OSError:
        return False


def _alive(directory: Path) -> bool:
    """Whether a process holds the workspace lock of `directory`, as a running upgrade does."""
    try:
        fd = os.open(directory / STATE_DIR / "delegation.lock", os.O_RDWR)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def recover_upgrade(root: Path) -> None:
    """Settle what an interrupted `upgrade` left, before a workspace opens (ADR 0018): each
    directory ends wholly old or wholly migrated. Refuses while an upgrade runs."""
    root = root.resolve()
    copy, old = _sibling(root, UPGRADING), _sibling(root, PRE_UPGRADE)
    state = root / STATE_DIR
    if not root.exists():
        if not (copy.is_dir() and old.is_dir()):
            return
        if _alive(old):
            raise WorkspaceError(f"An upgrade of {root} is running.")
        if (copy / STATE_DIR / UPGRADE_COMPLETE).is_file():  # the window: finish the swap
            copy.rename(root)
            (old / STATE_DIR / UPGRADING_MARKER).unlink(missing_ok=True)
            (state / UPGRADE_COMPLETE).unlink()
        else:  # or roll it back
            old.rename(root)
            (root / STATE_DIR / UPGRADING_MARKER).unlink(missing_ok=True)
            shutil.rmtree(copy, ignore_errors=True)
    elif (state / UPGRADE_COMPLETE).is_file():  # swapped; the upgrade died before cleaning up
        if copy.is_dir() and not old.exists():  # exchanged: the old one sits at `.upgrading`
            copy.rename(old)
        (old / STATE_DIR / UPGRADING_MARKER).unlink(missing_ok=True)
        (state / UPGRADE_COMPLETE).unlink()
    elif (state / UPGRADING_MARKER).is_file():  # interrupted before the swap: the original stands
        if _alive(root):
            raise WorkspaceError(f"An upgrade of {root} is running.")
        shutil.rmtree(copy, ignore_errors=True)
        (state / UPGRADING_MARKER).unlink()


def _versioned(root: Path) -> tuple[Path, dict, int]:
    """`workspace.yaml`, its content and its schema version, refusing a newer one."""
    config = root / CONFIG_FILE
    if not config.is_file():
        raise WorkspaceError(f"{root} is not a campaign workspace: {CONFIG_FILE} is missing.")
    data = _read(config)
    version = data.get("schema_version")
    if not isinstance(version, int):
        raise WorkspaceError(f"{config} has no integer schema_version.")
    if version > SCHEMA_VERSION:
        raise WorkspaceError(
            f"{config} declares schema version {version}, newer than the {SCHEMA_VERSION} "
            "this SecondChair supports. Upgrade SecondChair to serve this workspace."
        )
    return config, data, version


def _calendar(value: object, where: str) -> Calendar:
    try:
        return from_config(value)
    except CalendarError as e:
        raise WorkspaceError(f"{where}: invalid calendar: {e}") from e


def _read(config: Path) -> dict:
    try:
        data = yaml.safe_load(config.read_text())
    except yaml.YAMLError as e:
        raise WorkspaceError(f"{config} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise WorkspaceError(f"{config} must be a YAML mapping.")
    return data
