"""Install the versioned workspace skill without overwriting campaign customizations."""

import hashlib
import json
from pathlib import Path

import yaml

from secondchair.core.workspace import WorkspaceError

SOURCE = Path(__file__).parent.parent / "skills/campaign-workshop/SKILL.md"
MANIFEST = ".secondchair-skills.json"
TARGETS = tuple(f"{host}/skills/campaign-workshop/SKILL.md" for host in (".agents", ".claude"))


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def plan(root: Path) -> tuple[bytes, dict]:
    """Preflight every managed file before writing any of them."""
    manifest = root / MANIFEST
    for relative in (*TARGETS, MANIFEST):
        path = root / relative
        if any(p.exists() and not p.is_dir() for p in path.parents):
            raise WorkspaceError(f"Managed skill parent is not a directory: {path}.")
        if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise WorkspaceError(f"Managed skill path uses a symlink: {path}.")
    try:
        previous = json.loads(manifest.read_text()) if manifest.exists() else {}
        hashes = previous.get("files", {})
        if not isinstance(hashes, dict):
            raise ValueError("files must be a mapping")
    except (ValueError, AttributeError) as e:
        raise WorkspaceError(f"Invalid skill manifest {manifest}: {e}") from e
    content = SOURCE.read_bytes()
    for relative in TARGETS:
        path = root / relative
        if path.exists() and (
            not path.is_file()
            or _hash(path.read_bytes()) not in (hashes.get(relative), _hash(content))
        ):
            raise WorkspaceError(
                f"Local skill edits at {path}; move custom guidance to a separate skill or "
                "campaign instructions, then retry. No managed files updated."
            )
    front = yaml.safe_load(content.decode().split("---", 2)[1])
    return content, {
        "version": front["metadata"]["version"],
        "files": {p: _hash(content) for p in TARGETS},
    }


def install(root: Path) -> list[str]:
    content, manifest = plan(root)
    changed = []
    for relative in TARGETS:
        path = root / relative
        if not path.exists() or path.read_bytes() != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            changed.append(relative)
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
    return changed
