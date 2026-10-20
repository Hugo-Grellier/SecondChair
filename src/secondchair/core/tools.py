"""Tool registration (ARC-03, docs/contracts/tool-registration.md).

Blocks never expose tools of their own: each registers its tools with the Core through a
`secondchair.tools` entry point, declaring every tool's responsibility, whether it is a
delegated action or a read, and whether it is reversible.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from secondchair.core import PROTOCOL_VERSION
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


@dataclass(frozen=True)
class Change:
    """What a delegated action's `fn` returns: the workspace file it writes. The Core, not the
    block, logs it and applies it at the effective level (ARC-04)."""

    path: str  # relative to the workspace root
    after: str | None  # the file's new content, None to delete it
    source: str | None = None  # what the action draws on, recorded in the log (DEL-24)
    entity: str | None = None  # the acting entity's canon id, what overrides key on (DEL-10)


class Contradiction(Exception):
    """Raised by a delegated action's `fn` when its change would contradict canon (a correction
    of something played, an event closing a higher-ranked fact). The Core refuses the action and
    logs the refusal, a continuity error (MET-01)."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(message)
        self.path = path  # the workspace file the refused change targeted


@dataclass(frozen=True, kw_only=True)
class VttAction:
    """What a delegated action's `fn` returns to act in the VTT: one operation on one document,
    which the Core logs and has the VTT connector take at the effective level (ARC-04, ARC-16).
    The Core reads none of it: the connector and its modules give `op` and `target` their
    meaning (docs/contracts/foundry-bridge.md)."""

    op: str  # the connector's operation, generic (move_token) or mechanical (system adapter)
    target: str  # the document acted on, as the connector names it
    params: dict[str, Any]  # the fields to set
    source: str | None = None  # what the action draws on, recorded in the log (DEL-24)
    entity: str | None = None  # as for `Change`
    # A disclosure's facts: the Core checks them, then marks them known by the party once the
    # action is taken (CAN-16, CAN-17). None for an action that shows the players nothing.
    cites: list[str] | None = None
    # Shown to some of the table only: `cites` mark nothing known by the party; the wrap holds
    # each as a call on the GM (CAP-08).
    whisper: bool = False
    # Holds it at propose whatever the level, the call carrying this as its message: an action
    # only the GM resolves, which an agent may only propose (RUL-08).
    hold: str | None = None


@dataclass(frozen=True, kw_only=True)
class Block:
    """What a `secondchair.tools` entry point names: the protocol range the block supports and
    the function returning its tools, called with the served workspace (ARC-17)."""

    protocol: tuple[str, str]  # lowest supported protocol version, first unsupported one
    tools: Callable[[Workspace], Iterable[Tool]]


def _semver(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(n) for n in version.split("."))
    return major, minor, patch


def _check_protocol(block: object) -> Block:
    """`block` if it declares a protocol range holding the Core's version, else refused."""
    if not isinstance(block, Block):
        raise RegistrationError("it declares no protocol range (secondchair.core.tools.Block)")
    try:
        low, high = (_semver(v) for v in block.protocol)
    except (TypeError, ValueError) as e:
        raise RegistrationError(f"protocol range {block.protocol!r} is not two X.Y.Z") from e
    if not low <= _semver(PROTOCOL_VERSION) < high:
        raise RegistrationError(
            f"it supports protocol {block.protocol[0]} up to {block.protocol[1]} (excluded), "
            f"the Core speaks {PROTOCOL_VERSION}. Install matching versions of SecondChair "
            "and the block."
        )
    return block


def load_tools(ws: Workspace) -> list[Tool]:
    """Every tool the installed blocks register, or `RegistrationError` naming the block."""
    tools: dict[str, Tool] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            registered: Iterable[object] = _check_protocol(ep.load()).tools(ws)
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
