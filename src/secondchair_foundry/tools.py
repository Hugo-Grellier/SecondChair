"""The Foundry connector's tools (ARC-07, ARC-10), registered with the Core (ARC-03).

Generic VTT actions each describe one operation the `secondchair-foundry` module takes in the GM's
client (docs/contracts/foundry-bridge.md); the Core logs it and has the bridge send it (ARC-04).
A prepared scene or world document is a desired state in the workspace, realised by the bridge.
"""

import hashlib
import json
import posixpath
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal, TypedDict
from urllib.parse import unquote

import yaml

from secondchair.core import index, machine, vtt
from secondchair.core.tools import Block, Change, Tool, VttAction
from secondchair.core.workspace import STATE_DIR, Workspace
from secondchair_foundry import compendium

DOOR_STATES = {"closed": 0, "open": 1, "locked": 2}  # Foundry's wall door states (`ds`)
SCENES_DIR = "scenes"  # the desired scenes, one YAML file per scene key
REPORTS_DIR = f"{STATE_DIR}/scenes"  # each scene's last reconciliation report (derived)
DOCUMENTS_DIR = "documents"  # the desired world documents, one YAML file per document key
DOCUMENT_REPORTS_DIR = f"{STATE_DIR}/documents"  # each document's last report (derived)
PRODUCTION_DIR = "prep/production"  # a scene's asset manifest: prep, not canon (#179)
DOCUMENT_TYPES = ("JournalEntry", "Actor", "Item", "Playlist", "RollTable")
EMBEDDED = ("pages", "sounds", "items", "results")  # embedded documents, each replaced whole
# A world or compendium document's UUID, its type captured: Actor.<id>, Compendium.<pack>.Actor.<id>
UUID = re.compile(r"^(?:Compendium\.[\w-]+\.[\w-]+\.)?(\w+)\.[A-Za-z0-9]+$")
ITEM_TYPES = ("Token", "Wall", "AmbientLight", "AmbientSound", "Note", "Tile", "Drawing", "Region")
MODULE = "secondchair-foundry"  # the only flags namespace prep may write on a placed object
# The Region behaviour types prep may place: any other (executeScript, executeMacro, a module's,
# toggleBehavior, which enables any behaviour by UUID) could run code in every client.
BEHAVIORS = (
    "adjustDarknessLevel",
    "displayScrollingText",
    "pauseGame",
    "suppressWeather",
    "modifyMovementCost",
    "teleportToken",
)
# The module's identity flags, which only reconciliation writes: prep may not forge them.
RESERVED = ("scene", "document", "created", "spec", "shape", "local", "source", "base", "key")
# A Scene's embedded collections: what a scene places only arrives as an item.
SCENE_EMBEDDED = (
    *("drawings", "levels", "lights", "notes", "regions", "sounds", "templates", "tiles"),
    *("tokens", "walls"),
)
KEY = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PREPARED = re.compile(r"^@prepared:([^/]+)(?:/(.+))?$")
FILE_FIELDS = ("src", "path", "img")  # the fields of a desired state that name a file
IMAGE_TYPES = (".webp", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".avif", ".webm", ".mp4", ".m4v")

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


def whisper(user: str, line: str, cites: list[str] | None = None) -> VttAction:
    """Whisper `line` to one player: a chat message only that user sees, a disclosure. `user` is
    the player's Foundry UUID (User.<id>); `cites` the ids of the facts it tells. One player is
    not the party: the facts are not marked known by the party, the wrap asks the GM who learned
    them (CAP-08). Irreversible: held for the GM's approval unless the GM lifted the hold."""
    return VttAction(
        op="whisper", target=user, params={"content": line}, cites=cites or None, whisper=True
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
    `background`: `{src}`, the map, found with `browse_files`, its size read with `image_size`;
    the module writes it where the Foundry version keeps it). `items` are the objects placed on
    it, each `{key, type, data}`: a key stable across preparations, a type among Token, Wall,
    AmbientLight, AmbientSound, Note, Tile, Drawing and Region, and the document's Foundry
    fields; a Token also takes `actor`, the UUID of the Actor (world or compendium) it is made
    from. `choices` are the GM's calls by object key
    (`_scene` for the scene itself): `keep` the VTT's version of a conflict, `overwrite` it, or
    `recreate` an object deleted in play. Never set `ownership`, an update operator (`-=`, `==`),
    another module's `flags` or the module's own identity flags, nor a Token's `delta`; a
    Region's `behaviors` are of the types adjustDarknessLevel, displayScrollingText, pauseGame,
    suppressWeather, modifyMovementCost, teleportToken only; HTML is sanitized. Writing the same
    state again changes nothing."""
    desired: dict[str, Any] = {"scene": scene, "items": items}
    if choices:
        desired["choices"] = choices
    _check(key, desired)
    text = yaml.safe_dump(desired, sort_keys=False, allow_unicode=True)
    return Change(path=f"{SCENES_DIR}/{key}.yaml", after=text)


ASSET_KINDS = ("map", "portrait", "token", "music", "ambience", "handout")
SOURCES = ("install", "user-file", "provider")
CONSENTS = ("local", "model")  # model: the asset may be sent to a third-party provider
STATUSES = ("wanted", "found", "approved")
PROVENANCE = ("prompt", "version", "seed", "terms")  # the provider is the entry's own


def validate_manifest(manifest: Any) -> None:
    """Refuse a production manifest the pipeline could not use (pure; #179, docs/contracts/
    workspace-layout.md `prep/production/`). Policy that needs the machine is `_refuse_policy`."""
    if not isinstance(manifest, dict) or set(manifest) - {"map", "packs", "entries"}:
        raise ValueError("A manifest has only map, packs and entries.")
    if not isinstance(manifest.get("map", {}), dict):
        raise ValueError("`map` is the map spec: scale, grid, levels.")
    packs = manifest.get("packs", {})
    if not isinstance(packs, dict):
        raise ValueError("`packs` maps a pack key to its licence record.")
    for name, pack in packs.items():
        if not KEY.match(str(name)) or not isinstance(pack, dict) or not pack.get("licence"):
            raise ValueError(f"Pack {name!r}: a key and a `licence` record are required.")
        if set(pack) - {"licence", "path"}:
            raise ValueError(f"Pack {name!r}: a pack has only licence and path.")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("`entries` is the list of wanted assets.")
    seen: set[str] = set()
    for e in entries:
        k = e.get("key") if isinstance(e, dict) else None
        if not isinstance(k, str) or not KEY.match(k) or k in seen:
            raise ValueError(f"Entry key {k!r}: give each entry its own key, lowercase and dashes.")
        seen.add(k)
        if set(e) - {
            *("key", "kind", "need", "source", "path", "pack", "licence", "consent"),
            *("status", "provider", "provenance"),
        }:
            raise ValueError(f"{k}: unknown field.")
        for field, allowed in (
            ("kind", ASSET_KINDS), ("source", SOURCES), ("consent", CONSENTS), ("status", STATUSES)
        ):  # fmt: skip
            if e.get(field) not in allowed:
                raise ValueError(f"{k}: `{field}` is one of {', '.join(allowed)}.")
        if not isinstance(e.get("need"), str) or not e["need"]:
            raise ValueError(f"{k}: say what is `need`ed.")
        if e.get("pack") is not None and e["pack"] not in packs:
            raise ValueError(f"{k}: pack {e['pack']!r} has no licence record in `packs`.")
        if not (e.get("licence") or (e.get("pack") and packs[e["pack"]]["licence"])):
            raise ValueError(f"{k}: no licence: give `licence` or a `pack` with a record.")
        if e["status"] != "wanted" and not isinstance(e.get("path"), str):
            raise ValueError(f"{k}: a {e['status']} asset needs its `path`.")
        if "path" in e:
            _data_path(str(e["path"]))
        if (e["source"] == "provider" or e["consent"] == "model") and not e.get("provider"):
            raise ValueError(f"{k}: name the `provider`.")
        prov = e.get("provenance")
        if e["source"] == "provider" and e["status"] != "wanted":
            if not isinstance(prov, dict) or any(f not in prov for f in PROVENANCE):
                raise ValueError(f"{k}: a generated asset needs `provenance`: {PROVENANCE}.")
        elif prov is not None:
            raise ValueError(f"{k}: only a generated asset has `provenance`.")


def _in_purchased(path: str, roots: list[Path]) -> bool:
    """Whether a Foundry data path (`modules/<id>/...`) lies in a purchased directory, by the
    trailing components of the configured root (`.../Data/modules/<id>`)."""
    parts = unquote(path).split("/")
    return any(
        parts[:k] == list(r.parts[-k:])
        for r in roots
        for k in range(2, min(len(r.parts), len(parts)) + 1)
    )


def _refuse_policy(manifest: dict[str, Any], purchased: list[Path], providers: list[str]) -> None:
    """Decisions 19 and 20 (#179): purchased module assets are referenced, never copied;
    nothing goes to a third-party model unless the GM switched that provider on."""
    for e in manifest["entries"]:
        if e.get("path") and e["source"] != "install" and _in_purchased(e["path"], purchased):
            raise ValueError(
                f"{e['key']}: {e['path']} is purchased content: reference it with `source: "
                "install`, never as another source (LIC-12)."
            )
        if e["consent"] == "model" and e["provider"] not in providers:
            raise ValueError(
                f"{e['key']}: sending to {e['provider']!r} is off. The GM adds it to "
                "`model_providers` in the machine configuration (LIC-12, LIC-16)."
            )


def write_production_manifest(
    key: str,
    entries: list[dict[str, Any]],
    packs: dict[str, dict[str, str]] | None = None,
    map_spec: dict[str, Any] | None = None,
) -> Change:
    """Write a scene's production manifest, `prep/production/<key>.yaml`: the assets the scene
    needs and where each stands. It is prep, not canon; `asset_check` reads it.

    `entries` are `{key, kind, need, source, consent, status, path?, pack?, licence?, provider?,
    provenance?}`. `kind` is map, portrait, token, music, ambience or handout; `need` says what
    is wanted. `source` is `install` (a Foundry module's or system's file), `user-file` (the
    GM's own) or `provider` (generated). `status` is `wanted` (the GM must supply it), `found`
    or `approved`; these two need `path`, relative to Foundry's data. `licence` is the asset's
    own; without it the entry takes its `pack`'s record. `packs` maps a pack key to
    `{licence, path?}`. `consent` is `local` (nothing leaves the machine) or `model` (it may go
    to a third-party model: the entry names its `provider`, and the GM must have switched that
    provider on). A generated, found asset records `provenance`: `prompt`, `version`, `seed`,
    `terms`. A purchased module's files are referenced with `source: install`, never copied.
    `map_spec` is `{scale, grid, levels}`."""
    manifest: dict[str, Any] = {}
    if map_spec:
        manifest["map"] = map_spec
    if packs:
        manifest["packs"] = packs
    manifest["entries"] = entries
    if not KEY.match(key):
        raise ValueError(f"Scene key {key!r}: use lowercase words joined by dashes.")
    validate_manifest(manifest)
    _refuse_policy(manifest, [p for p, _ in machine.purchased_content()], machine.model_providers())
    text = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    return Change(path=f"{PRODUCTION_DIR}/{key}.yaml", after=text)


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
    if _sets_ownership([desired["scene"], *(i["data"] for i in desired["items"])]):
        raise ValueError("`ownership` is not prep's: who sees a scene is the GM's call in Foundry.")
    for item in desired["items"]:
        _check_fields(item["key"], item["data"])
        _check_placed(item["key"], item["data"])
        if item["type"] == "Token" and any(
            p[0] in ("delta", "actorData") for p in _paths(item["data"])
        ):
            raise ValueError(f"{item['key']}: no `delta` in prep: a token is its actor's.")
    _check_fields("_scene", desired["scene"])
    if placed := sorted({str(f).split(".")[0] for f in desired["scene"]} & set(SCENE_EMBEDDED)):
        raise ValueError(f"_scene: place {', '.join(placed)} as items, not in the scene.")


def _paths(value: object, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    """Every field path in `value`, dotted keys split as Foundry expands them, a list's entries
    under their index."""
    if isinstance(value, dict):
        for k, v in value.items():
            path = (*prefix, *str(k).split("."))
            yield path
            yield from _paths(v, path)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _paths(v, (*prefix, str(i)))


def _check_fields(what: str, data: dict[str, Any]) -> None:
    """Refuse, at any depth of a document's or a placed object's fields, what only Foundry or
    reconciliation writes: an update operator (`-=`, `==`), flags of another namespace than the
    module's, the module's own identity flags. An embedded document's flags are checked too."""
    for path in _paths(data):
        if operator := next((s for s in path if s.startswith(("-=", "=="))), None):
            raise ValueError(f"{what}: no update operator ({operator}) in prep.")
        at = 2 if len(path) > 2 and path[0] in EMBEDDED else 0
        if len(path) > at + 1 and path[at] == "flags":
            if path[at + 1] != MODULE:
                raise ValueError(f"{what}: flags of {path[at + 1]} are not prep's.")
            if len(path) > at + 2 and path[at + 2] in RESERVED:
                raise ValueError(f"{what}: the module's `{path[at + 2]}` flag is reconciliation's.")


def _check_placed(key: str, data: dict[str, Any]) -> None:
    """Refuse a Region's behaviours unless they are a list of the types prep may place."""
    if any(str(f).startswith("behaviors.") for f in data) or not (
        isinstance(data.get("behaviors", []), list)
        and all(isinstance(b, dict) for b in data.get("behaviors", []))
    ):
        raise ValueError(f"{key}: `behaviors` must be a list of behaviours.")
    for behavior in data.get("behaviors", []):
        if behavior.get("type") not in BEHAVIORS:
            raise ValueError(
                f"{key}: a Region behaviour of type {behavior.get('type')!r} is not prep's; "
                f"prep places {', '.join(BEHAVIORS)}."
            )


def prepare_document(
    key: str,
    type: Literal["JournalEntry", "Actor", "Item", "Playlist", "RollTable"],
    data: dict[str, Any],
    base: str | None = None,
    choice: Choice | None = None,
) -> Change:
    """Write a world document's desired state: a journal, an NPC actor, an item, a playlist or a
    roll table that must exist in Foundry after prep. The GM's client realises it by
    reconciliation as soon as one is connected, keeping what the GM retouched; `document_report`
    says how it went. Documents are realised before scenes, so a scene can use them.

    `key` names the document in the campaign (lowercase words joined by dashes). `type` is its
    Foundry document type, `data` its Foundry fields. `base` is the UUID of a compendium or world
    document to make it from (`Compendium.pf2e.pathfinder-bestiary.Actor.<id>`), `data` set on
    top of it; without `base`, `data` needs a `name`. By type:
    - JournalEntry: `{name, pages: [{name, type: "text", text: {markdown: "..."}}]}`, the
      Markdown shown as sanitized HTML in Foundry. Only the GM sees it: `publish_journal`
      shows it to the players; `data` never sets `ownership`.
    - Actor: `base` a bestiary entry, `data` `{name}` and any field to change (`img`,
      `prototypeToken`, `system`…).
    - Item: `base` an equipment or treasure entry, `data` `{name}` or other changes.
    - Playlist: `{name, mode, sounds: [{name, path, repeat, volume}]}`, `mode` 0 in order,
      1 shuffled, 2 soundboard only; `path` a sound file found with `browse_files`.
    - RollTable: `{name, formula, results: [{type: "text", description, range: [low, high]}]}`.
    The pages, sounds, results, and an actor's `items` when `data` gives them, are replaced as a
    whole when prep changes them. In this document or a prepared scene, a string value
    `@prepared:<key>` stands for that prepared document's Foundry id (a Token's `actor`: its
    UUID), and `@prepared:<playlist key>/<sound name>` for that sound's id (a Scene's
    `playlistSound`). `choice` is the GM's call on a conflict: `keep` the VTT's version,
    `overwrite` it, or `recreate` a document deleted in Foundry. Never set `ownership`, an update
    operator (`-=`, `==`), another module's `flags` or the module's own identity flags. Writing
    the same state again changes nothing."""
    desired: dict[str, Any] = {"type": type}
    if base is not None:
        desired["base"] = base
    desired["data"] = data
    if choice is not None:
        desired["choice"] = choice
    _check_document(key, desired)
    text = yaml.safe_dump(desired, sort_keys=False, allow_unicode=True)
    return Change(path=f"{DOCUMENTS_DIR}/{key}.yaml", after=text)


def _check_document(key: str, desired: dict[str, Any]) -> None:
    """Refuse what the module could not realise (foundry-bridge.schema.json, desired_document)."""
    if not KEY.match(key):
        raise ValueError(f"Document key {key!r}: use lowercase words joined by dashes.")
    kind, data, base = desired["type"], desired["data"], desired.get("base")
    if kind not in DOCUMENT_TYPES:
        raise ValueError(f"Type {kind!r} is not one of {', '.join(DOCUMENT_TYPES)}.")
    if not isinstance(data, dict):
        raise ValueError("`data` must hold the document's fields.")
    for k, v in data.items():
        field = str(k).split(".")[0]
        if field in EMBEDDED and (k != field or not isinstance(v, list)):
            raise ValueError(f"`{field}` must be given whole, as a list of its documents.")
    if _sets_ownership(data):
        raise ValueError(
            "`ownership` is not prep's: a prepared document is the GM's only, and only "
            "`publish_journal` shows a journal to the players."
        )
    _check_fields(key, data)
    if base is None and not (isinstance(data.get("name"), str) and data["name"]):
        raise ValueError("Without a `base`, the document needs a `name` in `data`.")
    found = UUID.match(base) if isinstance(base, str) else None
    if base is not None and (not found or found[1] != kind):
        raise ValueError(f"`base` {base!r}: give the UUID of a {kind}, world or compendium.")


def _sets_ownership(value: object) -> bool:
    """Whether a key anywhere in `value` sets who sees a document, however Foundry spells it:
    `ownership`, `ownership.default`, `-=ownership`, `==ownership`, `pages.0.ownership`, at any
    depth."""
    if isinstance(value, list):
        return any(_sets_ownership(v) for v in value)
    if not isinstance(value, dict):
        return False
    return any(
        any(s.removeprefix("-=").removeprefix("==") == "ownership" for s in str(k).split("."))
        or _sets_ownership(v)
        for k, v in value.items()
    )


def _data_path(path: str) -> str:
    """`path` if it is relative to Foundry's data: no scheme or URL (`https:`, `data:`, `//`), no
    leading `/`, no `..` segment, no control character, checked as given and percent-decoded
    (Foundry lists paths encoded, `Log%20Fume`): a read never leaves the GM's install."""
    refused = ValueError(f"{path!r} is not a path in Foundry's data: give a relative one.")
    # A malformed or non-UTF-8 percent sequence, which decodeURIComponent refuses too.
    if re.search(r"%(?![0-9A-Fa-f]{2})", path):
        raise refused
    try:
        decoded = unquote(path, errors="strict")
    except UnicodeDecodeError:
        raise refused from None
    for text in (path, decoded):
        if (
            re.match(r"^[a-z][\w+.-]*:", text, re.IGNORECASE)
            or text.lstrip() != text  # the URL parser drops a leading space: " //evil"
            or text.startswith(("/", "\\"))
            or ".." in re.split(r"[/\\]", text)
            or re.search(r"[\x00-\x1f\x7f]", text)
        ):
            raise refused
    return path


def browse_files(
    path: str = "", source: str = "data", extensions: list[str] | None = None
) -> dict[str, Any]:
    """The folders and files in a directory of the GM's Foundry install, to find maps, tokens,
    sounds and music for prep: `{dirs, files}`, paths to use as they are (a scene's
    `background.src`, a playlist sound's `path`). `source` is `data` (the user data: `worlds/`,
    `modules/<id>/…`, `assets/`) or `public` (Foundry's own icons and sounds); `extensions` keeps
    only those files, such as `[".webp", ".jpg", ".png", ".webm"]` for maps or
    `[".ogg", ".mp3"]` for sounds. Long listings are cut short, with `more` saying how many were
    left out."""
    if source not in ("data", "public"):
        raise ValueError(f"Source {source!r}: `data` or `public`.")
    params = {"path": _data_path(path), "source": source, "extensions": extensions}
    return vtt.read("browse_files", params)


def image_size(path: str) -> dict[str, Any]:
    """An image's or video's size in pixels, `{width, height}`, loaded in the GM's client:
    `path` as `browse_files` gives it. Set a scene's `width` and `height` from its map's, and its
    `grid.size` so the map's squares fall on the grid (a map drawn at 140 pixels a square takes
    `grid: {size: 140}`)."""
    if not path:
        raise ValueError("Give the image's path.")
    return vtt.read("image_size", {"path": _data_path(path)})


def list_world_documents(
    type: Literal["Actor", "JournalEntry", "Item", "Playlist", "RollTable", "Scene"],
    query: str = "",
) -> list[dict[str, Any]]:
    """The documents of one type already in the Foundry world, whose name contains `query`
    (any case), each `{uuid, id, name, prepared_key}`: `prepared_key` the key of the prepared
    document or scene it realises, null when the GM made it. At most 100."""
    return vtt.read("list_world_documents", {"type": type, "query": query})


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


def _strings(value: object, where: str = "") -> Iterator[tuple[str, str, str]]:
    """Every string in `value` as (location, field name, value)."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, f"{where}.{k}" if where else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _strings(v, f"{where}.{i}")
    elif isinstance(value, str):
        yield where, where.rsplit(".", 1)[-1], value


class _Offline(Exception):
    """The GM client cannot answer: every read still to do is skipped, none is retried."""


def check_assets(ws: Workspace, key: str) -> dict[str, Any]:
    """Whether a prepared scene, and the prepared documents it refers to, could be realised with
    what the GM's Foundry holds. Reads only; fixes nothing. `passed` is true when nothing is
    `missing`, `mismatched` or `skipped`."""
    path = ws.root / SCENES_DIR / f"{key}.yaml"
    if not KEY.match(key) or not path.is_file():
        raise ValueError(f"No prepared scene {key!r}.")
    report: dict[str, list[dict[str, str]]] = {
        "missing": [],
        "mismatched": [],
        "ok": [],
        "skipped": [],
        "wanted": [],  # production the GM still has to supply: the scene itself is not broken
    }

    def add(bucket: str, where: str, check: str, value: str, detail: str = "") -> None:
        report[bucket].append({"where": where, "check": check, "value": value, "detail": detail})

    try:
        desired = yaml.safe_load(path.read_text())
        _check(key, desired)
    except (ValueError, yaml.YAMLError, KeyError, TypeError, AttributeError) as e:
        add("mismatched", f"{SCENES_DIR}/{key}.yaml", "schema", key, str(e))
        return {"scene": key, "passed": False, **report}

    sizes: dict[str, dict[str, Any] | None] = {}  # image path -> size, None when unreadable
    listings: dict[str, list[str] | None] = {}

    def read(op: str, params: dict[str, Any]) -> Any:
        try:
            return vtt.read(op, params)
        except vtt.Unanswered as e:
            raise _Offline from e
        except vtt.VttError as e:
            if str(e) == vtt.NO_VTT:
                raise _Offline from e
            raise

    def size(value: str) -> dict[str, Any] | None:
        if value not in sizes:
            try:
                sizes[value] = read("image_size", {"path": _data_path(value)})
            except (ValueError, vtt.VttError) as e:
                sizes[value] = {"error": str(e)}
        return sizes[value]

    def listing(folder: str) -> list[str] | None:
        if folder not in listings:
            listings[folder] = None
            found: list[str] = []
            for source in ("data", "public"):
                try:
                    r = read("browse_files", {"path": folder, "source": source, "extensions": None})
                except vtt.VttError as e:
                    if isinstance(e, vtt.Unanswered) or str(e) == vtt.NO_VTT:
                        raise _Offline from e
                    continue
                if r.get("more"):
                    return None  # a long folder is cut short: a file may be hiding past the cut
                found += [unquote(f) for f in r.get("files", [])]
            listings[folder] = found
        return listings[folder]

    def check_file(where: str, value: str) -> None:
        try:
            _data_path(value)
        except ValueError as e:
            return add("mismatched", where, "file", value, str(e))
        if value.lower().endswith(IMAGE_TYPES):
            got = size(value)
            if got is None or "error" in got:
                detail = str((got or {}).get("error", ""))
                return add("missing", where, "file", value, detail)
            return add("ok", where, "file", value, f"{got['width']}x{got['height']}")
        files = listing(posixpath.dirname(unquote(value)))
        if files is None:
            return add("skipped", where, "file", value, "its folder is too long to list")
        add("ok" if unquote(value) in files else "missing", where, "file", value)

    def check_actor(where: str, value: str) -> None:
        if value.startswith("@prepared:"):
            return  # a reference: checked below, whatever the field
        if not UUID.match(value):
            return add("mismatched", where, "actor", value, "not an Actor UUID")
        try:
            found = read("resolve_uuid", {"uuid": value})
        except vtt.VttError as e:
            return add("skipped", where, "actor", value, str(e))
        if found is None:
            add("missing", where, "actor", value)
        elif found.get("type") != "Actor":
            add("mismatched", where, "actor", value, f"is a {found.get('type')}")
        else:
            add("ok", where, "actor", value, found.get("name", ""))

    def check_prepared(where: str, value: str, wanted: str | None) -> dict[str, Any] | None:
        match = PREPARED.match(value)
        assert match
        name, sound = match.groups()
        doc = ws.root / DOCUMENTS_DIR / f"{name}.yaml"
        data = yaml.safe_load(doc.read_text()) if KEY.match(name) and doc.is_file() else None
        if not isinstance(data, dict):
            add("missing", where, "prepared", value, f"no {DOCUMENTS_DIR}/{name}.yaml")
        elif wanted and data.get("type") != wanted:
            add("mismatched", where, "prepared", value, f"is a {data.get('type')}")
        elif sound and sound not in [s.get("name") for s in data["data"].get("sounds", [])]:
            add("missing", where, "prepared", value, f"no sound {sound!r}")
        else:
            add("ok", where, "prepared", value)
            return data
        return None

    scene = desired["scene"]
    # The scene's own file first, then each prepared document it names, once.
    todo: list[tuple[str, object]] = [(f"{SCENES_DIR}/{key}.yaml", desired)]
    seen: set[str] = set()
    try:
        while todo:
            file, content = todo.pop(0)
            for loc, field, value in _strings(content):
                where = f"{file}: {loc}"
                if field in FILE_FIELDS and value and not value.startswith("@prepared:"):
                    check_file(where, value)
                elif field == "actor" and file.startswith(SCENES_DIR):
                    check_actor(where, value)
                if value.startswith("@prepared:"):
                    wanted = "Actor" if field == "actor" else None
                    doc = check_prepared(where, value, wanted)
                    name = value.removeprefix("@prepared:").split("/")[0]
                    if doc is not None and name not in seen:
                        seen.add(name)
                        todo.append((f"{DOCUMENTS_DIR}/{name}.yaml", doc))
        background = (scene.get("background") or {}).get("src")
        grid = (
            (scene.get("grid") or {}).get("size") if isinstance(scene.get("grid"), dict) else None
        )
        if isinstance(background, str) and isinstance(grid, int) and grid > 0:
            got = size(background)
            where = f"{SCENES_DIR}/{key}.yaml: scene.grid.size"
            if got and "error" not in got:
                w, h = got["width"], got["height"]
                fits = w % grid == 0 and h % grid == 0
                add("ok" if fits else "mismatched", where, "grid", str(grid), f"map {w}x{h}")
        manifest_file = ws.root / PRODUCTION_DIR / f"{key}.yaml"
        if manifest_file.is_file():
            where = f"{PRODUCTION_DIR}/{key}.yaml"
            try:
                manifest = yaml.safe_load(manifest_file.read_text())
                validate_manifest(manifest)
            except (ValueError, yaml.YAMLError, AttributeError, TypeError) as e:
                add("mismatched", where, "schema", key, str(e))
            else:
                for entry in manifest["entries"]:
                    here = f"{where}: {entry['key']}"
                    if entry["status"] == "wanted":
                        add("wanted", here, "production", entry["need"], entry["source"])
                    else:
                        check_file(here, entry["path"])
    except _Offline:
        add("skipped", f"{SCENES_DIR}/{key}.yaml", "foundry", key, vtt.NO_VTT)
    passed = not (report["missing"] or report["mismatched"] or report["skipped"])
    return {"scene": key, "passed": passed, **report}


def tools(ws: Workspace) -> list[Tool]:
    def report(folder: str, reports: str, what: str, key: str) -> dict[str, Any]:
        desired = ws.root / folder / f"{key}.yaml"
        if not KEY.match(key) or not desired.is_file():
            raise ValueError(f"No prepared {what} {key!r}.")
        path = ws.root / reports / f"{key}.json"
        if not path.is_file():
            return {
                "realised": False,
                "message": "Not realised yet: it waits for a GM client to connect.",
            }
        record = json.loads(path.read_text())
        pending = record.pop("desired") != digest(desired.read_text())
        return {"realised": True, "pending": pending, **record}

    def scene_report(key: str) -> dict[str, Any]:
        """How a prepared scene was last realised in Foundry: `realised`, then `pending` (the
        desired state changed since and waits for a GM client), and the GM client's `report`
        (what each object became, conflicts waiting for the GM's choice, errors) or `error`.
        `production` says how far the scene is, in three separate states: `structurally_valid`
        (the desired state passes `asset_check`), `realised` (the last reconciliation is current
        and clean: no error, no conflict) and `smoke_tested` (a player-view preview ran in
        Foundry; false until that exists). Each is false until proven."""
        result = report(SCENES_DIR, REPORTS_DIR, "scene", key)
        actions = result.get("report", {}).get("actions", [])
        clean = (
            (
                result.get("ok") is True
                and not result["pending"]
                and not result["report"].get("errors")
                and not any(a.get("action") == "conflict" for a in actions)
            )
            if result["realised"] and "report" in result
            else False
        )
        production = {
            "structurally_valid": check_assets(ws, key)["passed"],
            "realised": clean,
            "smoke_tested": False,
        }
        return {**result, "production": production}

    def asset_check(key: str) -> dict[str, Any]:
        """Before realising, whether the files, sizes, grid, actors and `@prepared:` references
        of a prepared scene (and of the prepared documents it names) exist in the GM's Foundry.
        Reads only, fixes nothing. `missing`, `mismatched` and `ok` list each check as
        `{where, check, value, detail}`; `skipped` the checks that could not run, such as every
        Foundry read when no GM client is connected. `passed` is true when the first, second and
        last are empty. The scene's production manifest, when written, is read too: a `found` or
        `approved` asset must resolve like a scene file; a `wanted` one is listed under `wanted`,
        production the GM must supply, which does not fail `passed`."""
        return check_assets(ws, key)

    def search_compendium(query: str, type: str | None = None, limit: int = 20) -> dict[str, Any]:
        """The compendium entries of the GM's install whose name contains `query` (any case), as
        `{entries, offline, snapshot}`. Each entry is `{uuid, name, type, pack, img, level, rarity,
        traits}`: the UUID to make a prepared document or a token from, and pf2e's level, rarity
        and traits (null elsewhere) to calibrate encounters. `type` keeps one document type
        (Actor, Item, JournalEntry, Scene, Playlist, RollTable…) or one system type (pf2e: npc,
        hazard, loot, weapon, equipment…). At most `limit` entries (up to 100). `offline` is true
        when no GM client is connected and the metadata snapshot taken at the last connection
        answered: entries then also carry `slug`, `publication` and `remaster`, match on slug or
        exact UUID as well, and may be out of date; no snapshot, no answer. `snapshot` is the
        game system version of the snapshot (null if none was taken)."""
        try:
            entries = vtt.read("search_compendium", {"query": query, "type": type, "limit": limit})
        except vtt.VttError as e:
            # Both "no GM client" messages (the bridge's and the Core's) start alike.
            if not str(e).startswith("No GM client") or not (
                offline := compendium.lookup(ws, query, type, limit)
            ):
                raise
            return offline
        return {"entries": entries, "offline": False, "snapshot": compendium.version(ws)}

    def lookup_rule(query: str, type: str | None = None, limit: int = 10) -> dict[str, Any]:
        """A cited rule lookup, offline: the entries of the metadata snapshot taken at the last
        Foundry connection whose name or slug contains `query` (or whose UUID it is), whether or
        not a GM client is connected. Each entry is `{uuid, name, type, pack, publication,
        system_version, translation}`: cite the UUID and the system version. The snapshot holds
        no rule text, so never present an entry as the book's wording. `translation` is the
        translation module active at the snapshot, null when none. `house_rule_notice` is set
        when the campaign records house rules: tell the GM the installed entry may be overridden.
        `type` and `limit` as `search_compendium`. No snapshot is an error."""
        found = compendium.cite(ws, query, type, limit)
        if found is None:
            raise ValueError("No compendium snapshot yet: connect a GM client once.")
        return found

    def document_report(key: str) -> dict[str, Any]:
        """How a prepared world document was last realised in Foundry: `realised`, then
        `pending` (the desired state changed since and waits for a GM client), and the GM
        client's `report` (its Foundry id, what it became, a conflict waiting for the GM's
        choice, errors such as an unresolved `@prepared:` reference) or `error`."""
        return report(DOCUMENTS_DIR, DOCUMENT_REPORTS_DIR, "document", key)

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
        Tool(fn=whisper, responsibility="disclosure", delegated_action=True, reversible=False),
        Tool(fn=prepare_scene, responsibility="prep", delegated_action=True, reversible=True),
        Tool(
            fn=write_production_manifest,
            responsibility="prep",
            delegated_action=True,
            reversible=True,
        ),
        Tool(fn=scene_report, responsibility="prep", delegated_action=False, reversible=True),
        Tool(fn=prepare_document, responsibility="prep", delegated_action=True, reversible=True),
        Tool(fn=asset_check, responsibility="prep", delegated_action=False, reversible=True),
        Tool(fn=document_report, responsibility="prep", delegated_action=False, reversible=True),
        Tool(fn=browse_files, responsibility="prep", delegated_action=False, reversible=True),
        Tool(fn=search_compendium, responsibility="prep", delegated_action=False, reversible=True),
        Tool(
            fn=lookup_rule,
            responsibility="rules_and_combat",
            delegated_action=False,
            reversible=True,
        ),
        Tool(fn=image_size, responsibility="prep", delegated_action=False, reversible=True),
        Tool(
            fn=list_world_documents, responsibility="prep", delegated_action=False, reversible=True
        ),
        # ponytail: a read sits under memory (canon and continuity), as the Core's own reads.
        Tool(fn=official_name, responsibility="memory", delegated_action=False, reversible=True),
    ]


# The protocol range this block supports (ARC-17): `serve` refuses it outside the range.
BLOCK = Block(protocol=("0.1.0", "0.2.0"), tools=tools)
