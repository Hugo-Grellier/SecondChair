"""Trace readers: optional evidence from third-party module flags (RUL-19, RUL-20, ADR 0013).

A closed list, each written against one known format. A reader returns None, silent, when the
module is absent or its flags do not have the format it knows: the rules checks then fall back
to the pf2e trace alone, and the bench catches the drift. Each takes an outcome's payload
(docs/contracts/pf2e-outcome.schema.json), whose `flags` carry the raw module flags.
"""

from typing import Any

DEGREES = ("criticalFailure", "failure", "success", "criticalSuccess")
AMOUNTS = (-2, -1, 1, 2, *DEGREES)  # pf2e's DEGREE_ADJUSTMENT_AMOUNTS
VISIBILITIES = ("observed", "concealed", "hidden", "undetected")
COVERS = ("none", "lesser", "standard", "greater")


def _flags(payload: dict, module: str) -> Any:
    flags = payload.get("flags")
    return flags.get(module) if isinstance(flags, dict) else None


def _int(value: object) -> bool:
    return type(value) is int


def _adjustments(record: object) -> dict | None:
    """A pf2e DegreeAdjustmentsRecord, {"all" | degree: {label, amount}}, or None."""
    if not isinstance(record, dict):
        return None
    for key, adjustment in record.items():
        if (
            key not in ("all", *DEGREES)
            or not isinstance(adjustment, dict)
            or not isinstance(adjustment.get("label"), str)
            or adjustment.get("amount") not in AMOUNTS
            or isinstance(adjustment.get("amount"), bool)
        ):
            return None
    return record


def dos_adjustments(payload: dict) -> dict | None:
    """pf2e's own `dosAdjustments`, the degree adjustments the roll applied."""
    pf2e = _flags(payload, "pf2e")
    return _adjustments(pf2e.get("dosAdjustments")) if isinstance(pf2e, dict) else None


def toolbelt_saves(payload: dict) -> list[dict] | None:
    """PF2e Toolbelt's Target Helper: each target's save, as a degree trace
    {target, total, natural, dc, degree, unadjusted, adjustments}."""
    helper = _flags(payload, "pf2e-toolbelt")
    helper = helper.get("targetHelper") if isinstance(helper, dict) else None
    variants = helper.get("saveVariants") if isinstance(helper, dict) else None
    if not isinstance(variants, dict):
        return None
    saves = []
    for variant in variants.values():
        if not (isinstance(variant, dict) and _int(variant.get("dc"))):
            return None
        targets = variant.get("saves", {})
        if not isinstance(targets, dict):
            return None
        for target, save in targets.items():
            if not (
                isinstance(save, dict)
                and _int(save.get("value"))
                and _int(save.get("die"))
                and save.get("success") in DEGREES
                and save.get("unadjustedOutcome", None) in (None, *DEGREES)
            ):
                return None
            adjustments = _adjustments(save.get("dosAdjustments", {}))
            if adjustments is None:
                return None
            saves.append(
                {
                    "target": target,
                    "total": save["value"],
                    "natural": save["die"],
                    "dc": variant["dc"],
                    "degree": save["success"],
                    "unadjusted": save.get("unadjustedOutcome"),
                    "adjustments": adjustments,
                }
            )
    return saves


def visioner(payload: dict) -> dict | None:
    """PF2e Visioner's token flags: the acting token's visibility and cover, by other token."""
    flags = _flags(payload, "pf2e-visioner")
    if not isinstance(flags, dict):
        return None
    found = {}
    for key, states in (("visibility", VISIBILITIES), ("cover", COVERS)):
        value = flags.get(key)
        if isinstance(value, dict) and all(v in states for v in value.values()):
            found[key] = value
    return found or None


def reaction_used(payload: dict) -> bool | None:
    """Whether a known reaction tracker says the actor's reaction is used this round: Reaction
    Checker's combatant flag, Combater's `reactionUsed`, Sundry's `effect-reaction-used`
    effect. None when no tracker speaks (RUL-07)."""
    said = []
    checker = _flags(payload, "pf2e-reaction")
    if isinstance(checker, dict) and isinstance(checker.get("state"), bool):
        said.append(not checker["state"])
    combater = _flags(payload, "pf2e-combater")
    if isinstance(combater, dict) and isinstance(combater.get("reactionUsed"), bool | None):
        said.append(bool(combater.get("reactionUsed")))
    effects = _flags(payload, "sundry")  # the adapter lists the actor's effects when it is active
    if isinstance(effects, dict) and isinstance(effects.get("effects"), list):
        said.append("effect-reaction-used" in effects["effects"])
    return any(said) if said else None


def evidence(payload: dict) -> list[str]:
    """What the readers that speak add, in words, for the GM reading a discrepancy."""
    found = []
    if (seen := visioner(payload)) is not None:
        found.append(f"PF2e Visioner: {seen}")
    if (used := reaction_used(payload)) is not None:
        found.append(f"reaction used: {used}")
    return found
