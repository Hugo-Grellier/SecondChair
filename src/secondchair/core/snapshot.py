"""Backup and restore of a campaign workspace (ADR 0018, PKG-16).

A backup is a gzip tar holding `manifest.json` and every workspace file except the derived
`.secondchair/` under `workspace/`. A restore only writes a new directory, verifies every hash,
and reports what the new host must still grant or find. The Core never dials Foundry: the paired
world backup is the GM's, declared by time.
"""

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime
from importlib import metadata
from pathlib import Path

import yaml

from secondchair.core import delegation, jobs, library, machine
from secondchair.core.workspace import STATE_DIR, Workspace, WorkspaceError

MANIFEST = "manifest.json"
FILES = "workspace/"
CACHE = "library-cache/"
BINDING = "foundry.yaml"


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _tree(root: Path, skip: str | None = None) -> dict[str, Path]:
    """Every regular file under `root` by relative path, refusing what a tar would not keep."""
    found = {}
    for p in sorted(root.rglob("*")):
        relative = p.relative_to(root)
        if skip and relative.parts[0] == skip:
            continue
        if p.is_symlink() or not (p.is_file() or p.is_dir()):
            raise WorkspaceError(f"{p} is a link or special file; a backup keeps only files.")
        if p.is_file():
            found[relative.as_posix()] = p
    return found


def _quiet(ws: Workspace) -> None:
    entries, _ = delegation.read_log(ws)
    unknown = [e["id"] for e in entries if e.get("status") == "unknown"]
    started = [j["id"] for j in jobs.pending(ws) if j["status"] == "started"]
    parts = []
    if unknown:
        parts.append(f"action(s) {unknown} await the VTT's answer")
    if started:
        parts.append(f"job(s) {started} are started")
    if parts:
        raise WorkspaceError(
            f"Not a quiet point: {'; '.join(parts)}. Wait for them, or end the job, then retry."
        )


def _foundry(ws: Workspace) -> dict:
    """The bound world and the versions the handshake last reported (the newest recorded
    rules context), as far as the workspace knows them."""
    binding = ws.root / BINDING
    world = yaml.safe_load(binding.read_text()).get("world") if binding.is_file() else None
    reported = {}
    for p in sorted((ws.root / delegation.OBSERVATIONS_DIR).glob("*.jsonl")):
        for line in p.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("kind") == "rules_context":
                payload = e.get("payload") or {}
                reported = {
                    "at": e.get("at"),
                    **{k: payload.get(k) for k in ("foundry", "system", "system_version")},
                    "modules": payload.get("modules"),
                }
    return {"world": world, "reported": reported or None}


def _commit(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    done = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or None if done.returncode == 0 else None


def backup(
    ws: Workspace,
    archive: Path,
    *,
    with_library_cache: bool = False,
    foundry_backup_at: str | None = None,
) -> dict:
    """Write the archive (mode 0600, never over a file) and return its manifest."""
    archive = archive.resolve()
    if archive.is_relative_to(ws.root.resolve()):
        raise WorkspaceError("The archive must be outside the workspace it backs up.")
    if foundry_backup_at is not None:
        try:
            datetime.fromisoformat(foundry_backup_at)
        except ValueError as e:
            raise WorkspaceError(
                f"--foundry-backup-at {foundry_backup_at!r} is not an ISO 8601 time."
            ) from e
    cache_root = machine.data_dir() / "library"
    with delegation.locked(ws):
        _quiet(ws)
        files = _tree(ws.root, STATE_DIR)
        cache = _tree(cache_root) if with_library_cache and cache_root.is_dir() else {}
        manifest = {
            "schema_version": ws.schema_version,
            "secondchair_version": metadata.version("secondchair"),
            "git_commit": _commit(ws.root),
            "foundry": {**_foundry(ws), "world_backup_at": foundry_backup_at},
            "files": {name: _sha256(p) for name, p in files.items()},
            "library_cache": {name: _sha256(p) for name, p in cache.items()},
        }
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out, tarfile.open(fileobj=out, mode="w:gz") as tar:
            data = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo(MANIFEST)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            for prefix, tree in ((FILES, files), (CACHE, cache)):
                for name, p in tree.items():
                    tar.add(p, arcname=prefix + name, recursive=False)
    return manifest


def _verified(tar: tarfile.TarFile, stage: Path) -> dict:
    """Extract into `stage` and check every file against the manifest; the manifest."""
    try:
        manifest = json.load(tar.extractfile(MANIFEST))  # ty: ignore[invalid-argument-type]
        expected = {FILES + n: h for n, h in manifest["files"].items()} | {
            CACHE + n: h for n, h in manifest["library_cache"].items()
        }
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        raise WorkspaceError("The archive has no valid manifest.json.") from e
    members = [m for m in tar.getmembers() if m.name != MANIFEST]
    if sorted(m.name for m in members) != sorted(expected) or not all(m.isfile() for m in members):
        raise WorkspaceError("The archive's files are not those of its manifest.")
    tar.extractall(stage, members=members, filter="data")
    wrong = [n for n, h in expected.items() if _sha256(stage / n) != h]
    if wrong:
        raise WorkspaceError(f"The archive is corrupt: hash mismatch for {', '.join(wrong)}.")
    return manifest


def restore(archive: Path, target: Path) -> tuple[dict, list[str]]:
    """Restore into an empty or new `target`; the manifest and the report of what the new host
    still needs. Nothing is fixed. Run `check` on `target` afterwards."""
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise WorkspaceError(f"{target} is not empty: restore only writes a new directory.")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".restore-", dir=target.parent))
    try:
        try:
            with tarfile.open(archive, "r:gz") as tar:
                manifest = _verified(tar, stage)
        except (tarfile.TarError, EOFError) as e:
            raise WorkspaceError(f"{archive} is not a SecondChair backup: {e}") from e
        if target.exists():
            target.rmdir()
        (stage / FILES).rename(target)  # an archive of an empty workspace cannot occur
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    cache = stage / CACHE
    if cache.is_dir():
        destination = machine.data_dir() / "library"
        if destination.exists():
            note = "kept the library cache already on this host."
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(cache, destination)
            note = "restored the library cache."
    else:
        note = None
    shutil.rmtree(stage, ignore_errors=True)
    return manifest, _report(manifest, target, note)


def _locations() -> dict:
    path = machine.config_dir() / "sources.yaml"
    found = yaml.safe_load(path.read_text()) if path.is_file() else None
    return found if isinstance(found, dict) else {}


def _report(manifest: dict, root: Path, cache_note: str | None) -> list[str]:
    lines = []
    foundry = manifest["foundry"]
    if foundry["world"]:
        lines.append(
            f"Foundry: bound to world {foundry['world']!r}; restore the paired world backup "
            f"(taken {foundry['world_backup_at'] or 'at an undeclared time'}). The new host "
            "reports its Foundry, system and module versions when the module connects; compare "
            f"them with those at backup: {foundry['reported'] or 'none were reported'}."
        )
    else:
        lines.append("Foundry: the workspace was not bound to a world at backup.")
    lines.append(
        "Machine configuration never travels: run `secondchair token` and paste the new token "
        "into the Foundry module; configure runners and purchased content again."
    )
    registered = (
        yaml.safe_load((root / library.REFERENCE_FILE).read_text())
        if (root / library.REFERENCE_FILE).is_file()
        else None
    )
    if registered:
        lines.append(
            f"Library: {len(registered)} reference(s) in library.yaml have no path or permission "
            "on this host (they are keyed by the workspace path): `secondchair sources add` "
            "their files, then `secondchair sources permit` again."
        )
    locations = _locations()
    missing = sorted(
        p.stem
        for p in (root / "sources").glob("*.yaml")
        if p.stem not in locations or not Path(locations[p.stem]).exists()
    )
    if missing:
        lines.append(f"Sources: no file on this host for {', '.join(missing)}.")
    if cache_note:
        lines.append(f"Library cache: {cache_note}")
    return lines
