"""The PF2e calculators: threat, XP and treasure, pure and usable offline for prep (BVE-02,
02-architecture.md). The v3 tables, transplanted: GM Core p.75-76 (Tables 10-1 and 10-2,
Different Party Sizes), p.56 (Table 10-8, XP Awards), p.59 (Table 10-9) and p.61 (Different
Party Sizes). Keys of the XP tables are the creature's level less the party's.

The `secondchair.tools` entry point registers them as prep reads, so a prep agent calibrates an
encounter or a hoard through the Core (ARC-03).
"""

from typing import Any, NamedTuple

from secondchair.core.tools import Tool
from secondchair.core.workspace import Workspace

THREATS = ("trivial", "low", "moderate", "severe", "extreme")
CREATURE_XP = {-4: 10, -3: 15, -2: 20, -1: 30, 0: 40, 1: 60, 2: 80, 3: 120, 4: 160}
SIMPLE_HAZARD_XP = {-4: 2, -3: 3, -2: 4, -1: 6, 0: 8, 1: 12, 2: 16, 3: 24, 4: 32}
COMPLEX_HAZARD_XP = CREATURE_XP
BUDGET_4PC = {"trivial": 40, "low": 60, "moderate": 80, "severe": 120, "extreme": 160}
PER_EXTRA_PC = {"trivial": 10, "low": 20, "moderate": 20, "severe": 30, "extreme": 40}
ACCOMPLISHMENT_XP = {"minor": 10, "moderate": 30, "major": 80}
LEVEL_UP_XP = 1000


class Treasure(NamedTuple):
    total_gp: int
    currency_gp: int
    extra_pc_currency_gp: int
    permanent: dict[int, int]  # item level: count
    consumables: dict[int, int]


def _row(n: int, total: int, currency: int, extra: int) -> Treasure:
    return Treasure(total, currency, extra, {n + 1: 2, n: 2}, {n + 1: 2, n: 2, n - 1: 2})


_LEVELS = [
    *[(175, 40, 10), (300, 70, 18), (500, 120, 30), (850, 200, 50), (1350, 320, 80)],
    *[(2000, 500, 125), (2900, 720, 180), (4000, 1000, 250), (5700, 1400, 350)],
    *[(8000, 2000, 500), (11500, 2800, 700), (16500, 4000, 1000), (25000, 6000, 1500)],
    *[(36500, 9000, 2250), (54500, 13000, 3250), (82500, 20000, 5000)],
    *[(128000, 30000, 7500), (208000, 48000, 12000), (355000, 80000, 20000)],
]
TREASURE = {n: _row(n, *row) for n, row in enumerate(_LEVELS, 1)}
TREASURE[1] = TREASURE[1]._replace(consumables={2: 2, 1: 3})
TREASURE[20] = Treasure(490000, 140000, 35000, {20: 4}, {20: 4, 19: 2})
EXTRA_PC = {"permanent": 1, "consumables": 2}  # per PC beyond 4, at the party level or +1


class CalculatorError(ValueError):
    """Input outside the GM Core tables, with a message for the GM."""


def _party(level: int, size: int) -> None:
    if not (type(level) is int and 1 <= level <= 20 and type(size) is int and size >= 1):
        raise CalculatorError("Expected a party level from 1 to 20 and a party size of 1 or more.")


def budgets(size: int) -> dict[str, int]:
    """The XP budget of each threat for a party of `size`."""
    return {t: max(0, BUDGET_4PC[t] + (size - 4) * PER_EXTRA_PC[t]) for t in THREATS}


def threat(total: int, size: int) -> str:
    """The threat of an encounter worth `total` XP: trivial at or below its budget, otherwise the
    highest budget it meets."""
    found = budgets(size)
    if total <= found["trivial"]:
        return "trivial"
    return next((t for t in reversed(THREATS[1:]) if found[t] <= total), "low")


def encounter(
    level: int,
    size: int,
    creatures: list[int],
    simple_hazards: list[int] | None = None,
    complex_hazards: list[int] | None = None,
) -> dict[str, Any]:
    """An encounter's XP lines, total, threat and the XP each PC is awarded (the 4-PC value,
    GM Core p.56; 0 when trivial). Each list holds one level per creature or hazard."""
    _party(level, size)
    foes = [
        *(("creature", c, CREATURE_XP) for c in creatures),
        *(("simple hazard", h, SIMPLE_HAZARD_XP) for h in simple_hazards or []),
        *(("complex hazard", h, COMPLEX_HAZARD_XP) for h in complex_hazards or []),
    ]
    if not foes:
        raise CalculatorError("An encounter needs at least one creature or hazard.")
    lines: list[dict[str, Any]] = []
    for kind, foe, table in foes:
        if (foe - level) not in table:
            raise CalculatorError(
                f"A level {foe} {kind} against a level {level} party is outside the table "
                "(PL-4 to PL+4, GM Core p.76)."
            )
        lines.append({"kind": kind, "level": foe, "delta": foe - level, "xp": table[foe - level]})
    total = sum(line["xp"] for line in lines)
    found = threat(total, size)
    award = 0 if found == "trivial" else max(0, total - (size - 4) * PER_EXTRA_PC[found])
    return {
        "lines": lines,
        "total": total,
        "threat": found,
        "budgets": budgets(size),
        "award": award,
    }


def accomplishments(kinds: list[str]) -> int:
    """The XP each PC gets for accomplishments, minor, moderate or major."""
    unknown = [k for k in kinds if k not in ACCOMPLISHMENT_XP]
    if unknown:
        raise CalculatorError(f"Unknown accomplishment {unknown[0]!r}: minor, moderate or major.")
    return sum(ACCOMPLISHMENT_XP[k] for k in kinds)


def treasure(level: int, size: int) -> dict[str, Any]:
    """The party's treasure for a level: the budget in gp (currency adjusted per PC beyond or
    short of 4), and the items by item level; per PC beyond 4, uncosted extra items."""
    if type(level) is not int or level not in TREASURE:
        raise CalculatorError("Treasure levels run 1 to 20.")
    _party(level, size)
    row = TREASURE[level]
    extra = size - 4
    return {
        "budget_gp": row.total_gp + extra * row.extra_pc_currency_gp,
        "currency_gp": row.currency_gp + extra * row.extra_pc_currency_gp,
        "permanent": row.permanent,
        "consumables": row.consumables,
        "extra_pc": {"pcs": extra, **{k: extra * v for k, v in EXTRA_PC.items()}},
    }


def tools(ws: Workspace) -> list[Tool]:
    """The calculators as prep reads (docs/contracts/tool-registration.md)."""

    def encounter_xp(
        party_level: int,
        party_size: int,
        creatures: list[int],
        simple_hazards: list[int] | None = None,
        complex_hazards: list[int] | None = None,
    ) -> dict[str, Any]:
        """Calibrate a PF2e encounter (GM Core): each creature's and hazard's XP from its level
        against the party's, the total, its threat (trivial, low, moderate, severe, extreme),
        the threat budgets for this party size, and the XP each PC is awarded. Give one level per
        creature or hazard."""
        return encounter(party_level, party_size, creatures, simple_hazards, complex_hazards)

    def treasure_budget(party_level: int, party_size: int) -> dict[str, Any]:
        """The PF2e party treasure for a level (GM Core Table 10-9): the budget in gp, the
        currency, the permanent items and consumables by item level, and the extra items per PC
        beyond 4."""
        return treasure(party_level, party_size)

    return [
        Tool(fn=fn, responsibility="prep", delegated_action=False, reversible=True)
        for fn in (encounter_xp, treasure_budget)
    ]
