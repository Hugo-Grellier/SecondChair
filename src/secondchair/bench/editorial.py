"""Deterministic editorial metrics (#182): what a prep artifact shows without a human or a model.

Reported only, never a gate (docs/bench/editorial). Each metric is a named check; a branch adds its
own by registering a function in `CHECKS`, for example `check_prep` (#178) or the spotlight count
(#176). Only what is on main is wired: the mystery warnings, the audience guard, the attempts the
Core logged for a job (ARC-27, no token counts exist yet) and the size of the GM's edit.
"""

import difflib
import random
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from secondchair.core import jobs, knowledge, mystery
from secondchair.core.index import CanonError
from secondchair.core.workspace import Workspace

Check = Callable[[Workspace, dict[str, Any]], Any]


def _mystery_warnings(ws: Workspace, a: dict) -> list[str]:
    [tool] = [t for t in mystery.tools(ws) if t.name == "check_mystery"]
    return [w["code"] for w in tool.fn(mystery=a["mystery"])["warnings"]]


def _guard(ws: Workspace, a: dict) -> list[str]:
    try:
        knowledge.guard(ws, a["audience"], a["text"], a.get("cites", []))
    except knowledge.AudienceRefused as refusal:
        return [str(refusal)]
    return []


def _cost(ws: Workspace, a: dict) -> dict:
    attempts = jobs.read(ws, a["job"])["attempts"]
    return {"attempts": len(attempts), "failed": sum(x["outcome"] == "failed" for x in attempts)}


def _diff(_: Workspace, a: dict) -> int:
    """Lines added or removed between the agent's draft and the version the GM adopted."""
    lines = difflib.unified_diff(a["draft"].splitlines(), a["adopted"].splitlines(), n=0)
    return sum(x[0] in "+-" and x[:3] not in ("+++", "---") for x in lines)


# check name -> (artifact key it needs, check)
CHECKS: dict[str, tuple[str, Check]] = {
    "mystery_warnings": ("mystery", _mystery_warnings),
    "guard": ("audience", _guard),
    "cost": ("job", _cost),
    "diff_lines": ("adopted", _diff),
}


def metrics(ws: Workspace, artifact: dict) -> dict:
    """Every registered check whose input the artifact carries. A check that cannot run (a
    missing mystery or job) reports its error instead of hiding the artifact."""
    out: dict[str, Any] = {}
    for name, (needs, check) in CHECKS.items():
        if needs not in artifact:
            continue
        try:
            out[name] = check(ws, artifact)
        except (CanonError, jobs.DelegationError) as error:
            out[name] = f"error: {error}"
    return out


def markdown(rows: dict[str, dict]) -> str:
    """One row per artifact id, one column per metric that any artifact reports."""
    names = [n for n in CHECKS if any(n in r for r in rows.values())]
    lines = ["| Artifact | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for artifact, row in rows.items():
        cells = [str(row.get(n, "-")).replace("|", "/") for n in names]
        lines.append(f"| {artifact} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def abandoned_prep(log: Path) -> list[str]:
    """Scenes and clues prepared and not played, from a filled table-use log."""
    prep = yaml.safe_load(log.read_text())["prep"]
    used = set(prep["used"])
    return [p for p in prep["prepared"] if p not in used]


_FRONT_MATTER = re.compile(r"\A﻿?\s*---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _loose(value: str) -> str:
    """Regex for a value where '-', '_' and ' ' are interchangeable."""
    return r"[-_ ]+".join(re.escape(w) for w in re.split(r"[-_\s]+", value.strip()))


def blind(candidates: list[dict], out: Path, key: Path, seed: int) -> dict[str, str]:
    """Render candidates into one template for blind human review (#182, decision 25).

    A candidate is `{"id", "provenance": {model, host, tier, ...}, "text"}`. Each is written to
    `out/<letter>.md` with front matter and HTML comments dropped and every provenance value
    redacted from the body (longest first; '-', '_' and ' ' match each other); the letters follow
    a seeded shuffle of the id-sorted candidates, so the same input and seed give the same files.
    The sealed key (letter -> id, provenance) goes to `key`, which must lie outside `out` so a
    reviewer's folder never holds it. Everything is validated before the first write; `out` must
    be absent or empty. Returns letter -> id.
    """
    if len(candidates) > 26:  # ponytail: letters A-Z, enough for the three-way comparison
        raise ValueError(f"at most 26 candidates, got {len(candidates)}")
    ids = [c["id"] for c in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("candidate ids must be unique")
    for c in candidates:
        for k, v in c["provenance"].items():
            if not isinstance(v, str | int | float | bool):
                raise ValueError(f"provenance {k!r} of {c['id']} must be a scalar")
            if 0 < len(str(v).strip()) < 3:
                raise ValueError(f"provenance {k!r} of {c['id']} is too short to redact safely")
    if out.resolve() == key.resolve() or out.resolve() in key.resolve().parents:
        raise ValueError("the sealed key must live outside the rendered folder")
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"{out} is not empty")
    ordered = sorted(candidates, key=lambda c: c["id"])
    random.Random(seed).shuffle(ordered)
    out.mkdir(parents=True, exist_ok=True)
    sealed: dict[str, dict] = {}
    for i, c in enumerate(ordered):
        letter = chr(ord("A") + i)
        body = _COMMENT.sub("", _FRONT_MATTER.sub("", c["text"]))
        values = {str(v).strip() for v in c["provenance"].values() if str(v).strip()}
        for value in sorted(values, key=len, reverse=True):
            body = re.sub(_loose(value), "[redacted]", body, flags=re.I)
        (out / f"{letter}.md").write_text(f"# Candidate {letter}\n\n{body.strip()}\n")
        sealed[letter] = {"id": c["id"], "provenance": c["provenance"]}
    key.write_text(yaml.safe_dump(sealed, sort_keys=True))
    return {k: v["id"] for k, v in sealed.items()}
