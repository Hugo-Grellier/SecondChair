"""The PF2e System extension's tools: a GM creature's turn in an encounter (RUL-03..05, RUL-09).

Each is one call the PF2e adapter's executor takes in the GM's client through pf2e's document
methods (docs/contracts/foundry-bridge.md). The adapter refuses it for a PC, or outside a started
combat; it applies a follow-up condition only if no module did, and traces an ambiguous one for a
discrepancy (RUL-10). The Core logs each one under rules and combat; the GM undoes it.
"""

from typing import Literal

from secondchair.core.tools import Tool, VttAction
from secondchair.core.workspace import Workspace

RESPONSIBILITY = "rules_and_combat"


def strike(
    creature: str,
    strike: str,
    target: str,
    attack: Literal[1, 2, 3] = 1,
    entity: str | None = None,
) -> VttAction:
    """A GM creature strikes in an encounter: pf2e rolls the attack against the target's AC and,
    on a hit, rolls the damage and applies it to the target, a PC included. `creature` and
    `target` are their tokens' Foundry UUIDs (Scene.<id>.Token.<id>); `strike` is the strike's
    slug on the creature's sheet (such as "jaws"); `attack` its first, second or third attack
    this turn, for the multiple attack penalty; `entity` the creature's canon entity id, if it
    has one. Refused for a PC, whose player acts, and outside a started combat."""
    return VttAction(
        op="strike",
        target=creature,
        params={"strike": strike, "target": target, "map": attack - 1},
        entity=entity,
    )


def use_action(creature: str, action: str, target: str, entity: str | None = None) -> VttAction:
    """A GM creature uses a pf2e system action in an encounter (`action`, its slug in
    game.pf2e.actions: demoralize, trip, grapple, shove, …) against the token `target`. The
    condition its degree gives the target (frightened, prone, grabbed, restrained) is applied
    once, unless a module already did; an ambiguous one becomes a discrepancy. `creature` and
    `target` are tokens' Foundry UUIDs; `entity` the creature's canon entity id, if any. Refused
    for a PC and outside a started combat."""
    params = {"action": action, "target": target}
    return VttAction(op="use_action", target=creature, params=params, entity=entity)


def saving_throw(
    target: str,
    save: Literal["fortitude", "reflex", "will"],
    dc: int,
    entity: str | None = None,
) -> VttAction:
    """A save against `dc` in an encounter, by the token `target` (its Foundry UUID). A GM
    creature's save is rolled; a PC's is never rolled: its player is asked to roll it, with a
    check button in the chat. `entity` is the acting creature's canon entity id, if any.
    Refused outside a started combat."""
    return VttAction(
        op="saving_throw", target=target, params={"save": save, "dc": dc}, entity=entity
    )


def tools(_ws: Workspace) -> list[Tool]:
    return [
        Tool(fn=fn, responsibility=RESPONSIBILITY, delegated_action=True, reversible=True)
        for fn in (strike, use_action, saving_throw)
    ]
