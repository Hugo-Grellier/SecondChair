"""The PF2e calculators (BVE-02, 02-architecture.md): the v3 threat, XP and treasure cases,
transplanted as acceptance tests and run offline, with no Foundry and no workspace."""

import pytest

from secondchair_pf2e import calculators as calc
from secondchair_pf2e.calculators import CalculatorError

TOTALS = [175, 300, 500, 850, 1350, 2000, 2900, 4000, 5700, 8000, 11500, 16500, 25000, 36500]
TOTALS += [54500, 82500, 128000, 208000, 355000, 490000]
CURRENCY = [40, 70, 120, 200, 320, 500, 720, 1000, 1400, 2000, 2800, 4000, 6000, 9000, 13000]
CURRENCY += [20000, 30000, 48000, 80000, 140000]
EXTRA = [10, 18, 30, 50, 80, 125, 180, 250, 350, 500, 700, 1000, 1500, 2250, 3250, 5000, 7500]
EXTRA += [12000, 20000, 35000]


def test_the_tables_are_gm_core() -> None:
    assert calc.CREATURE_XP == {-4: 10, -3: 15, -2: 20, -1: 30, 0: 40, 1: 60, 2: 80, 3: 120, 4: 160}
    assert calc.SIMPLE_HAZARD_XP == {-4: 2, -3: 3, -2: 4, -1: 6, 0: 8, 1: 12, 2: 16, 3: 24, 4: 32}
    assert calc.COMPLEX_HAZARD_XP == calc.CREATURE_XP
    assert calc.ACCOMPLISHMENT_XP == {"minor": 10, "moderate": 30, "major": 80}
    rows = [calc.TREASURE[n] for n in range(1, 21)]
    assert [r.total_gp for r in rows] == TOTALS
    assert [r.currency_gp for r in rows] == CURRENCY
    assert [r.extra_pc_currency_gp for r in rows] == EXTRA
    assert rows[0].permanent == {2: 2, 1: 2} and rows[0].consumables == {2: 2, 1: 3}
    for n in range(2, 20):
        assert calc.TREASURE[n].permanent == {n + 1: 2, n: 2}
        assert calc.TREASURE[n].consumables == {n + 1: 2, n: 2, n - 1: 2}
    assert rows[19].permanent == {20: 4} and rows[19].consumables == {20: 4, 19: 2}


def test_budgets_by_party_size() -> None:
    assert calc.budgets(4) == {
        "trivial": 40,
        "low": 60,
        "moderate": 80,
        "severe": 120,
        "extreme": 160,
    }
    assert calc.budgets(5) == {
        "trivial": 50,
        "low": 80,
        "moderate": 100,
        "severe": 150,
        "extreme": 200,
    }
    assert calc.budgets(3) == {
        "trivial": 30,
        "low": 40,
        "moderate": 60,
        "severe": 90,
        "extreme": 120,
    }


def test_threat_between_budgets() -> None:  # GM Core: "trivial: 40 or less", else the highest met
    found = [calc.threat(xp, 4) for xp in (0, 40, 41, 59, 60, 119, 120, 160, 400)]
    assert found == [
        *("trivial", "trivial", "low", "low", "low"),
        *("moderate", "severe", "extreme", "extreme"),
    ]


@pytest.mark.parametrize(
    ("level", "size", "creatures", "total", "threat"),
    [
        (5, 4, [2], 15, "trivial"),  # GM Core p.76: level 2 against a level 5 party, PL-3
        (1, 4, [3, -3, -3, -3, -3], 120, "severe"),  # p.75 Boss and Lackeys
        (3, 4, [3, 3], 80, "moderate"),  # p.75 Mated Pair
        (4, 4, [0] * 6, 60, "low"),  # p.75 Mook Squad
        (3, 5, [3, 1, 1, 1], 100, "moderate"),  # a party of 5: Troop (80) + PL-2
        (4, 3, [0] * 6, 60, "moderate"),  # a party of 3: Mook Squad is moderate
    ],
)
def test_encounter_total_and_threat(
    level: int, size: int, creatures: list[int], total: int, threat: str
) -> None:
    found = calc.encounter(level, size, creatures)
    assert (found["total"], found["threat"]) == (total, threat)


@pytest.mark.parametrize(
    ("level", "size", "creatures", "award"),
    [
        (3, 5, [3, 1, 1, 1], 80),  # 100 XP for 5 PCs is moderate: 80 awarded (the 4-PC value)
        (3, 4, [3, 3], 80),  # a party of 4: the total
        (4, 3, [0] * 6, 80),  # 60 XP for 3 PCs is moderate: + 1 x 20
        (1, 5, [3, -3, -3, -3, -3], 100),  # 120 XP for 5 PCs is moderate: 120 - 20
        (5, 4, [2], 0),  # trivial: 0 XP (GM Core p.56)
    ],
)
def test_the_award_is_the_four_pc_value(
    level: int, size: int, creatures: list[int], award: int
) -> None:
    assert calc.encounter(level, size, creatures)["award"] == award


def test_hazards_count_in_the_budget() -> None:
    found = calc.encounter(3, 4, [3], simple_hazards=[2], complex_hazards=[4])
    assert found["total"] == 40 + 6 + 60
    assert [line["xp"] for line in found["lines"]] == [40, 6, 60]


def test_accomplishments() -> None:
    assert calc.accomplishments(["moderate"]) == 30
    assert calc.accomplishments(["minor", "major"]) == 90
    with pytest.raises(CalculatorError, match="huge"):
        calc.accomplishments(["huge"])


def test_out_of_table_is_refused() -> None:
    for level, creature in ((1, 6), (9, 4)):
        with pytest.raises(CalculatorError, match=r"PL-4 to PL\+4"):
            calc.encounter(level, 4, [creature])
    for level, size, creatures in ((21, 4, [1]), (0, 4, [1]), (1, 0, [1]), (1, 4, [])):
        with pytest.raises(CalculatorError):
            calc.encounter(level, size, creatures)


def test_treasure_budget_by_party_size() -> None:
    assert [calc.treasure(3, n)["budget_gp"] for n in (3, 4, 5)] == [470, 500, 530]
    assert calc.treasure(1, 6)["budget_gp"] == 195
    found = calc.treasure(1, 5)
    assert found["currency_gp"] == 50
    assert found["permanent"] == {2: 2, 1: 2} and found["consumables"] == {2: 2, 1: 3}
    assert found["extra_pc"] == {"pcs": 1, "permanent": 1, "consumables": 2}
    with pytest.raises(CalculatorError, match="1 to 20"):
        calc.treasure(21, 4)
    with pytest.raises(CalculatorError):
        calc.treasure(1, 0)
