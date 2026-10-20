"""The Foundry VTT connector's Python half: the bridge to the Foundry modules (ARC-06), its tools,
and its playbooks (ARC-10)."""

from pathlib import Path

# A Claude Code plugin whose `skills/` is also a Codex skill bundle, like the Core's (PKG-19).
PLAYBOOKS = Path(__file__).parent / "playbooks"
