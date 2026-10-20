"""The PF2e System extension: everything specific to Pathfinder Second Edition (ARC-15)."""

from pathlib import Path

# Its rules playbooks, a Claude Code plugin whose `skills/` is also a Codex skill bundle (PKG-19).
PLAYBOOKS = Path(__file__).parent / "playbooks"
