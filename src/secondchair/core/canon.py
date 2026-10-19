"""Canon in the workspace (04-canon-memory-capture.md). So far: entities, identity only (CAN-02)."""

import secrets

import yaml

from secondchair.core.tools import Change

ENTITIES_DIR = "canon/entities"


def create_entity(
    names: list[str],
    aliases: list[str] | None = None,
    official_reference: str | None = None,
    description: str = "",
) -> Change:
    """Create a canon entity: identity only (names, aliases, an optional official reference and a
    player-facing description with no truth value). What is true about it is stated by facts."""
    if not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise ValueError("An entity needs at least one non-empty name.")
    entity_id = f"e-{secrets.token_hex(4)}"
    identity = {
        "id": entity_id,
        "names": names,
        "aliases": aliases or [],
        "official_reference": official_reference,
    }
    front = yaml.safe_dump(identity, sort_keys=False, allow_unicode=True)
    return Change(path=f"{ENTITIES_DIR}/{entity_id}.md", after=f"---\n{front}---\n{description}\n")
