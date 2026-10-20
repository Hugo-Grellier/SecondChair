"""The Foundry connector's tools (ARC-07, ARC-10), registered with the Core (ARC-03).

Generic VTT actions each describe one operation the `secondchair-foundry` module takes in the GM's
client (docs/contracts/foundry-bridge.md); the Core logs it and has the bridge send it (ARC-04).
A prepared scene is a desired state in the workspace, realised by the bridge.
"""

import hashlib
import json
import re
from typing import Any, Literal, TypedDict

import yaml

from secondchair.core import index, vtt
from secondchair.core.tools import Change, Tool, VttAction
from secondchair.core.workspace import STATE_DIR, Workspace

DOOR_STATES = {"closed": 0, "open": 1, "locked": 2}  # Foundry's wall door states (`ds`)
SCENES_DIR = "scenes"  # the desired scenes, one YAML file per scene key
REPORTS_DIR = f"{STATE_DIR}/scenes"  # each scene's last reconciliation report (derived)
ITEM_TYPES = ("Token", "Wall", "AmbientLight", "AmbientSound", "Note", "Tile", "Drawing", "Region")
KEY = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

type Choice = Literal["keep", "overwrite", "recreate"]


def digest(text: str) -> str:
    """Which version of a desired scene file a report is about."""
    return hashlib.sha256(text.encode()).hexdigest()


def move_token(token: str, x: int, y: int) -> VttAction:
    """Move a token on its scene. `token` is its Foundry UUID (Scene.<id>.Token.<id>); `x` and
    `y` are the pixel position of its top-left corner."""
    return VttAction(op="move_token", target=token, params={"x": x, "y": y})


def set_door(door: str, state: Literal["closed", "open", "locked"]) -> VttAction:
    """Open, close or lock a door. `door` is its wall's Foundry UUID (Scene.<id>.Wall.<id>)."""
    return VttAction(op="set_door", target=door, params={"ds": DOOR_STATES[state]})


def reveal_token(token: str, cites: list[str]) -> VttAction:
    """Reveal a hidden token to the players, a disclosure. `token` is its Foundry UUID
    (Scene.<id>.Token.<id>); `cites` the ids of the facts the players learn by seeing it, which
    become known by the party. Irreversible: held for the GM's approval unless the GM lifted the
    hold."""
    return VttAction(op="reveal_token", target=token, params={"hidden": False}, cites=cites)


def publish_journal(journal: str, cites: list[str]) -> VttAction:
    """Publish a journal entry to the players (observer for everyone), a disclosure. `journal`
    is its Foundry UUID (JournalEntry.<id>); `cites` the ids of the facts it tells, which
    become known by the party. Irreversible: held for the GM's approval unless the GM lifted the
    hold."""
    return VttAction(
        op="publish_journal", target=journal, params={"ownership.default": 2}, cites=cites
    )


def speak(
    token: str, line: str, cites: list[str] | None = None, entity: str | None = None
) -> VttAction:
    """A creature says `line` aloud to the whole table, in character: a public chat message
    spoken by its token (its Foundry UUID), a disclosure, so its own action, apart from any
    strike it goes with (DEL-23). `cites` the ids of the facts the players learn from it, which
    become known by the party; `entity` the speaker's canon entity id, if it has one.
    Irreversible: held for the GM's approval unless the GM lifted the hold."""
    return VttAction(
        op="speak", target=token, params={"content": line}, cites=cites or None, entity=entity
    )


def prepare_scene(
    key: str,
    scene: dict[str, Any],
    items: list[dict[str, Any]],
    choices: dict[str, Choice] | None = None,
) -> Change:
    """Write a scene's desired state: what the scene must look like in Foundry after prep. The
    GM's client realises it by reconciliation as soon as one is connected, keeping what was
    played and what the GM retouched; `scene_report` says how it went.

    `key` names the scene in the campaign (lowercase words joined by dashes). `scene` holds the
    Scene's Foundry fields, `name` required (for example `width`, `height`, `grid`,
    `background`). `items` are the objects placed on it, each `{key, type, data}`: a key stable
    across preparations, a type among Token, Wall, AmbientLight, AmbientSound, Note, Tile,
    Drawing and Region, and the document's Foundry fields; a Token also takes `actor`, the UUID of
    the Actor (world or compendium) it is made from. `choices` are the GM's calls by object key
    (`_scene` for the scene itself): `keep` the VTT's version of a conflict, `overwrite` it, or
    `recreate` an object deleted in play. Writing the same state again changes nothing."""
    desired: dict[str, Any] = {"scene": scene, "items": items}
    if choices:
        desired["choices"] = choices
    _check(key, desired)
    text = yaml.safe_dump(desired, sort_keys=False, allow_unicode=True)
    return Change(path=f"{SCENES_DIR}/{key}.yaml", after=text)


def _check(key: str, desired: dict[str, Any]) -> None:
    """Refuse what the module could not realise (foundry-bridge.schema.json, desired_scene)."""
    if not KEY.match(key):
        raise ValueError(f"Scene key {key!r}: use lowercase words joined by dashes.")
    if not isinstance(desired["scene"].get("name"), str) or not desired["scene"]["name"]:
        raise ValueError("The scene needs a `name`.")
    seen: set[str] = set()
    for item in desired["items"]:
        k = item.get("key")
        if not isinstance(k, str) or not KEY.match(k) or k in seen:
            raise ValueError(f"Item key {k!r}: give each item its own key, lowercase and dashes.")
        seen.add(k)
        if item.get("type") not in ITEM_TYPES:
            raise ValueError(
                f"{k}: type {item.get('type')!r} is not one of {', '.join(ITEM_TYPES)}."
            )
        if not isinstance(item.get("data"), dict):
            raise ValueError(f"{k}: `data` must hold the document's fields.")
        if set(item) - {"key", "type", "actor", "data"}:
            raise ValueError(f"{k}: an item has only key, type, actor and data.")
        if "actor" in item and (item["type"] != "Token" or not isinstance(item["actor"], str)):
            raise ValueError(f"{k}: only a Token takes an `actor`, an Actor's UUID.")


class OfficialName(TypedDict):
    name: str | None
    official_reference: dict[str, str | None]


def official_name(key: str, pack: str | None = None) -> OfficialName:
    """The name official game content (a creature, a spell, an item) has in the GM's own install,
    in the campaign language, to offer as a new entity's name (CAN-20), with the official
    reference to store on it. `key` is the System extension's stable English key (PF2e: the
    item's or actor's slug, else its English name); `pack` the compendium pack, needed only when
    the key is in several. `name` is null when the entry has no translation: then propose a name
    or ask the GM, never translate an official name yourself (CAN-21)."""
    found = vtt.read("official_name", {"key": key, "pack": pack})
    try:
        reference = index.official_reference({"key": found["key"], "pack": found["pack"]})
        name = found["name"]
        if name is not None and not (isinstance(name, str) and name.strip()):
            raise TypeError
    except (KeyError, TypeError, index.CanonError) as e:
        raise vtt.VttError(f"The GM client sent a malformed official name: {found}") from e
    return {"name": name, "official_reference": reference}


def tools(ws: Workspace) -> list[Tool]:
    def scene_report(key: str) -> dict[str, Any]:
        """How a prepared scene was last realised in Foundry: `realised`, then `pending` (the
        desired state changed since and waits for a GM client), and the GM client's `report`
        (what each object became, conflicts waiting for the GM's choice, errors) or `error`."""
        desired = ws.root / SCENES_DIR / f"{key}.yaml"
        if not KEY.match(key) or not desired.is_file():
            raise ValueError(f"No prepared scene {key!r}.")
        path = ws.root / REPORTS_DIR / f"{key}.json"
        if not path.is_file():
            return {
                "realised": False,
                "message": "Not realised yet: it waits for a GM client to connect.",
            }
        record = json.loads(path.read_text())
        pending = record.pop("desired") != digest(desired.read_text())
        return {"realised": True, "pending": pending, **record}

    return [
        Tool(
            fn=move_token, responsibility="vtt_operations", delegated_action=True, reversible=True
        ),
        Tool(fn=set_door, responsibility="vtt_operations", delegated_action=True, reversible=True),
        Tool(fn=reveal_token, responsibility="disclosure", delegated_action=True, reversible=False),
        Tool(
            fn=publish_journal, responsibility="disclosure", delegated_action=True, reversible=False
        ),
        Tool(fn=speak, responsibility="disclosure", delegated_action=True, reversible=False),
        Tool(fn=prepare_scene, responsibility="prep", delegated_action=True, reversible=True),
        Tool(fn=scene_report, responsibility="prep", delegated_action=False, reversible=True),
        # ponytail: a read sits under memory (canon and continuity), as the Core's own reads.
        Tool(fn=official_name, responsibility="memory", delegated_action=False, reversible=True),
    ]
