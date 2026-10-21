"""The installed playbooks' metadata (ARC-21, ARC-25): read from their Agent Skills front matter,
so the Core queues a job at its playbook's tier without naming a model."""

from importlib.metadata import entry_points
from pathlib import Path

import yaml

from secondchair.core.delegation import DelegationError

PLAYBOOK_GROUP = "secondchair.playbooks"


def playbook_dirs() -> list[Path]:
    """Every installed block's playbook directory, from the PLAYBOOK_GROUP entry points."""
    return [Path(ep.load()) for ep in sorted(entry_points(group=PLAYBOOK_GROUP), key=str)]


def skills() -> list[Path]:
    """Every installed playbook's skill directory."""
    return sorted((s for d in playbook_dirs() for s in (d / "skills").iterdir()), key=str)


def playbook(name: str) -> dict[str, str]:
    """A playbook's SecondChair metadata, from its Agent Skills front matter."""
    found = [s / "SKILL.md" for s in skills() if s.name == name]
    if not found:
        known = ", ".join(sorted(s.name for s in skills()))
        raise DelegationError(f"No playbook {name!r}; known playbooks: {known}.")
    front = yaml.safe_load(found[0].read_text().split("---", 2)[1])
    prefix = "secondchair-"
    return {k.removeprefix(prefix): v for k, v in front["metadata"].items() if k.startswith(prefix)}
