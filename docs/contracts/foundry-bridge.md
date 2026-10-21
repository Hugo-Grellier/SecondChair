# Contract: the Foundry bridge and its handshake

Protocol version: **0.1.0** (`secondchair.core.PROTOCOL_VERSION`). Messages: [`foundry-bridge.schema.json`](foundry-bridge.schema.json), with observations in [`event-envelope.schema.json`](event-envelope.schema.json), validated by the Python tests and the module's `node --test`. Requirements: ARC-06, ARC-07, ARC-10, ARC-16, ARC-17, ARC-18, CAP-03, CAP-08, BVE-02, PKG-07, PKG-08, PKG-09, PKG-10, PKG-14, TRC-01, TRC-02, TRC-03, TRC-04, TRC-05, ARC-08, RUL-02, RUL-03, RUL-04, RUL-05, RUL-06, RUL-07, RUL-08, RUL-09, RUL-10, RUL-11, RUL-12, RUL-22, DEL-22, CAN-20, CAN-21, CAL-10..14.

## Who dials whom

`secondchair serve` carries the bridge at `ws://127.0.0.1:<port>/foundry`, on the same loopback port as the MCP endpoint. The `secondchair-foundry` module, running in the **active GM's** browser client, dials it when the world is ready; players' clients never do. The Core never dials Foundry, so a Foundry hosted elsewhere (The Forge, a homelab) connects the same way: the page's origin does not matter, the token authenticates. The Core sees Foundry only while that GM client is connected (PKG-10).

The bridge is the Foundry connector's Python half, `secondchair_foundry`, loaded through the `secondchair.connectors` entry point group: a function called once when `serve` starts, with the served `Workspace`, returning the Starlette routes to serve next to `/mcp`. A connector that raises stops `serve` before it listens, as a refused tool registration does.

## The token

`secondchair token` prints the token, creating it on first use in the machine configuration, `$XDG_CONFIG_HOME/secondchair/foundry-token` (default `~/.config/secondchair/`), mode 0600 (PKG-08, PKG-14). The GM pastes it into the module's **Core token** setting, a client setting kept in that browser only, never on the Foundry server. Delete the file and run `secondchair token` again to replace it. The Core reads the file at each handshake, so `serve` need not restart.

## Handshake

1. The module opens the socket and sends **hello**: `{"type": "hello", "protocol": "0.1.0", "token": …, "world": <Foundry world id>, "campaign": <campaign id stored in the world, or null>}`.
2. The Core answers **welcome** `{"type": "welcome", "protocol": …, "campaign": <campaign id>, "campaign_language": …}` and keeps the socket open, or **refused** `{"type": "refused", "reason": …, "message": …}` and closes it with code 1008. The module shows the message to the GM.
3. On welcome, the module stores the campaign id in the world (a hidden world setting), binding the world to the campaign.

A client that sends nothing within 10 seconds is closed without a reply. The Core checks, in this order:

| Reason | Refused when | Message tells the GM |
|---|---|---|
| `malformed` | the first message is not a hello | to update the module |
| `no_token` | the machine has no token yet | to run `secondchair token` |
| `wrong_token` | the token differs (compared in constant time) | to paste the token `secondchair token` prints |
| `protocol` | the versions are incompatible | both versions, and to install matching ones |
| `busy` | a GM client is already connected | to close it first |
| `world` | the world or the campaign is bound elsewhere | which world or campaign it is bound to |

**Protocol compatibility** (ARC-17): the module sends the protocol version it implements, and the Core accepts it when the major versions match and, while the major is 0, the minor versions too (the semver caret range). A patch difference connects.

**World binding** (PKG-09, ARC-18): the workspace records its world in `foundry.yaml`, the world records its campaign in its world setting.

```yaml
# <workspace>/foundry.yaml, written by the Core on the first welcome
world: secondchair-dev
campaign: 3f2a9c4e0b7d4e1f9a6c2d8b5e0f1a7c
```

- A world carrying a campaign id other than this workspace's is refused: it belongs to another campaign.
- A workspace bound to another world refuses this one.
- An unbound world meeting an unbound workspace is bound on that first contact: the Core writes `foundry.yaml` and the module stores the campaign id.
- The bound world whose setting was lost (reset, re-imported) reconnects and gets its campaign id back.

To rebind a campaign to another world, the GM deletes `foundry.yaml`; to free a world, they clear its hidden setting from the browser console as GM: `game.settings.set("secondchair-foundry", "campaign", "")`.

## After the handshake

While the socket stays open, no other GM client can connect; when it closes, the next one can. Later slices add their messages here.

### Actions (ARC-04, ARC-07, ARC-09)

A delegated action that acts in the VTT returns a `VttAction` ([tool-registration.md](tool-registration.md)). The Core checks the level and, when the action is to be taken, has the bridge send the GM client a **request**; the module takes it and answers with a **reply**:

```json
{"type": "request", "id": "9f1c…", "op": "move_token", "target": "Scene.s1.Token.t1", "params": {"x": 300, "y": 200}, "expect": null, "level": "act-then-review"}
{"type": "reply", "id": "9f1c…", "ok": true, "before": {"x": 100, "y": 200}, "after": {"x": 300, "y": 200}}
{"type": "reply", "id": "9f1c…", "ok": false, "error": "Scene.s1.Token.t1 changed since: nothing was done."}
```

- `target` is the Foundry UUID of the document acted on; `params` the fields to set; `before` and `after` the fields the module read before and after, which the Core logs.
- `level` is the delegation level the Core takes the action at: the entry's effective level when it acts or the GM approves (an approved proposal is at `propose`), null for the GM's undo. The module checks it against the ceiling (below).
- `expect`, when not null, holds the fields the document must still have: an **undo** sends the logged `before` as `params` and the logged `after` as `expect`, so a token the GM moved by hand since is not moved back.
- **Generic operations**, taken by `secondchair-foundry` itself: `move_token` (a Token's `x`, `y`), `set_door` (a Wall's `ds`: 0 closed, 1 open, 2 locked), and the disclosures `reveal_token` (a Token's `hidden`) and `publish_journal` (a JournalEntry's `ownership.default`, set to 2, observer: a dotted field names a nested one, in `params`, `before` and `after`), and `speak` (a Token says `params.content` aloud, a public in-character chat message spoken by it, its text escaped; `before` is `{"message": null}`, `after` the new message's id; irreversible, so an undo of it is refused), and `whisper` (the same for a line whispered to one player: `target` is the User's UUID, the chat message is whispered to that user and spoken by no token). Any other `op` is a **mechanical action**, handed to the system adapter ([below](#system-adapters-arc-08-adr-0004)) as `ops[op](target, params, expect)`, which resolves its own target. With no adapter, the module refuses it (ARC-09).
- **Idempotent write queue** (transplanted from v3, BVE-02): the module records each request id on the GM user before and after taking it, so a replayed id gets its first reply back and is never applied twice, even after a reload; a request a reload interrupted is answered with an error asking the GM to check the VTT. Requests are taken one at a time.
- A **failed action** is one the VTT did not take: no GM client connected, or a refusal (`ok: false`). The Core logs it with status `failed` and the error, and the agent gets the error. Nothing is retried.
- The Core logs an action with status `unknown` before sending its request, and does not hold the workspace lock while the GM client takes it: other actions, approvals and GM gestures go on meanwhile. The reply settles the entry as `applied` or `failed`. With no reply within 15 seconds the agent gets an error saying the action may have been taken, and the entry stays `unknown`, with that error, until a late reply on the same connection settles it; if the GM client leaves first, it stays `unknown` for the GM to check in the VTT. Undo refuses an `unknown` entry.

### The ceiling (DEL-19, DEL-19a, DEL-20)

The module enforces its own **ceiling**, whatever the Core asks: one maximum delegation level for every action reaching this world. It is the world setting **Delegation ceiling** of `secondchair-foundry` (`manual`, `propose`, `act-then-review`, `autonomous`), `act-then-review` on a fresh world, so no base profile exceeds it and *autonomous* takes raising it in Foundry on purpose.

- It also bounds the realisation of a [prepared scene](#prepared-scenes-arc-10-bve-02) or [world document](#prepared-world-documents-arc-07-arc-10), at the `level` the `realise` or `realise_document` message carries.
- A request whose `level` is above the ceiling, or not a level, is refused before anything is read: `{"type": "reply", "id": …, "ok": false, "error": "Refused by this world's delegation ceiling (propose): …", "reason": "ceiling"}`. A `null` level, the GM's undo, is not bounded. The ceiling is read at each request, so a change applies at once.
- The Core logs the refusal as a failed action and writes a **call** on the GM, `kind: ceiling_refusal`, in `calls/` ([workspace-layout.md](workspace-layout.md)).
- Only a GM user changes it: Foundry keeps world settings to users with the *Modify configuration settings* permission, and the module refuses the change in the client of a user who is not a GM, even when that permission was granted to players. A change by a non-GM user that still lands is put back by the active GM client.
- Each change is an **observation** (below) of kind `ceiling`, visibility `gm`, payload `{"user": <Foundry user id>, "before": …, "after": …}`, captured by the active GM client in every moment: tagged with the live session when one is open, else with `session: null`.

### The Director's Desk (ARC-12, ARC-13, ARC-14)

The **Director's Desk** is a minimal window of `secondchair-foundry`, with no tabs, shown only in the GM client connected to the Core (players' clients never open the bridge, and the module renders nothing and sends no gesture for a user who is not a GM). It opens when the module connects and whenever a call is due now; **Shift+D** (a GM-only keybinding) opens it again. It shows the current moment, the world's ceiling (read-only: it is changed only in the module settings), the calls due now, the break pile once the GM signals a break, the active NPC's **acting cue** (DEL-15: its goal, its optional `posture` (a few words on its emotional state, GM-only direction that is not audience content and never goes through the audience check), the line an agent last showed with `show_acting_cue`, what it knows and does not know, with **I voice this one** or, once the GM voices it, **Hand back**; shown at every level, manual included, since it is a read), and the facts and events recorded from the GM's words that await confirmation at the GM-decision rank.

It holds no state (ARC-11): the Core sends the module a **desk** message after `welcome`, whenever the moment, the calls due now, the acting cue, the action log or the turn driver change (it looks every second), and after each gesture. `turn_driver` is the one the connected client's rules context names, or null; while there is one the agents stay silent (RUL-12): the cue's `line` is null and the Desk says the driver runs the GM creatures' turns. Each button sends a **gesture**, which the Core takes and answers with a **result**:

```json
{"type": "desk", "moment": "live-session", "session": 3, "calls": [{"id": 4, "kind": "proposal", "responsibility": "disclosure", "deadline": "now", "status": "open", "entry": 12, "message": null, "detail": "speak by claude-live on lines/1.md: The bell rings.", "reversible": false}], "decisions": [{"id": "f-1a2b3c4d", "text": "The bell tower fell.", "words": "The bell tower fell in 4710."}], "cue": {"npc": "e-1a2b3c4d", "name": "Tovan Reed", "goal": "Keep the party away from the tower.", "line": "It only rings when the nights are dry.", "knows": [{"id": "f-5e6f7a8b", "statement": "The bell rings on dry nights.", "mode": "knows"}], "does_not_know": [{"id": "f-9c0d1e2f", "statement": "A cracked relay rings the bell."}], "voiced": false}, "turn_driver": null}
{"type": "gesture", "id": "g1", "gesture": "reject", "entry": 12, "reason": "tone"}
{"type": "result", "id": "g1", "ok": true}
{"type": "result", "id": "g2", "ok": true, "pile": […]}
{"type": "result", "id": "g3", "ok": false, "error": "Session 3 is already open; end it first."}
```

| Gesture | Fields | Does |
|---|---|---|
| `approve` | `entry` | approves a pending proposal (DEL-28), irreversible ones included (DEL-29) |
| `reject` | `entry`, `reason` | rejects it, the reason one of contradiction, rules, tone, other (DEL-26) |
| `confirm` | `doc` | confirms a fact or event from the GM's words as a GM decision (CAN-09, DEL-29) |
| `break` | | signals a break; the result carries the break pile (DEL-30, DEL-32) |
| `start_session` | | opens live-session with the next session id, refused while one is open (DEL-03, DEL-03b) |
| `end_session` | | ends it: between-sessions, and "wrap a session" is queued (DEL-03, DEL-04) |
| `voice` | `entity` | "I voice this one": entity overrides at manual, every moment, on npcs and disclosure for that NPC; its pending calls and queued jobs on them are withdrawn with their safe default (DEL-14, DEL-15, DEL-16) |
| `hand_back` | `entity` | "Hand back": removes those overrides, refused when the GM does not voice that NPC (DEL-14, DEL-15) |

The Desk is an **authenticated Surface** (ARC-13): its gestures reach the Core only over the bridge the token authenticated, from the GM client. The Core logs them as GM interactions with channel `desk` and `authenticated: true` (DEL-27). A gesture on a VTT action is taken in a worker thread, so the Core can send the GM client its request while the gesture waits.

The GM's approval or undo of a VTT action from the CLI needs the GM client, which only the `serve` process holds: the CLI relays it to `POST /gm` on the served Core ([tool-registration.md](tool-registration.md)).

### Observations (ARC-16, CAP-03, CAP-08)

While a live session is open, the module captures what happens at the table as **observations**, each in the **event envelope** ([`event-envelope.schema.json`](event-envelope.schema.json)): `id`, `session`, `at`, `scene`, `actor`, `kind`, `visibility`, `payload`.

```json
{"type": "session", "session": 3}
{"type": "observation", "envelope": {"id": "4b1e…", "session": 3, "at": "2026-10-19T20:15:00.000Z", "scene": "Scene.s1", "actor": "Actor.a1", "kind": "chat", "visibility": "players", "payload": {"author": "Gamemaster", "speaker": "Sella", "text": "The bell rings.", "flavor": "", "whisper": [], "rolls": []}}}
{"type": "ack", "id": "4b1e…", "ok": true}
```

- **Session**: the Core sends `session` right after `welcome` and whenever `secondchair session start|end` opens or ends one (it looks at `moment.yaml` every second): the live session id, or null. The module captures only while it is not null, and tags every envelope with it.
- **Generic kinds**, captured by `secondchair-foundry`: `chat` (every chat message: author, speaker, text, flavor, whisper recipients' names, rolls' formula and total), `combat` (`start`, `round`, `turn`, `end`, with the combatant), `scene` (`activate`), and `ceiling` (above); and `clock` and `rules_context`, which a system adapter fills ([below](#the-rules-context-and-the-world-clock-rul-22-cal-10cal-14)). These three are captured in every moment, with `session: null` outside a live session. A system adapter's own kinds are prefixed by its system id and their payload schemas ship with it.
- **Visibility** (ARC-16): `players` when the whole table saw it; `gm` when it was not shown to the table (GM-only, a whisper even to a player, a hidden combatant's turn); `blind` for a blind roll. Only `players` attests what the party knows: the Core refuses a party knowledge record whose origin quotes a `gm` or `blind` observation (CAP-08: a whisper or a blind roll becomes a call held for the wrap).
- **Durable capture** (transplanted from v3, BVE-02): the module keeps each envelope in the browser's local storage before sending it, and drops it only on its `ack`. Whatever is held (sent before a reload, or captured while the Core was unreachable) is resent on the next welcome. The Core appends each envelope to `observations/<session>.jsonl` in the workspace (`observations/outside-sessions.jsonl` for `session: null`), once per id, before acknowledging it, so a resent envelope is never recorded twice. An envelope the Core cannot take (malformed, or for a session not yet opened) is acknowledged with `ok: false` and an `error`, and the module drops it.

### Prepared scenes (ARC-10, BVE-02)

Prep holds a scene as a **desired state** in the workspace, `scenes/<key>.yaml` ([workspace layout](workspace-layout.md#scenes)), written by the delegated action `prepare_scene` (prep, reversible). Its format is the schema's `desired_scene`: the Scene's Foundry fields (`scene`, `name` required), the objects placed on it (`items`, each `{key, type, data}`, a Token also taking `actor`, the UUID of the world or compendium Actor it is made from), and the GM's `choices`.

While a GM client is connected, the bridge sends it each desired scene it has not realised in this connection, then each one whose file changes (it looks every second), one at a time:

```json
{"type": "realise", "id": "4b7e…", "scene": "goblin-cave", "desired": {"scene": {"name": "Goblin cave"}, "items": [{"key": "boss", "type": "Token", "actor": "Compendium.pf2e.pathfinder-bestiary.Actor.x", "data": {"x": 100, "y": 100, "hidden": true}}]}, "level": "act-then-review"}
{"type": "realised", "id": "4b7e…", "ok": true, "report": {"scene": "aB3…", "summary": {"create": 2}, "actions": [{"action": "create", "key": "_scene"}, {"action": "create", "key": "boss"}], "errors": []}}
{"type": "realised", "id": "5c8f…", "ok": false, "error": "Refused by this world's delegation ceiling (propose): it was asked at act-then-review.", "reason": "ceiling"}
```

The **ceiling** bounds a realisation (DEL-19a), checked when the scene is realised. `level` is the effective level of the `prepare_scene` entry that last wrote the desired state, or null when the GM wrote it last, by a logged hand edit or an undo, which the ceiling does not bound; any other origin is sent at `autonomous` (#163), a hand edit of `scenes/` or `documents/` included: CAN-11 logs hand edits of `canon/` only. Above the ceiling the module refuses it before reading anything, with `reason: "ceiling"`, and warns the GM. A refused realisation is not an action: no entry is logged and no call is made; the refusal is the scene's report, and the bridge sends the scene again after the next change of the ceiling (its `ceiling` observation).

With no GM client the desired state waits: every connection starts by sending all of them, which changes nothing in a scene already realised. [Prepared documents](#prepared-world-documents-arc-07-arc-10) are sent first in each look, and every scene again after a document is sent, so a scene uses the documents it refers to. The Core keeps each scene's last report in `.secondchair/scenes/<key>.json`; the read `scene_report(key)` returns it, with `pending` when the desired state changed since, and a `production` object of three separate states, each false until proven: `structurally_valid` (the desired scene passes the read `asset_check(key)`), `realised` (the last report is current, `ok`, and has no error and no conflict) and `smoke_tested` (a player-view preview ran in Foundry; always false until that exists). `asset_check(key)` reads only and fixes nothing: for the scene and the prepared documents it names, it checks that every `src`, `path` and `img` file exists (`image_size`, else `browse_files`), that `grid.size` divides the background map's size, that every Token `actor` resolves (`resolve_uuid`, or a prepared Actor) and that every `@prepared:` reference has its document. It returns `passed`, and the checks as `missing`, `mismatched`, `ok` and `skipped`; with no GM client the Foundry checks are `skipped`, not failed. A compendium Actor is imported into the world once, the first time a token needs it.

**Reconciliation**, transplanted from v3 and run by the module (`scenes.js`): the Scene and each object it places carry, in their `secondchair-foundry` flags, their key, the fingerprint of what prep asked for (`spec`) and of what was written, read back from Foundry with the play state left out (`local`). For each object:

| Prep | In Foundry | Action |
|---|---|---|
| new | absent | `create` |
| new | deleted since it was created (killed, picked up, removed by the GM) | `kept-deleted`, unless the GM chose `recreate` |
| unchanged | unchanged | `noop` |
| unchanged | retouched by the GM | `retouched`: kept |
| changed | unchanged | `update`, leaving the play state as it is |
| changed | retouched | `conflict`: kept until the GM chooses `keep` or `overwrite` |
| removed | unchanged / retouched | `delete` / `conflict` (deleted this way, it is created again if prep adds it back) |
| type changed | unchanged / retouched | `create` the new one; the old one as if removed |

A Token whose `actor` prep changed is rebound to the new Actor on update. A copy the GM pasted carries the same key: only one object per key is prep's, the others are the GM's.

A desired scene gets a [prepared document's guards](#prepared-world-documents-arc-07-arc-10): `prepare_scene` refuses an `ownership` key anywhere in the scene or an item's data. By allowlist, it also refuses:
- an update operator key (`-=…`, `==…`) at any depth of the scene or an item;
- an embedded collection in the scene itself (`drawings`, `levels`, `lights`, `notes`, `regions`, `sounds`, `templates`, `tiles`, `tokens`, `walls`, dotted or not): what a scene places arrives only as an item;
- an item's `flags` of any namespace but `secondchair-foundry`;
- a Region's `behaviors` that is not a list of objects (or is given as dotted keys), or holds a behaviour whose type is not one of `adjustDarknessLevel`, `displayScrollingText`, `modifyMovementCost`, `pauseGame`, `suppressWeather`, `teleportToken` (any other, such as `executeScript`, `executeMacro`, a module's, or `toggleBehavior`, which enables any behaviour by UUID, could run code in every client);
- a Token's `delta`: a token is made from its actor.

In the scene, its items and a [prepared document](#prepared-world-documents-arc-07-arc-10) (its embedded documents included), flags are prep's only in the `secondchair-foundry` namespace, and never its identity flags, which reconciliation writes (`scene`, `document`, `created`, `spec`, `shape`, `local`, `source`, `base`, `key`): `prepare_scene` and `prepare_document` refuse the others, and refuse an update operator at any depth; the module drops them, and refuses an operator too.

The module, after expanding dotted keys, drops the ownership keys and an item's foreign flags namespaces, sanitizes every HTML string (a Note's, a Tile's or Drawing's text), and refuses the rest as a whole scene.

A scene's map, `scene.background` and `scene.foreground` (`{src}`), is written where the Foundry version keeps it: from Foundry 14, in the scene's default level (`levels[0]`, `defaultLevel0000` on a new scene), since Foundry 14 ignores the Scene's own `background`; and read back from there, so a map the GM changes is a retouch.

The **play state** is never compared nor rewritten: a token's position, elevation, rotation, visibility and actor delta, a door's state, a light, sound, tile or drawing's visibility, whether a region's behaviours are disabled. So a token the GM or a player moved stays where it is when prep changes it. A retouch is judged on the fields prep wrote only. The scene itself (`_scene`) is reconciled the same way, never deleted. An object that cannot be written is reported in `errors`; the others are still realised.

### Prepared world documents (ARC-07, ARC-10)

Prep also holds the world documents a session needs as desired states, `documents/<key>.yaml` ([workspace layout](workspace-layout.md#documents)), written by the delegated action `prepare_document(key, type, data, base, choice)` (prep, reversible): an NPC `Actor`, a GM handoff or handout `JournalEntry`, a treasure `Item`, a music `Playlist`, a `RollTable`. Its format is the schema's `desired_document`: `type`, `data` (the document's Foundry fields), `base` (the UUID of a compendium or world document it is made from, `data` merged on top) and the GM's `choice`. A journal's text page may give `text.markdown`: the module stores it as HTML (`text.content`, `format` 1), converted with the showdown Foundry's client ships. Every string holding HTML (`<`) in `data` and its embedded documents, and every page converted from Markdown, is sanitized with Foundry's `cleanHTML`, since any may land in an HTMLField (a page's text, an actor's notes, an item's description), so a prepared document runs no script; with no sanitizer it is not written. A document is always created the GM's only (`ownership.default` 0): who sees it is a disclosure, made only by `publish_journal` (DEL-09), so `prepare_document` refuses a key with an `ownership` segment anywhere in `data`, however spelled (`ownership`, `ownership.default`, `-=ownership`, `==ownership`, `pages.0.ownership`), and an embedded field (`pages`, `sounds`, `items`, `results`) not given whole as a list; the module, after expanding dotted keys as Foundry does, drops every ownership key a hand edit adds, at any depth, refuses an embedded field that is not a list, and never writes ownership on update.

The bridge sends them as it sends scenes, before the scenes in each look, and keeps each report in `.secondchair/documents/<key>.json`, returned by the read `document_report(key)`:

```json
{"type": "realise_document", "id": "6d1a…", "document": "ransom-note", "desired": {"type": "JournalEntry", "data": {"name": "The ransom note", "pages": [{"name": "Note", "type": "text", "text": {"markdown": "Bring **100 gp**."}}]}}, "level": "act-then-review"}
{"type": "realised", "id": "6d1a…", "ok": true, "report": {"document": "jR7…", "summary": {"create": 1}, "actions": [{"action": "create", "key": "ransom-note"}], "errors": []}}
```

The module (`documents.js`) finds the document by its key in its `secondchair-foundry` flags (`document`), in any of the five types, and reconciles it as one object of a scene ([above](#prepared-scenes-arc-10-bve-02)): `create`, `update`, `noop`, `retouched`, `conflict`, `kept-deleted` (deleted in Foundry since it was created: the world remembers the keys it created, in a hidden world setting), `recreate` on the GM's choice; a change of type creates the new one and deletes the old one. `report.document` is its Foundry id, null when it is not in the world. Its play state is never compared nor rewritten: its `ownership` (a journal published to the players), a playlist's or sound's `playing` and `pausedTime`, a table result's `drawn`. On update, the embedded documents `data` gives (a journal's `pages`, a playlist's `sounds`, an actor's `items`, a table's `results`) are replaced as a whole, so their ids change. A document dropped from prep stays in the world.

**References**: in a desired document or scene, a string value `"@prepared:<key>"` is the realised prepared document's id, and a Token item's `actor: "@prepared:<key>"` that Actor's UUID; `"@prepared:<playlist key>/<sound name>"` is that playlist sound's id (a Scene's `playlist` and `playlistSound`). The module resolves them before reconciling; one with no realised document is null, and an error in the report.

### Behaviour traces (TRC-01 to TRC-05; ADR 0012)

Behaviour traces record how each consenting user operates Foundry, in every moment. They say nothing about the fiction.

- **Consent** (TRC-01): each user ticks **Record my behaviour traces** in their own module settings. It is off by default and kept in that user's browser, per world and user, so nobody can give it for someone else; the module records nothing and sends nothing until it is on. The user's own client mirrors it in a user flag, `flags.secondchair-foundry.traces`, which the players list shows with a dot; a flag someone else wrote is set back by the user's client. Unticking stops recording at once, unsent records included, and offers to erase every trace already kept: the module sends `erase_traces` for that user, through the active GM's client, and tells the user whether it reached the Core.
- **Two streams on one clock** (TRC-02): each record carries `t`, milliseconds on the capturing client's clock, and a `stream`. The `semantic` stream holds `event`s: `window.open` and `window.close` (`window`, `app`, `document` UUID or null), `roll` (`formulas`), `target` (`token`, `on`), `move` (`token`), `turn` (`combat`, `round`, `turn`, and `own`: the new combatant is this user's, for a GM a GM creature with no player owner), `focus` and `blur`, plus a system adapter's, prefixed by its system id, sent through `game.modules.get("secondchair-foundry").api.trace(event, data)`. The friction detectors read these adapter events by the name after the prefix: `move.cancel` (a token move cancelled), `roll.cancel` (a roll dialog cancelled), and `action`, `strike` or `spell` (an action started). A semantic event triggered while the client performs a request or a realisation of the Core carries `"secondchair": true`: it is SecondChair's own write, not the user's act. The `input` stream holds `click` (`button`, screen `x`, `y`, `canvas` position or null, `target` element as tag, id, classes and `data-action`, never text), `move` (sampled at the world setting's rate, 10 per second by default, while the window has focus), `wheel` (`dy`), `drag`, `drop` and `key` (`key` and modifiers) outside text fields. In a text field (input, textarea, select, contenteditable) a key press is only `{"input": "type", "del": <Backspace or Delete>}`: the rhythm, never a character.
- **Relay** (TRC-05): each client sends its records about once a second. A player's client sends them, and its erase request, as a Foundry query (`secondchair-foundry.traces`, `secondchair-foundry.erase`; Foundry 13+ `User#query`) addressed to the active GM's user, so no other client receives them, unlike a module socket message, which Foundry relays to every client. Foundry reports the querying user, so a player cannot send or erase traces as another. A query the active GM's client refuses (it is no longer the active GM) or that fails, for instance because the GM removed the players' *Query users* permission, loses its records like a send with no GM client. The active GM's client sends the Core one **traces** message per user, its own included, with `gm` true when that user is a GM. There is no buffer: with no GM client open, or a GM client not connected to the Core, records are dropped and counted, and the next records sent start with a `gap` record (`from`, `to`, `lost`).

```json
{"type": "traces", "user": "aB3dE5fG7hI9jK1l", "name": "Alice", "gm": false, "records": [
  {"t": 1760000090000, "stream": "gap", "from": 1760000000000, "to": 1760000090000, "lost": 42},
  {"t": 1760000091000, "stream": "input", "input": "click", "button": 0, "x": 640, "y": 360, "canvas": {"x": 2100, "y": 1450}, "target": "canvas#board"},
  {"t": 1760000091200, "stream": "input", "input": "type", "del": false}
]}
{"type": "erase_traces", "user": "aB3dE5fG7hI9jK1l"}
```

- **Where they are kept** (TRC-04): the Core appends each record, tagged with the current `moment` and its `seq` (the first record of each message also with the user's `name` and `gm`), to `$XDG_DATA_HOME/secondchair/traces/<campaign id>/<user id>.jsonl` (default `~/.local/share/secondchair/`), a Source on the GM's machine, outside the workspace, never sent anywhere. Nothing expires them in v4: `erase_traces` deletes a user's file and rewrites the reports of every moment it had records in, and the GM may delete any file. Traces are not acknowledged; a message the Core cannot read or keep is lost like one with no GM client.
- **Report** (TRC-03): the Core rewrites a moment's friction report in the workspace ([workspace-layout.md](workspace-layout.md#frictions)) when a gap arrives in it, and once a user's first records of the next moment arrive.

### System adapters (ARC-08, ADR 0004)

A system adapter is its own Foundry module that requires `secondchair-foundry` and registers through a hook the library calls once, during Foundry's `init`, so a third party can ship one from its own repository (LIC-08):

```js
Hooks.once("secondchairFoundryInit", (api) => api.registerAdapter({
  ops: {set_date: async (target, params, expect) => ({before, after})},  // mechanical actions
  reads: {rules_context: async (params, {language}) => …, official_name: …},  // see Reads
  translations: {fr: "pf2-fr"},                    // campaign language -> required module
  observe: (emit) => { /* emit({kind, visibility, payload, anytime}) on Foundry hooks */ },
}));
```

- **Translation module** (CAN-21, RUL-18): when the welcome's `campaign_language`, or its primary subtag, has an entry in `translations` and that module is not active in the world, the module closes the socket and tells the GM, in a permanent notification, which module to install and enable. It stays disconnected until the GM reloads with it enabled.
- `observe` hands the adapter the library's durable capture: what it emits is an observation like the library's own.
- `secondchair-foundry-pf2e` is the first adapter. Its own mechanical action is `set_actor` (target an Actor UUID, `params` setting `system.attributes.hp.value`, `system.attributes.hp.temp` or `system.resources.focus.value`), such as a discrepancy's fix. It targets **Foundry v14 + pf2e 8.x** (RUL-02): its manifest declares that pair, so Foundry warns elsewhere, and on any other Foundry generation or pf2e major it does not register and tells the GM why; SecondChair then runs without an adapter (ARC-09). It requires `pf2-fr` for a `fr` campaign.
- The PF2e adapter traces its user's own acts for the friction detectors (TRC-02, TRC-03), through `api.trace` on every client: `pf2e.strike`, `pf2e.spell` or `pf2e.action` (`item`, the origin item's UUID or null) when an act starts, that is when pf2e's check dialog opens, or without a dialog when its roll or card is posted (a weapon's attack roll is a strike; a spell's attack roll or an actual cast, not a spell sent to chat, a spell; a system action's check, an action's card or a self-effect, an action; damage and re-rolls start nothing); `pf2e.roll.cancel` (`dialog`: `check` or `damage`) when a roll dialog closes without rolling; `pf2e.move.cancel` (`token`) when a token drag is cancelled rather than dropped.

### The executor (RUL-03..10)

The PF2e adapter's own executor takes a GM creature's turn in an encounter, each request one call to pf2e's document methods, never a chat card's button (which acts on the clicking user's selection). `target` is the acting token's UUID (`Scene.<id>.Token.<id>`):

| `op` | `params` | Does |
|---|---|---|
| `strike` | `{strike, target, map}` | rolls the strike (its slug in `actor.system.actions`) at MAP step `map` (0, 1, 2) against the `target` token; on a hit, rolls the damage (critical on a critical hit) and applies it to the target with `actor.applyDamage`, a PC included (RUL-04) |
| `use_action` | `{action, target}` | uses the system action `game.pf2e.actions.get(action)` against the `target` token, required: without one pf2e would fall back to the GM's own targets |
| `saving_throw` | `{save, dc}` | the token's save (`fortitude`, `reflex`, `will`) against `dc`: a GM creature's is rolled; a PC's is never rolled, its player is asked with a chat message carrying pf2e's inline check (`@Check[reflex\|dc:20]`) |
| `cast_spell` | `{spell, rank, variant, actions}` | casts the creature's spell (its item id or slug) through its spellcasting entry's `cast`, which spends a prepared slot, a spontaneous slot, a focus point or an innate use (a cantrip or an at-will spell spends nothing), at `rank` (heightened; the spell's own when null) and as the overlay `variant` (`spell.loadVariant`, one of its overlay ids, or null). A spell whose cast time is variable (`1 to 3`) and that has no overlay is refused unless `actions`, the cost an agent proposed, is given: the Core only sends it once the GM approved (RUL-08). Refused, nothing cast, when pf2e spent nothing on a spell that costs something (no slot, point or use left) |
| `self_effect` | `{item}` | posts the creature's action or feat `item` (its slug, one with a `selfEffect`) to the chat with `item.toMessage`, waits for it to settle, then puts the self-effect on the creature (a copy of the Effect item its `selfEffect.uuid` names) unless an effect of that slug is already there (RUL-06, RUL-10) |
| `place_area` | `{area, size, x, y, direction, name}` | creates an effect-area Region on the creature's scene from the agent's origin (`x`, `y`, scene pixels), as pf2e's own `placeRegionFromItem` shapes it (`flags.pf2e.areaShape`): `burst` a circle of radius `size` feet, `cone` (90°) and `line` (5 ft wide) `size` feet long pointing `direction` degrees; `size` a multiple of 5 (RUL-06) |
| `reaction` | `{strike, target, trigger}` | Reactive Strike: refused unless `trigger` is on the closed list `leaves-reach`, `manipulate`, `move`, `ranged-attack` (within reach), the creature has Reactive Strike (an action slug `reactive-strike` or `attack-of-opportunity`), the `target` token is within the strike's reach (`actor.getReach`), and its reaction is unused this round, by the adapter's counter (the combat and round it last reacted in, a round running from the start of its turn to the next, since a creature gets its reaction back on its turn; kept in the GM client) and by every known reaction tracker that is active (Reaction Checker's combatant flag `state` false, Combater's `reactionUsed`, Sundry's `effect-reaction-used` effect). Then strikes as `strike` at MAP step 0 and counts the reaction (RUL-07). Every other reaction is the GM's (RUL-08) |

- **Refusals**: an op whose acting token's actor has a player owner (a PC: its player acts, RUL-04), or whose token is not a combatant of the started combat (RUL-03), is refused before anything is rolled. `saving_throw` asks a PC rather than refusing it, and is refused outside a started combat too. Rolls skip pf2e's dialogs, since an agent's call cannot wait on one.
- **Turn drivers** (RUL-11, RUL-12, DEL-22): while a known turn driver is active (a closed list of module ids: `pf2e-combater`), every executor op, reactions included, is refused for every creature before anything is rolled: the GM runs turns through the driver. Only the undo of an action taken before it came on still runs. Every other op, the library's and the adapter's (`set_actor`, `set_date`), works as before.
- **Before and after**: `before` is `{"state": {<token UUID>: {"hp": {value, temp}, "conditions": {<slug>: <value or null>}, "resources": {<key>: <count>}, "effects": {<effect item id>: <slug>}}}}` for every token the op touches (the acting creature and its target), `resources` keyed as in the outcome traces (`focus`, `<entry>.slot<n>`, `<entry>.slot<n>.<spell>`, `<spell>.uses`); `after` the same state once the call settled, with `degree` (pf2e's, or null), `damage` and `applied` (strike and reaction: the damage roll's total, null on a miss; `applied` when the executor applied it, `already` when a module had), `follow_ups` (use_action; self_effect: `{token, effect, result}`), `requested` (saving_throw: true when a player was asked), `spent` and `actions` (cast_spell: the resource keys it lowered, the proposed cost or null), `trigger` and `round` (reaction: `<combat id>.<round>`). `place_area`'s `before` is `{"region": null}` and its `after` `{region: <its UUID>, area, shape}`.
- **Undo**: the Core's undo sends the logged `before` as `params` and the logged `after` as `expect`; the op then puts each token's HP, conditions and spell resources back and removes the effects it added, refused when any of them changed since; an undone reaction no longer counts for its round. `place_area`'s undo deletes the Region, refused when it is gone. The chat messages stay.
- **Follow-ups** (RUL-10): after the call, the adapter waits for it to settle (1.5 s), then looks at the condition the action's degree gives its target (`demoralize`: frightened 1, 2 on a critical success; `trip`: prone; `grapple`: grabbed, restrained on a critical success). Already there at that value or more: `already`, nothing is done (a module applied it, or the target had it). Unchanged by the call: the adapter sets it, `applied`. Changed while the call settled, but not to it: `ambiguous`, never applied. Each is recorded as a `pf2e.outcome` observation of type `follow-up` (its `follow_up` section, [`pf2e-outcome.schema.json`](pf2e-outcome.schema.json)), in every moment; the rules check `follow_up` raises an ambiguous one as a discrepancy. A strike's damage is settled the same way: after the damage roll the adapter waits, and applies it only when the target's HP did not move meanwhile (a module that applies damage from the roll already did). A miss and a save do not wait.

### Outcome traces (RUL-13, RUL-19)

While a live session is open, in every mode of play, the PF2e adapter emits a `pf2e.outcome` observation for each outcome it sees, its payload following [`pf2e-outcome.schema.json`](pf2e-outcome.schema.json): a pf2e chat message with a context (a check with its roll breakdown, DC, degree before and after adjustment; a damage roll; damage taken with the damage roll of the same item, the IWR the message shows and the HP before and after; a spell cast with the slot, focus point or innate use it spent, counted before and after) and each condition change of an actor (its conditions before, once seen, and after). The visibility is the message's, `gm` for a condition change. Its `flags` carry, as the modules wrote them, pf2e's `dosAdjustments` and the flags the trace readers know: PF2e Toolbelt's on the message, PF2e Visioner's on the actor's token, Reaction Checker's (`pf2e-reaction`) and Combater's on its combatant, and the actor's effect slugs when Sundry is active. While a turn driver is active, each outcome of a GM creature (an actor with no player owner) names it in `turn_driver`: the executor is off, so the act is the GM's, run through the driver, and the user is the one whose client made it (RUL-12). The Core's rules checks read them ([tool-registration.md](tool-registration.md#rules-checks-and-discrepancies)).

### Reads (CAN-20, RUL-22)

What only the VTT knows, asked by the Core: `{"type": "read", "id", "op", "params"}`, answered `{"type": "reply", "id", "ok": true, "result": …}`, or with `ok: false` and an `error`. A read changes nothing, so it is neither queued nor recorded with the handled requests. The library answers its own generic reads (ARC-07), then the adapter's `reads[op](params, {language})`, and refuses one neither knows. With no GM client, or no reply within 15 seconds, the read fails with a message for the agent.

The generic reads, answered by `secondchair-foundry` whatever the system, each bounded to 100 entries so a reply stays small; a `path` is relative to Foundry's data (no scheme or URL such as `https:`, `data:`, `blob:`, `file:` or `//`, no leading `/`, no `..` segment) and `browse_files` reads `data` or `public` only, refused by the Core's tool and again by the module; the Core's tools of the same names (prep) forward them, for an agent to find the maps, sounds, tokens and creatures of the GM's install:

| `op` | `params` | `result` |
|---|---|---|
| `browse_files` | `{path, source, extensions}` | `{dirs, files, more?}`: Foundry's file picker browse of `path` in `source` (`data`, `public`), files filtered by `extensions` when given; `more` counts what was left out |
| `search_compendium` | `{query, type, limit}` | `[{uuid, name, type, pack, img, level, rarity, traits}]` (the last three pf2e's, from `system.details.level.value` or `system.level.value` and `system.traits`, null when absent): every pack's index entries whose name contains `query` (any case), `type` a document type (Actor, Item…) or the entry's system type (npc, loot…), at most `limit` (20 by default) |
| `image_size` | `{path}` | `{width, height}`: the pixel size of an image or video in the GM's install, loaded with Foundry's texture loader, to size a scene from its map |
| `resolve_uuid` | `{uuid}` | `{uuid, name, type}` of the world or compendium document the UUID names, `null` when there is none: what `asset_check` resolves a Token's `actor` with |
| `list_world_documents` | `{type, query}` | `[{uuid, id, name, prepared_key}]`: the world's documents of `type` (Actor, JournalEntry, Item, Playlist, RollTable, Scene) whose name contains `query`; `prepared_key` the key of the prepared document or scene it realises, else null |

| `op` | `params` | `result` (PF2e adapter) |
|---|---|---|
| `compendium_snapshot` | `{}` | `{system: {id, version, translation}, entries: [{uuid, slug, name, type, pack, level, rarity, traits, publication, remaster}]}`: every pack entry's metadata, no description and no text (LIC-12). `translation` is the official translation module's title, or null |
| `rules_context` | `{}` | `{foundry, system, system_version, modules: {<active module id>: <version>}, settings: {<pf2e rules setting>: <value>}, turn_driver: <active turn driver's module id, or null>}` |
| `official_name` | `{key, pack}` | `{name, key, pack}`: the name in the GM's install, the stable English key (`system.slug`, else pf2e's slug of the English name), and the pack only when the key is in several packs |

`official_name` matches `key` against each compendium index entry's slug or English name (`flags.babele.originalName`, else its name); several packs holding it with no `pack` given is an error naming them. The `name` is the translated name with pf2-fr's `vf-vo` suffix (` (<English name>)`) stripped. It is `null` when the entry has no translation in a non-English campaign: an official name is never machine-translated silently, so an agent proposes one or the GM chooses (CAN-21). `doc.name` is only ever a label. The Core's `official_name` tool returns `{name, official_reference: {key, pack}}`, ready for `create_entity`.

### The rules context and the world clock (RUL-22, CAL-10..14)

- **Compendium snapshot** (#190): right after the welcome, as a follow-up so its size holds nothing up, the Core reads `compendium_snapshot` (up to 120 seconds) and keeps it as `.secondchair/compendium/<system version>.json`, derived and rebuildable. The `search_compendium` tool always returns `{entries, offline, snapshot}` (`snapshot` the latest snapshot's system version, null if none; the module read itself still returns the bare list) and answers from the latest snapshot, as `{entries, offline: true, snapshot: <system version>}`, when no GM client is connected, and also matches an entry's slug or exact UUID; with no snapshot it fails as before. A system version that differs from the previous snapshot's is reported on the `serve` console with the entries added, removed and changed.
- **Rules context**: the Core reads `rules_context` when the GM client connects and at the start of each moment (it looks at `moment.yaml` every second), and records it as a `rules_context` observation (visibility `gm`) unless it is the one already recorded in that moment. Toggling a module in Foundry reloads the client, which connects again. The adapter also emits one when a rules setting changes.
- **Clock advances** (CAL-12): the adapter emits a `clock` observation (`{date, world_time}`, visibility `gm`) at every advance of the world clock, its date read in the campaign calendar (PF2e: Absalom Reckoning, the world clock's Gregorian year plus 2700).
- **Session start** (CAL-10, CAL-11): the Director's Desk's Start session, or `secondchair session start` while a Core serves the campaign (it relays `{"gesture": "session_start"}` to `POST /gm`), also pushes the current date. When the campaign calendar is a System extension's named calendar (`calendar: absalom`) and the campaign has a current date (`time.yaml`), that Core takes `set_date` with target `time`, `params` `{calendar, date}` and level null (a GM gesture, not bounded by the ceiling). The adapter moves the world clock by whole days, keeping its time of day, and the Core records the date it reports after as the session's first `clock` observation. A declared calendar is never synced. The CLI prints what was done; the Desk shows it from its `result`'s `message`.
- The PF2e adapter refuses `set_date` for another calendar, a date before 1 Pharast 4600 or after 28 Calistril 4800 AR, where the PF2e clock drifts from Absalom Reckoning (CAL-13), or a date that does not exist. That failed action is reported to the GM (CLI or Desk) and is not an action log entry, since no delegated action took it; the session starts anyway. The push happens at that gesture only: the Core never writes the clock during play. Without a served Core or a GM client the session still starts and the clock is not pushed.
- **Session interval** (CAL-14): the first and last `clock` dates observed in a live session propose its fictional interval at the wrap: `secondchair wrap` takes it when the GM's notes give none, and asks the GM when the two disagree ([workspace-layout.md](workspace-layout.md#timeyaml)).
