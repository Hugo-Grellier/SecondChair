"""The situation card (#188 D1, ARC-14): a deterministic, GM-only read of where play stands.

The GM pulls it on the Director's Desk. The Core assembles it from what it holds, with no
model: the scene, who is acting, the NPCs present with what the party knows of what they know
and what they must not let slip, the matching lines of the session's handoff, and the open calls
about them. It is a read: no delegated action, no call, no job. It carries `as_of`, where play
stood when pulled, and is withdrawn once play moves on, as the acting cue is (ADR 0020 item 3).
"""

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from secondchair.core import calls, delegation, index, knowledge, observations, prep
from secondchair.core.index import PARTY
from secondchair.core.workspace import STATE_DIR, Workspace

CARD_FILE = f"{STATE_DIR}/situation.json"  # the last card pulled, derived state


def situation(ws: Workspace) -> dict[str, Any]:
    """The situation card for where play stands now."""
    as_of: dict[str, Any] = observations.position(ws) | {"at": datetime.now(UTC).isoformat()}
    session = list(reversed(observations.of_session(ws, as_of["session"])))  # latest first
    here = [o for o in session if as_of["scene"] is None or o["scene"] == as_of["scene"]]

    def said(o: dict, field: str) -> str | None:  # a payload field, when the client sent text
        return value if isinstance(value := o["payload"].get(field), str) else None

    scene = next((said(o, "name") for o in session if o["kind"] == "scene"), None)
    acting = None
    if as_of["round"] is not None:  # in combat: the combatant whose turn it is
        combat = next((o for o in session if o["kind"] == "combat"), None)
        acting = combat and said(combat, "combatant")
    # Present: an NPC whose name a combatant or a chat speaker of this scene carries.
    # ponytail: matched by name, as Foundry shows it; by actor UUID once canon links actors.
    names = {said(o, "combatant") for o in here if o["kind"] == "combat"}
    names |= {said(o, "speaker") for o in here if o["kind"] == "chat"}
    party = knowledge.known(ws, PARTY)
    npcs = [
        _npc(ws, e, party)
        for e in index.search_entities(ws)
        if e["kind"] in ("npc", None) and names & {*e["names"], *e["aliases"]}
    ]
    return {
        "as_of": as_of,
        "scene": scene,
        "acting": acting,
        "npcs": npcs,
        "handoff": _handoff(ws, [scene, *(n["name"] for n in npcs)]),
        "calls": _calls_about(ws, {n["id"] for n in npcs}),
    }


def pull(ws: Workspace) -> dict[str, Any]:
    """Assemble the card and keep it as the one the Desk shows until play moves on."""
    card = situation(ws)
    written = ws.root / f"{CARD_FILE}.{secrets.token_hex(4)}"  # never read half written
    written.write_text(json.dumps(card, ensure_ascii=False))
    written.replace(ws.root / CARD_FILE)
    return card


def current(ws: Workspace) -> dict[str, Any] | None:
    """The card last pulled while play has not moved on from its `as_of`; None otherwise, or
    when its derived file is unreadable."""
    try:
        card = json.loads((ws.root / CARD_FILE).read_text())
    except OSError, ValueError:
        return None
    if not isinstance(card, dict) or not observations.still(ws, card.get("as_of")):
        return None
    return card


def _npc(ws: Workspace, entity: dict, party: dict[str, dict]) -> dict[str, Any]:
    """What the NPC holds, split by whether the party holds it too."""
    held = knowledge.known(ws, entity["id"])
    shared, secret = [], []
    for fact, h in sorted(held.items(), key=lambda i: i[1]["statement"]):
        (shared if fact in party else secret).append(
            {"id": fact, "statement": h["statement"], "mode": h["mode"]}
        )
    return {"id": entity["id"], "name": entity["names"][0], "shared": shared, "secret": secret}


def _handoff(ws: Workspace, names: list[str | None]) -> list[str]:
    """The lines of this session's handoff (the next one's outside a session) naming the scene
    or an NPC present."""
    session = delegation.current_session(ws) or delegation.last_session(ws) + 1
    path = ws.root / prep.PREP_DIR / f"session-{session}/handoff.md"
    try:
        text = path.read_text()
    except OSError:
        return []
    wanted = [n for n in names if n]
    return [
        line.strip().lstrip("-*# ").strip()
        for line in text.splitlines()
        if any(knowledge.mentions(line, n) for n in wanted)
    ]


def _calls_about(ws: Workspace, npcs: set[str]) -> list[dict[str, Any]]:
    """The open calls whose acting entity is an NPC present, as DEL-16 finds it."""
    if not npcs:
        return []
    found = []
    for call in calls.read_calls(ws):
        if call["status"] != "open":
            continue
        entry = delegation.read_entry(ws, call["entry"]) if call["entry"] is not None else None
        if entry is not None:
            entity = entry.get("entity")
        else:
            entity = calls._job(ws, call["job"]).get("entity") if call["job"] else None
        if entity in npcs:
            text = call["message"] or (f"{entry['tool']} on {entry['target']}" if entry else "")
            shown = {"id": call["id"], "kind": call["kind"], "deadline": call["deadline"]}
            found.append(shown | {"text": text})
    return found
