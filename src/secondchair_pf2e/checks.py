"""PF2e rules checks: each observed outcome tested against its own trace (RUL-14..16, ADR 0011).

The `secondchair.rules_checks` entry point. The adapter records each outcome as a
`pf2e.outcome` observation (docs/contracts/pf2e-outcome.schema.json); a check reads only that
trace and the readers' evidence, never a character sheet nor the full rules (RUL-15), so the
bench replays it from recorded traces without Foundry (RUL-16). House rules that write into the
trace (`dosAdjustments`, modifiers in the breakdown) are consistent by construction, since the
degree is never recomputed from the total and the DC alone (RUL-23).
"""

from collections.abc import Callable

from secondchair_pf2e import readers
from secondchair_pf2e.readers import DEGREES

KIND = "pf2e.outcome"

# The kinds of rules check, what a house rule silences (RUL-24).
CHECKS = ("modifiers", "degree", "damage", "resource", "conditions", "activity")

# What an activity's degree does to its target (Player Core): the one real calculation the
# activity check needs (RUL-15). ponytail: three activities; add one when a table needs it.
ACTIVITIES: dict[str, dict[str, tuple[str, int | None]]] = {
    "demoralize": {"success": ("frightened", 1), "criticalSuccess": ("frightened", 2)},
    "trip": {"success": ("prone", None), "criticalSuccess": ("prone", None)},
    "grapple": {"success": ("grabbed", None), "criticalSuccess": ("restrained", None)},
}

type Failure = tuple[str, str]  # (check kind, what is inconsistent)


def check(observation: dict, earlier: Callable[[], list[dict]]) -> list[Failure]:
    """Every failed check on one observation; `earlier` gives its session's observations."""
    if observation.get("kind") != KIND:
        return []
    p = observation["payload"]
    failures = [
        *modifiers(p),
        *degree(p),
        *damage(p),
        *resource(p),
        *conditions(p),
        *activity(observation, earlier),
    ]
    if failures and (seen := readers.evidence(p)):
        failures = [(kind, f"{text} ({'; '.join(seen)})") for kind, text in failures]
    return failures


def modifiers(p: dict) -> list[Failure]:
    """The enabled modifiers of the breakdown sum to the total, less the natural die."""
    roll = p.get("roll")
    if not isinstance(roll, dict) or roll.get("natural") is None:
        return []
    applied = sum(m["modifier"] for m in roll["modifiers"] if m["enabled"])
    if roll["natural"] + applied == roll["total"]:
        return []
    return [
        (
            "modifiers",
            f"{_what(p)}: the die ({roll['natural']}) and the modifiers ({applied:+d}) make "
            f"{roll['natural'] + applied}, but the total is {roll['total']}.",
        )
    ]


def _degree(total: int, dc: int, natural: int | None) -> int:
    """The unadjusted degree: total against DC, then a natural 20 or 1 moves it one step."""
    found = 3 if total - dc >= 10 else 0 if dc - total >= 10 else 2 if total >= dc else 1
    step = 1 if natural == 20 else -1 if natural == 1 else 0
    return min(3, max(0, found + step))


def _adjust(unadjusted: int, adjustments: dict) -> int:
    """pf2e's DegreeOfSuccess: the first adjustment that applies, "all" first."""
    for outcome in ("all", *DEGREES):
        amount = (adjustments.get(outcome) or {}).get("amount")
        if (
            amount
            and not (unadjusted == 3 and amount == 1)
            and not (unadjusted == 0 and amount == -1)
            and (outcome == "all" or DEGREES.index(outcome) == unadjusted)
        ):
            if isinstance(amount, str):
                return DEGREES.index(amount)
            return min(3, max(0, unadjusted + amount))
    return unadjusted


def _degree_failures(
    what: str, total: int, dc: int, natural: int | None, trace: dict, adjustments: dict | None
) -> list[Failure]:
    found = _degree(total, dc, natural)
    if trace.get("unadjusted") not in (None, DEGREES[found]):
        return [
            (
                "degree",
                f"{what}: {total} against DC {dc}"
                + (f" with a natural {natural}" if natural in (1, 20) else "")
                + f" is a {DEGREES[found]}, but the roll recorded {trace['unadjusted']}.",
            )
        ]
    if adjustments is None:  # no reader for the adjustments: the pf2e trace alone (RUL-20)
        return []
    adjusted = _adjust(found, adjustments)
    if trace.get("degree") in (None, DEGREES[adjusted]):
        return []
    labels = ", ".join(a["label"] for a in adjustments.values()) or "no adjustment"
    return [
        (
            "degree",
            f"{what}: a {DEGREES[found]} adjusted by {labels} is a {DEGREES[adjusted]}, but the "
            f"roll recorded {trace['degree']}.",
        )
    ]


def degree(p: dict) -> list[Failure]:
    """The degree follows from the DC, the natural 20 or 1 and the recorded adjustments; so does
    each save PF2e Toolbelt's Target Helper recorded."""
    found: list[Failure] = []
    roll = p.get("roll")
    if isinstance(roll, dict) and p.get("dc") is not None and p.get("degree") is not None:
        found += _degree_failures(
            _what(p), roll["total"], p["dc"], roll["natural"], p, readers.dos_adjustments(p)
        )
    for save in readers.toolbelt_saves(p) or []:
        what = f"{_what(p)}, save of {save['target']} (PF2e Toolbelt)"
        found += _degree_failures(
            what, save["total"], save["dc"], save["natural"], save, save["adjustments"]
        )
    return found


def damage(p: dict) -> list[Failure]:
    """HP lost equals the damage minus the IWR shown, within the HP there were. A shield that
    absorbed part of it leaves no trace of how much: no check then."""
    dealt, hp = p.get("damage"), p.get("hp")
    if not (isinstance(dealt, dict) and isinstance(hp, dict)) or p.get("shield"):
        return []
    pool = hp["before"]["value"] + hp["before"]["temp"]
    lost = pool - hp["after"]["value"] - hp["after"]["temp"]
    iwr = sum(a["adjustment"] for a in p.get("iwr", []))
    total = dealt["total"]

    # ponytail: the pf2e chat buttons apply the roll whole, doubled or halved and record no
    # multiplier, so each is accepted; one recorded by the adapter would make this exact.
    def cost(base: int) -> int:
        return min(pool, max(0, base + iwr))

    if lost in {cost(base) for base in (total, 2 * total, total // 2, max(1, total // 2))}:
        return []
    shown = f"{iwr:+d} from IWR" if p.get("iwr") else "no IWR"
    return [
        (
            "damage",
            f"{_what(p)}: {total} damage with {shown} should cost {cost(total)} HP (or as much "
            f"for its double or half), but {lost} HP were lost.",
        )
    ]


def resource(p: dict) -> list[Failure]:
    """A cast that spends a slot, focus point or innate use decrements it."""
    spent = p.get("resource")
    if not isinstance(spent, dict) or spent["kind"] == "none":
        return []
    if spent["after"] < spent["before"]:
        return []
    return [
        (
            "resource",
            f"{_what(p)}: the {spent['kind']} went from {spent['before']} to {spent['after']}, "
            "not decremented.",
        )
    ]


def conditions(p: dict) -> list[Failure]:
    """The condition lifecycle holds: a valued condition is at 1 or more, and a dying creature
    is unconscious."""
    change = p.get("conditions")
    if not isinstance(change, dict):
        return []
    after = change["after"]
    found = [
        ("conditions", f"{_what(p)}: {slug} {value} is still applied, at no value.")
        for slug, value in after.items()
        if value is not None and value < 1
    ]
    if "dying" in after and "unconscious" not in after:
        found.append(("conditions", f"{_what(p)}: dying {after['dying']} but not unconscious."))
    return found


def activity(observation: dict, earlier: Callable[[], list[dict]]) -> list[Failure]:
    """A condition an activity gives its target matches the activity's degree: the latest
    activity rolled against this actor in the session before the change."""
    p = observation["payload"]
    change = p.get("conditions")
    if not (isinstance(change, dict) and isinstance(change.get("before"), dict)):
        return []
    before, after = change["before"], change["after"]
    gained = {
        slug: value
        for slug, value in after.items()
        if slug not in before or (value or 0) > (before[slug] or 0)
    }
    given = {slug for table in ACTIVITIES.values() for slug, _ in table.values()}
    if not gained.keys() & given:
        return []
    rolled = None
    for o in earlier():
        if o["id"] == observation["id"]:
            break
        q = o["payload"]
        if (
            o["kind"] == KIND
            and q.get("target") == p.get("actor")
            and q.get("action") in ACTIVITIES
            and q.get("degree") in DEGREES
        ):
            rolled = q
    if rolled is None:
        return []
    table = ACTIVITIES[rolled["action"]]
    expected = table.get(rolled["degree"])
    found = []
    for slug, value in gained.items():
        if slug not in {s for s, _ in table.values()}:
            continue
        if expected is None or expected[0] != slug or expected[1] not in (None, value):
            should = (
                f"{expected[0]}{'' if expected[1] is None else f' {expected[1]}'}"
                if expected
                else "nothing"
            )
            got = f"{slug}{'' if value is None else f' {value}'}"
            found.append(
                (
                    "activity",
                    f"{_what(p)}: {rolled['action']} at {rolled['degree']} gives {should}, "
                    f"but {got} was applied.",
                )
            )
    return found


def _what(p: dict) -> str:
    who = p.get("actor") or "an unknown actor"
    where = f" (message {p['message']})" if p.get("message") else ""
    return f"{p.get('type', 'outcome')} of {who}{where}"
