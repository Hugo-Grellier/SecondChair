"""Tool registration (ARC-03, docs/contracts/tool-registration.md).

Blocks never expose tools of their own: each registers its tools with the Core through a
`secondchair.tools` entry point, declaring every tool's responsibility, whether it is a
delegated action or a read, and whether it is reversible.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from secondchair.core.workspace import Workspace

ENTRY_POINT_GROUP = "secondchair.tools"

# The eight responsibilities (DEL-01).
RESPONSIBILITIES = (
    "prep",
    "memory",
    "vtt_operations",
    "rules_and_combat",
    "living_world",
    "npcs",
    "narrative_direction",
    "disclosure",
)


class RegistrationError(Exception):
    """A block's tool registration the Core refuses; `serve` does not start."""


@dataclass(frozen=True, kw_only=True)
class Tool:
    """One tool a block registers. The MCP tool's name, description and arguments come from
    `fn`'s name, docstring and parameters."""

    fn: Callable[..., Any]
    responsibility: str
    delegated_action: bool
    reversible: bool

    def __post_init__(self) -> None:
        if self.responsibility not in RESPONSIBILITIES:
            known = ", ".join(RESPONSIBILITIES)
            raise RegistrationError(f"responsibility {self.responsibility!r} is not one of {known}")
        for field in ("delegated_action", "reversible"):
            if type(getattr(self, field)) is not bool:
                raise RegistrationError(f"{field} must be true or false")

    @property
    def name(self) -> str:
        return getattr(self.fn, "__name__", repr(self.fn))


def load_tools(ws: Workspace) -> list[Tool]:
    """Every tool the installed blocks register, or `RegistrationError` naming the block."""
    tools: dict[str, Tool] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            registered: Iterable[object] = ep.load()(ws)
            for tool in registered:
                if not isinstance(tool, Tool):
                    raise RegistrationError(f"{tool!r} is not a secondchair.core.tools.Tool")
                if tool.name in tools:
                    raise RegistrationError(f"tool {tool.name!r} is already registered")
                tools[tool.name] = tool
        except Exception as e:  # a block's failure, whatever it is, stops `serve` cleanly
            raise RegistrationError(
                f"block {ep.name!r} ({ep.value}): registration refused: {e}"
            ) from e
    return list(tools.values())
