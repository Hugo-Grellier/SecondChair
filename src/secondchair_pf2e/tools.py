"""The PF2e System extension's tools: a GM creature's turn in an encounter (RUL-03..09).

Each is one call the PF2e adapter's executor takes in the GM's client through pf2e's document
methods (docs/contracts/foundry-bridge.md). The adapter refuses it for a PC, or outside a started
combat; it applies a follow-up condition only if no module did, and traces an ambiguous one for a
discrepancy (RUL-10). The Core logs each one under rules and combat; the GM undoes it.
"""

from typing import Literal

from secondchair.core.tools import Block, Tool, VttAction
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


def cast_spell(
    creature: str,
    spell: str,
    rank: int | None = None,
    variant: str | None = None,
    actions: Literal[1, 2, 3] | None = None,
    entity: str | None = None,
) -> VttAction:
    """A GM creature casts one of its spells in an encounter (`spell`, its id or slug on the
    creature's sheet), spending what pf2e spends: a prepared slot, a spontaneous slot, a focus
    point or an innate use; a cantrip spends nothing. `rank` heightens it (its own rank if
    omitted), `variant` is one of its overlay ids (such as Heal's one- or two-action version).
    Saves, damage and areas are their own actions. A spell whose cost is variable and that has no
    overlay is the GM's to resolve: give `actions`, the cost you propose, and it is held for the
    GM's approval whatever the level; without it the cast is refused. `creature` is its token's
    Foundry UUID; `entity` its canon entity id, if any. Refused for a PC and outside a started
    combat, and when nothing is left to spend."""
    params = {"spell": spell, "rank": rank, "variant": variant, "actions": actions}
    hold = None
    if actions is not None:
        hold = (
            f"{creature} proposes casting {spell} for {actions} action(s): a variable cost, "
            "which the GM resolves (RUL-08)."
        )
    return VttAction(op="cast_spell", target=creature, params=params, entity=entity, hold=hold)


def use_self_effect(creature: str, item: str, entity: str | None = None) -> VttAction:
    """A GM creature uses one of its actions or feats that has a self-effect (`item`, its slug,
    such as "raise-a-shield") in an encounter: the item goes to the chat and its effect is put on
    the creature, unless a module already did. `creature` is its token's Foundry UUID; `entity`
    its canon entity id, if any. Refused for a PC and outside a started combat."""
    return VttAction(op="self_effect", target=creature, params={"item": item}, entity=entity)


def place_area(
    creature: str,
    area: Literal["burst", "cone", "line"],
    size: int,
    x: int,
    y: int,
    direction: int = 0,
    name: str | None = None,
    entity: str | None = None,
) -> VttAction:
    """A GM creature places a spell's or ability's area on its scene in an encounter, as a pf2e
    effect-area Region: a `burst` of radius `size` feet centred on the origin, or a `cone` or
    `line` `size` feet long from it, pointing `direction` degrees (0 east, 90 south). The origin
    (`x`, `y`) is a point in scene pixels you choose, such as a grid intersection. `name` labels
    it (the spell's name). `creature` is its token's Foundry UUID; `entity` its canon entity id,
    if any. Refused for a PC and outside a started combat."""
    params = {
        "area": area,
        "size": size,
        "x": x,
        "y": y,
        "direction": direction,
        "name": name,
    }
    return VttAction(op="place_area", target=creature, params=params, entity=entity)


def reactive_strike(
    creature: str,
    strike: str,
    target: str,
    trigger: Literal["leaves-reach", "manipulate", "move", "ranged-attack"],
    entity: str | None = None,
) -> VttAction:
    """A GM creature with Reactive Strike reacts in an encounter to a creature within its reach
    that leaves it, uses a manipulate or a move action, or makes a ranged attack (`trigger`): it
    strikes `target` with `strike` (its slug), without multiple attack penalty, and the damage is
    applied on a hit. Once per round: refused when the creature already reacted this round, by
    SecondChair's count or any known reaction tracker. Every other reaction is the GM's. Tokens
    are Foundry UUIDs; `entity` the creature's canon entity id, if any."""
    params = {"strike": strike, "target": target, "trigger": trigger}
    return VttAction(op="reaction", target=creature, params=params, entity=entity)


def tools(_ws: Workspace) -> list[Tool]:
    return [
        Tool(fn=fn, responsibility=RESPONSIBILITY, delegated_action=True, reversible=True)
        for fn in (
            strike,
            use_action,
            saving_throw,
            cast_spell,
            use_self_effect,
            place_area,
            reactive_strike,
        )
    ]


# The protocol range this block supports (ARC-17): `serve` refuses it outside the range.
BLOCK = Block(protocol=("0.1.0", "0.2.0"), tools=tools)
