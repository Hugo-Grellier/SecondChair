"""Friction detectors and manual acts (TRC-03, ADR 0012; docs/contracts/workspace-layout.md).

A closed list of deterministic detectors, no model: each reads one user's behaviour trace
records for one moment and returns its frictions, each citing its trace span (the `t` of its
first and last record). Thresholds are in seconds, tunable per campaign under `frictions` in
`workspace.yaml`. What SecondChair itself does is never the user's: the windows of its own
applications (class names starting with `SecondChair`, the Director's Desk among them) and the
semantic events recorded while it acts through the GM's client (`by: secondchair`) are left out,
so a Desk interaction counts once, as the GM interaction the Core logs.
"""

import re
from collections.abc import Callable, Iterator
from itertools import pairwise

import yaml

from secondchair.core.workspace import CONFIG_FILE, Workspace, WorkspaceError

DEFAULTS: dict[str, dict] = {
    "rules_lookup": {"apps": ["Compendium", "CompendiumBrowser"]},
    "hunting": {"windows": 3, "within": 30},
    "long_creature_turn": {"over": 90},
    "manual_correction": {"within": 10},
    "dead_time": {"over": 20},
    "long_turn": {"over": 120},
    "cancelled_roll_dialog": {},
    "rage_clicks": {"clicks": 3, "within": 2, "radius": 10},
    "click_on_nothing": {"within": 1},
    "targeting_fixed": {"within": 10},
    "stumbling_input": {"deletions": 5, "share": 0.25, "pause": 2},
}
GM_DETECTORS = ("rules_lookup", "hunting", "long_creature_turn", "manual_correction", "dead_time")
PLAYER_DETECTORS = (
    "long_turn",
    "hunting",
    "cancelled_roll_dialog",
    "rage_clicks",
    "click_on_nothing",
    "targeting_fixed",
    "rules_lookup",
    "stumbling_input",
)
# The library's own events; any other is a system adapter's, an action of its system.
GENERIC = {
    "window.open",
    "window.close",
    "roll",
    "target",
    "move",
    "turn",
    "focus",
    "blur",
    "undo",
    "roll.cancel",
    "move.cancel",
}
# ponytail: a click lands on an element, not on its ancestors; one on a control's icon or label
# inside a button without data-action reads as a click on nothing.
INTERACTIVE = {"a", "button", "input", "select", "textarea", "label", "option", "summary", "canvas"}

type Span = tuple[int, int]


def thresholds(ws: Workspace) -> dict[str, dict]:
    """The detectors' thresholds: the defaults, overridden by `frictions` in workspace.yaml."""
    path = ws.root / CONFIG_FILE
    tuned = (yaml.safe_load(path.read_text()) or {}).get("frictions") or {}
    if not isinstance(tuned, dict) or any(
        k not in DEFAULTS or not isinstance(v, dict) for k, v in tuned.items()
    ):
        raise WorkspaceError(
            f"{path}: frictions maps detectors ({', '.join(DEFAULTS)}) to their thresholds; "
            f"got {tuned!r}."
        )
    return {k: {**v, **tuned.get(k, {})} for k, v in DEFAULTS.items()}


def _own(records: list[dict]) -> list[dict]:
    """The user's own records, in time order: not SecondChair's, not gaps."""
    return sorted(
        (
            r
            for r in records
            if r.get("stream") in ("semantic", "input")
            and r.get("by") != "secondchair"
            and not str(r.get("app") or "").startswith("SecondChair")
        ),
        key=lambda r: r["t"],
    )


def _event(r: dict) -> str | None:
    return r.get("event") if r["stream"] == "semantic" else None


def _is(r: dict, name: str) -> bool:
    """A generic event, or a system adapter's of the same name (`pf2e.roll.cancel`)."""
    event = _event(r) or ""
    return event == name or event.endswith(f".{name}")


def _system_action(r: dict) -> bool:
    event = _event(r)
    return event is not None and event not in GENERIC and not _is(r, "roll.cancel")


def _act(r: dict) -> bool:
    """A manual act in the VTT: a roll, a token moved or targeted, a system action, a drop."""
    return _event(r) in ("roll", "move", "target") or _system_action(r) or r.get("input") == "drop"


def manual_acts(records: list[dict]) -> int:
    """How many manual acts the records hold (counted in GM effort for a GM)."""
    return sum(_act(r) for r in _own(records))


def detect(records: list[dict], user: str, gm: bool, moment: str, limits: dict) -> list[dict]:
    """The frictions in one user's records of one moment, in time order."""
    recs = _own(records)
    found = []
    for name in GM_DETECTORS if gm else PLAYER_DETECTORS:
        if name == "rules_lookup" and gm and moment != "live-session":
            continue  # a GM's lookups count in live play only
        found += [
            {"detector": name, "from": a, "to": b}
            for a, b in DETECTORS[name](recs, user, limits[name])
        ]
    return sorted(found, key=lambda f: (f["from"], f["to"]))


def _closes(recs: list[dict], i: int) -> int:
    """When the window opened by recs[i] closed, or its opening when it never did."""
    window = recs[i].get("window")
    return next(
        (
            r["t"]
            for r in recs[i + 1 :]
            if _event(r) == "window.close" and r.get("window") == window
        ),
        recs[i]["t"],
    )


def rules_lookup(recs: list[dict], _user: str, lim: dict) -> Iterator[Span]:
    """A compendium document or the compendium's own window opened."""
    for i, r in enumerate(recs):
        if _event(r) == "window.open" and (
            str(r.get("document") or "").startswith("Compendium.") or r.get("app") in lim["apps"]
        ):
            yield r["t"], _closes(recs, i)


def hunting(recs: list[dict], _user: str, lim: dict) -> Iterator[Span]:
    """At least `windows` windows opened and closed within `within` s, with no act between."""
    opened: dict[object, int] = {}
    closed: list[Span] = []
    for r in recs:
        if _act(r):
            closed = []
        elif _event(r) == "window.open":
            opened[r.get("window")] = r["t"]
        elif _event(r) == "window.close" and r.get("window") in opened:
            closed.append((opened.pop(r.get("window")), r["t"]))
            closed = [c for c in closed if c[0] >= r["t"] - lim["within"] * 1000]
            if len(closed) >= lim["windows"]:
                yield closed[0][0], r["t"]
                closed = []


def _turns(recs: list[dict]) -> Iterator[tuple[list[str], int, int]]:
    """Each turn this client saw end: whose it was (the users owning its combatant), its span.
    ponytail: a turn still running when the records stop is not measured."""
    turns = [r for r in recs if _event(r) == "turn" and isinstance(r.get("players"), list)]
    for a, b in pairwise(turns):
        yield a["players"], a["t"], b["t"]


def long_creature_turn(recs: list[dict], _user: str, lim: dict) -> Iterator[Span]:
    """A turn of a creature no player owns lasting over `over` s."""
    for players, a, b in _turns(recs):
        if not players and b - a > lim["over"] * 1000:
            yield a, b


def long_turn(recs: list[dict], user: str, lim: dict) -> Iterator[Span]:
    """A turn of the player's own combatant lasting over `over` s."""
    for players, a, b in _turns(recs):
        if user in players and b - a > lim["over"] * 1000:
            yield a, b


def dead_time(recs: list[dict], _user: str, lim: dict) -> Iterator[Span]:
    """In a GM creature's turn, over `over` s with no input at all."""
    for players, a, b in _turns(recs):
        if players:
            continue
        times = [a, *(r["t"] for r in recs if r["stream"] == "input" and a < r["t"] < b), b]
        for x, y in pairwise(times):
            if y - x > lim["over"] * 1000:
                yield x, y


def manual_correction(recs: list[dict], _user: str, lim: dict) -> Iterator[Span]:
    """An undo (Ctrl or Cmd+Z outside a text field), a cancelled move, or the same roll made
    again within `within` s."""
    last: dict | None = None
    for r in recs:
        undo = r.get("input") == "key" and str(r.get("key")).lower() == "z"
        if _is(r, "undo") or _is(r, "move.cancel") or (undo and (r.get("ctrl") or r.get("meta"))):
            yield r["t"], r["t"]
        elif _event(r) == "roll":
            if (
                last
                and last.get("formulas") == r.get("formulas")
                and r["t"] - last["t"] <= lim["within"] * 1000
            ):
                yield last["t"], r["t"]
            last = r


def cancelled_roll_dialog(recs: list[dict], _user: str, _lim: dict) -> Iterator[Span]:
    """A roll dialog closed without rolling, as the system adapter reports it."""
    yield from ((r["t"], r["t"]) for r in recs if _is(r, "roll.cancel"))


def targeting_fixed(recs: list[dict], _user: str, lim: dict) -> Iterator[Span]:
    """A target changed within `within` s after an action started: a roll, a system action or
    a roll dialog."""
    start: int | None = None
    for r in recs:
        if _event(r) == "target" and start is not None and r["t"] - start <= lim["within"] * 1000:
            yield start, r["t"]
        elif _event(r) == "roll" or _system_action(r) or _is(r, "roll.cancel"):
            start = r["t"]


def _clicks(recs: list[dict]) -> list[dict]:
    return [r for r in recs if r.get("input") == "click"]


def rage_clicks(recs: list[dict], _user: str, lim: dict) -> Iterator[Span]:
    """At least `clicks` clicks within `within` s, all within `radius` px of the first."""
    clicks, i = _clicks(recs), 0
    while i < len(clicks):
        first = clicks[i]
        burst = [
            c
            for c in clicks[i:]
            if c["t"] - first["t"] <= lim["within"] * 1000
            and abs(c.get("x", 0) - first.get("x", 0)) <= lim["radius"]
            and abs(c.get("y", 0) - first.get("y", 0)) <= lim["radius"]
        ]
        if len(burst) >= lim["clicks"]:
            yield first["t"], burst[-1]["t"]
            i = clicks.index(burst[-1]) + 1
        else:
            i += 1


def click_on_nothing(recs: list[dict], _user: str, lim: dict) -> Iterator[Span]:
    """A left click on an element that is no control, followed by no event within `within` s."""
    for c in _clicks(recs):
        target = c.get("target")
        if c.get("button") != 0 or not isinstance(target, str) or "[data-action" in target:
            continue
        tag = re.match(r"[a-z0-9-]*", target)
        if tag and tag.group() in INTERACTIVE:
            continue
        if not any(
            r["stream"] == "semantic" and c["t"] < r["t"] <= c["t"] + lim["within"] * 1000
            for r in recs
        ):
            yield c["t"], c["t"]


def stumbling_input(recs: list[dict], _user: str, lim: dict) -> Iterator[Span]:
    """A burst of typing (no pause over `pause` s) with at least `deletions` deletions making at
    least `share` of its key presses."""
    keys = [r for r in recs if r.get("input") == "type"]
    bursts: list[list[dict]] = []
    for k in keys:
        if bursts and k["t"] - bursts[-1][-1]["t"] <= lim["pause"] * 1000:
            bursts[-1].append(k)
        else:
            bursts.append([k])
    for b in bursts:
        dels = sum(bool(k.get("del")) for k in b)
        if dels >= lim["deletions"] and dels / len(b) >= lim["share"]:
            yield b[0]["t"], b[-1]["t"]


DETECTORS: dict[str, Callable[[list[dict], str, dict], Iterator[Span]]] = {
    "rules_lookup": rules_lookup,
    "hunting": hunting,
    "long_creature_turn": long_creature_turn,
    "manual_correction": manual_correction,
    "dead_time": dead_time,
    "long_turn": long_turn,
    "cancelled_roll_dialog": cancelled_roll_dialog,
    "rage_clicks": rage_clicks,
    "click_on_nothing": click_on_nothing,
    "targeting_fixed": targeting_fixed,
    "stumbling_input": stumbling_input,
}
