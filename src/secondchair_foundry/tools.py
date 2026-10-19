"""The Foundry connector's generic VTT actions (ARC-07), registered with the Core (ARC-03).

Each describes one operation the `secondchair-foundry` module takes in the GM's client
(docs/contracts/foundry-bridge.md); the Core logs it and has the bridge send it (ARC-04).
"""

from typing import Literal

from secondchair.core.tools import Tool, VttAction
from secondchair.core.workspace import Workspace

DOOR_STATES = {"closed": 0, "open": 1, "locked": 2}  # Foundry's wall door states (`ds`)


def move_token(token: str, x: int, y: int) -> VttAction:
    """Move a token on its scene. `token` is its Foundry UUID (Scene.<id>.Token.<id>); `x` and
    `y` are the pixel position of its top-left corner."""
    return VttAction(op="move_token", target=token, params={"x": x, "y": y})


def set_door(door: str, state: Literal["closed", "open", "locked"]) -> VttAction:
    """Open, close or lock a door. `door` is its wall's Foundry UUID (Scene.<id>.Wall.<id>)."""
    return VttAction(op="set_door", target=door, params={"ds": DOOR_STATES[state]})


def tools(ws: Workspace) -> list[Tool]:
    return [
        Tool(fn=fn, responsibility="vtt_operations", delegated_action=True, reversible=True)
        for fn in (move_token, set_door)
    ]
