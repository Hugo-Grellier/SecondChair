"""Friction detectors and GM manual acts, read from behaviour traces (TRC-03; ADR 0012).

A closed list of deterministic detectors, no model. Each turns one user's trace records of one
moment into frictions, each citing its trace span: the `t` of the first and last records it rests
on. Thresholds are tunable per campaign under `friction_thresholds` in `workspace.yaml`. GM
frictions and manual acts count in GM effort; player frictions are table friction, never part of
GM effort (MET GM effort, Table friction).
"""

import math
from collections.abc import Callable, Iterator

from secondchair.core.workspace import WorkspaceError

THRESHOLDS: dict[str, float] = {
    "hunting_windows": 3,  # windows opened and closed with no action in between...
    "hunting_s": 30,  # ...within this many seconds
    "gm_turn_s": 90,  # a GM-creature turn longer than this is long
    "player_turn_s": 120,  # a player's turn longer than this is long
    "dead_time_s": 20,  # no input for this long in the GM's own turn
    "correction_s": 10,  # an undo, cancelled move or re-roll this soon after the act it fixes
    "rage_clicks": 3,  # clicks at one spot...
    "rage_s": 2,  # ...within this many seconds...
    "rage_px": 24,  # ...within this many screen pixels of the first
    "retarget_s": 10,  # targeting changed this soon after an action started
    "stumble_deletions": 5,  # deletions while typing...
    "stumble_s": 10,  # ...within this many seconds
}

type Span = tuple[int, int]
type Records = list[dict]
type Detector = Callable[[Records, dict[str, float]], Iterator[Span]]

# Generic semantic events of the library that are not acts (foundry-bridge.md, "Behaviour traces").
_NOT_ACTS = {"window.open", "window.close", "turn", "focus", "blur", "move.cancel", "roll.cancel"}
_ACTION_STARTS = ("action", "strike", "spell")


def thresholds(config: dict) -> dict[str, float]:
    """The campaign's thresholds: the defaults, overridden by `friction_thresholds`."""
    tuned = config.get("friction_thresholds") or {}
    if not isinstance(tuned, dict) or any(
        k not in THRESHOLDS or type(v) not in (int, float) or not v > 0 for k, v in tuned.items()
    ):
        raise WorkspaceError(
            "workspace.yaml: friction_thresholds maps threshold names to positive numbers; "
            f"known names: {', '.join(THRESHOLDS)}."
        )
    return THRESHOLDS | tuned


def _clean(records: Records) -> Records:
    """The records with the fields detectors read in the types they expect: a player's client
    could send anything (TRC-05), and a bad field must never stop the report. SecondChair's own
    windows (the Director's Desk) are left out: they are not the user hunting in the VTT."""
    out = []
    for r in records:
        r = dict(r)
        for key in ("event", "window", "document", "target", "key", "input"):
            if key in r and r[key] is not None:
                r[key] = str(r[key])
        for key in ("x", "y"):
            r[key] = r.get(key) if type(r.get(key)) in (int, float) else 0
        f = r.get("formulas")
        r["formulas"] = tuple(map(str, f)) if isinstance(f, list) else ()
        if r.get("event", "").startswith("window.") and (
            r.get("secondchair") or r.get("window", "").startswith("secondchair-")
        ):
            continue
        out.append(r)
    return sorted(out, key=lambda r: r["t"])


def _event(r: dict) -> str:
    return r.get("event", "") if r.get("stream") == "semantic" else ""


def _named(r: dict, *names: str) -> bool:
    """A semantic event of the library named so, or a system adapter's (`<system>.<name>`)."""
    event = _event(r)
    return event in names or event.partition(".")[2] in names


def _undo_key(r: dict) -> bool:
    return (
        r.get("input") == "key"
        and str(r.get("key", "")).lower() == "z"
        and bool(r.get("ctrl") or r.get("meta"))
        and not r.get("shift")
    )


def is_act(r: dict) -> bool:
    """An act in the VTT: a roll, a move, a target, an undo, or any act a system adapter traces."""
    event = _event(r)
    return _undo_key(r) or (
        bool(event) and event not in _NOT_ACTS and not event.endswith(".cancel")
    )


def manual_acts(records: Records) -> int:
    """The GM's manual acts: their acts, minus the VTT writes SecondChair itself made through the
    GM's client (tagged `secondchair`), so a Director's Desk gesture counts once, as a GM
    interaction in the action log."""
    return sum(is_act(r) and not r.get("secondchair") for r in _clean(records))


def _seconds(th: dict[str, float], key: str) -> float:
    return th[key] * 1000


def rules_lookup(rs: Records, th: dict[str, float]) -> Iterator[Span]:
    """A compendium document opened: looking a rule up."""
    for r in rs:
        if _event(r) == "window.open" and str(r.get("document") or "").startswith("Compendium."):
            yield r["t"], r["t"]


def hunting(rs: Records, th: dict[str, float]) -> Iterator[Span]:
    """Windows opened and closed one after another with no act in between."""
    opened: dict[object, int] = {}
    pairs: list[int] = []  # the opening times of the windows closed since the last act
    for r in rs:
        if _event(r) == "window.open":
            opened[r.get("window")] = r["t"]
        elif _event(r) == "window.close" and r.get("window") in opened:
            pairs.append(opened.pop(r.get("window")))
            pairs = [t for t in pairs if r["t"] - t <= _seconds(th, "hunting_s")]
            if len(pairs) >= th["hunting_windows"]:
                yield pairs[0], r["t"]
                pairs = []
        elif is_act(r):
            pairs = []


def _own_turns(rs: Records) -> Iterator[Span]:
    """The user's own turns: from a `turn` event marked `own` to the next one, or their last
    record. For the GM, a GM creature's turn."""
    start = None
    for r in rs:
        if _event(r) == "turn":
            if start is not None:
                yield start, r["t"]
            start = r["t"] if r.get("own") else None
    if start is not None and rs[-1]["t"] > start:
        yield start, rs[-1]["t"]


def _long_turn(key: str) -> Detector:
    def detect(rs: Records, th: dict[str, float]) -> Iterator[Span]:
        for start, end in _own_turns(rs):
            if end - start > _seconds(th, key):
                yield start, end

    return detect


def dead_time(rs: Records, th: dict[str, float]) -> Iterator[Span]:
    """No input at all for a while in the GM's own turn."""
    for start, end in _own_turns(rs):
        times = [
            start,
            *(r["t"] for r in rs if r.get("stream") == "input" and start < r["t"] < end),
        ]
        for a, b in zip(times, [*times[1:], end], strict=True):
            if b - a >= _seconds(th, "dead_time_s"):
                yield a, b


def manual_correction(rs: Records, th: dict[str, float]) -> Iterator[Span]:
    """An undo or a cancelled move soon after an act, or the same roll made again soon after."""
    last_act: int | None = None
    rolls: dict[tuple, int] = {}
    for r in rs:
        fixes = _undo_key(r) or _named(r, "undo", "move.cancel")
        if fixes and last_act is not None and r["t"] - last_act <= _seconds(th, "correction_s"):
            yield last_act, r["t"]
        elif _event(r) == "roll":
            formulas = r["formulas"]
            before = rolls.get(formulas)
            if before is not None and r["t"] - before <= _seconds(th, "correction_s"):
                yield before, r["t"]
            rolls[formulas] = r["t"]
        if is_act(r) and not _undo_key(r) and not _named(r, "undo"):
            last_act = r["t"]


def cancelled_roll_dialog(rs: Records, th: dict[str, float]) -> Iterator[Span]:
    for r in rs:
        if _named(r, "roll.cancel"):
            yield r["t"], r["t"]


def _clicks(rs: Records) -> list[dict]:
    return [r for r in rs if r.get("input") == "click"]


def rage_clicks(rs: Records, th: dict[str, float]) -> Iterator[Span]:
    """Clicks repeated at one spot in a short time."""
    clicks, i = _clicks(rs), 0
    while i < len(clicks):
        first = clicks[i]
        burst = [
            j
            for j in range(i, len(clicks))
            if clicks[j]["t"] - first["t"] < _seconds(th, "rage_s")
            and math.dist((clicks[j]["x"], clicks[j]["y"]), (first["x"], first["y"]))
            <= th["rage_px"]
        ]
        if len(burst) >= th["rage_clicks"]:
            yield first["t"], clicks[burst[-1]]["t"]
            i = burst[-1] + 1
        else:
            i += 1


def click_on_nothing(rs: Records, th: dict[str, float]) -> Iterator[Span]:
    """A click that landed on no element, or on the bare page."""
    for c in _clicks(rs):
        target = str(c.get("target") or "")
        if not target or target.split("#")[0].split(".")[0] in ("html", "body"):
            yield c["t"], c["t"]


def late_targeting(rs: Records, th: dict[str, float]) -> Iterator[Span]:
    """Targeting changed once an action had started."""
    started: int | None = None
    for r in rs:
        if _named(r, *_ACTION_STARTS):
            started = r["t"]
        elif _event(r) == "target" and started is not None:
            if r["t"] - started <= _seconds(th, "retarget_s"):
                yield started, r["t"]
            started = None


def stumbling_input(rs: Records, th: dict[str, float]) -> Iterator[Span]:
    """Many deletions while typing in a short time."""
    deletions = [r["t"] for r in rs if r.get("input") == "type" and r.get("del")]
    n, i = int(th["stumble_deletions"]), 0
    while i + n <= len(deletions):
        if deletions[i + n - 1] - deletions[i] <= _seconds(th, "stumble_s"):
            yield deletions[i], deletions[i + n - 1]
            i += n
        else:
            i += 1


# The closed lists (TRC-03), in the spec's order.
GM: dict[str, Detector] = {
    "rules-lookup": rules_lookup,  # in live play only: see detect()
    "hunting": hunting,
    "long-gm-creature-turn": _long_turn("gm_turn_s"),
    "manual-correction": manual_correction,
    "dead-time": dead_time,
}
PLAYER: dict[str, Detector] = {
    "long-turn": _long_turn("player_turn_s"),
    "hunting": hunting,
    "cancelled-roll-dialog": cancelled_roll_dialog,
    "rage-clicks": rage_clicks,
    "click-on-nothing": click_on_nothing,
    "late-targeting": late_targeting,
    "rules-lookup": rules_lookup,
    "stumbling-input": stumbling_input,
}


def detect(records: Records, gm: bool, moment: str, th: dict[str, float]) -> list[dict]:
    """One user's frictions in one moment, each with its detector and trace span."""
    rs = _clean(records)
    if not rs:
        return []
    found = []
    for name, detector in (GM if gm else PLAYER).items():
        if gm and name == "rules-lookup" and moment != "live-session":
            continue
        found += [{"detector": name, "from": a, "to": b} for a, b in detector(rs, th)]
    return sorted(found, key=lambda f: (f["from"], f["detector"]))
