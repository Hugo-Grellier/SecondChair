"""The offline compendium metadata snapshot (#190, LIC-12).

At each handshake the GM client sends pack metadata only: identifiers, level, rarity, traits,
publication. The Core keeps it in `.secondchair/compendium/<system version>.json` (derived,
rebuildable) so lookups work without Foundry and a system upgrade is noticed by diffing.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from secondchair.core.workspace import STATE_DIR, Workspace

DIR = f"{STATE_DIR}/compendium"
KEYS = (
    "uuid",
    "slug",
    "name",
    "type",
    "pack",
    "level",
    "rarity",
    "traits",
    "publication",
    "remaster",
)
VERSION = re.compile(r"[\w.+-]{1,64}")


def _latest(ws: Workspace, skip: Path | None = None) -> dict[str, Any] | None:
    files = [p for p in (ws.root / DIR).glob("*.json") if p != skip]
    return json.loads(max(files, key=lambda p: p.stat().st_mtime_ns).read_text()) if files else None


def store(ws: Workspace, payload: object) -> str | None:
    """Keep a snapshot, metadata fields only. Returns a message for the GM when the system
    version differs from the previous snapshot's, else None. Raises ValueError on a bad payload."""
    system = payload.get("system") if isinstance(payload, dict) else None
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not (
        isinstance(system, dict)
        and isinstance(system.get("version"), str)
        and VERSION.fullmatch(system["version"])
        and isinstance(entries, list)
        and all(isinstance(e, dict) and isinstance(e.get("uuid"), str) for e in entries)
    ):
        raise ValueError("malformed compendium snapshot")
    snapshot = {
        "system": {k: system.get(k) for k in ("id", "version", "translation")},
        "taken": datetime.now(UTC).isoformat(),
        "entries": [{k: e.get(k) for k in KEYS} for e in entries],
    }
    path = ws.root / DIR / f"{system['version']}.json"
    before = _latest(ws, skip=path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False))
    if before is None or before["system"]["version"] == system["version"]:
        return None
    old = {e["uuid"]: e for e in before["entries"]}
    new = {e["uuid"]: e for e in snapshot["entries"]}
    changed = sum(1 for u in old.keys() & new.keys() if old[u] != new[u])
    return (
        f"System {system.get('id')} version changed from {before['system']['version']} to "
        f"{system['version']}: {len(new.keys() - old.keys())} entries added, "
        f"{len(old.keys() - new.keys())} removed, {changed} changed."
    )


def version(ws: Workspace) -> str | None:
    """The system version of the latest snapshot, None when there is none."""
    snapshot = _latest(ws)
    return snapshot["system"]["version"] if snapshot else None


def lookup(ws: Workspace, query: str, type: str | None, limit: int) -> dict[str, Any] | None:
    """The latest snapshot's entries whose name or slug contains `query`, or whose UUID is it;
    None when there is no snapshot."""
    snapshot = _latest(ws)
    if snapshot is None:
        return None
    needle = query.lower()

    def wanted(e: dict) -> bool:
        kind = e["uuid"].split(".")[-2]  # the document type, as the live search's `type` takes
        return (
            needle in str(e["name"]).lower()
            or needle in str(e["slug"]).lower()
            or e["uuid"] == query
        ) and (not type or type in (e["type"], kind))

    found = [e for e in snapshot["entries"] if wanted(e)][: max(1, min(limit, 100))]
    return {
        "entries": found,
        "offline": True,
        "snapshot": snapshot["system"]["version"],
    }


def cite(ws: Workspace, query: str, type: str | None, limit: int) -> dict[str, Any] | None:
    """`lookup` as cited rule entries (RUL-22, #193 D6a): each carries its UUID and the system
    version and active translation module of the snapshot it came from; the campaign's house
    rules are named in `house_rule_notice`, since a compendium patch is invisible here (RUL-23).
    Offline by design: it reads the snapshot only. None when there is no snapshot."""
    from secondchair.core import rules

    found = lookup(ws, query, type, limit)
    snapshot = _latest(ws)
    if found is None or snapshot is None:
        return None
    system = snapshot["system"]
    names = [str(r["name"]) for r in rules.house_rules(ws)]
    return {
        "entries": [
            {
                **{k: e[k] for k in ("uuid", "name", "type", "pack", "publication")},
                "system_version": system["version"],
                "translation": system["translation"],
            }
            for e in found["entries"]
        ],
        "system_version": system["version"],
        "translation": system["translation"],
        "house_rule_notice": (
            f"This campaign records house rules ({', '.join(names)}); the installed entry may "
            "not describe how it is played here. Ask the GM before quoting it as the ruling."
            if names
            else None
        ),
    }
