# Contract: the Foundry bridge and its handshake

Protocol version: **0.1.0** (`secondchair.core.PROTOCOL_VERSION`). Messages: [`foundry-bridge.schema.json`](foundry-bridge.schema.json), with observations in [`event-envelope.schema.json`](event-envelope.schema.json), validated by the Python tests and the module's `node --test`. Requirements: ARC-06, ARC-07, ARC-10, ARC-16, ARC-17, ARC-18, CAP-03, CAP-08, BVE-02, PKG-07, PKG-08, PKG-09, PKG-10, PKG-14, TRC-01, TRC-02, TRC-04, TRC-05.

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
- **Generic operations**, taken by `secondchair-foundry` itself: `move_token` (a Token's `x`, `y`) and `set_door` (a Wall's `ds`: 0 closed, 1 open, 2 locked). Any other `op` is a **mechanical action**, handed to the system adapter that registered it through `game.modules.get("secondchair-foundry").api.registerAdapter({ops: {<op>: async (doc, params, expect) => ({before, after})}})`. With no adapter, the module refuses it (ARC-09).
- **Idempotent write queue** (transplanted from v3, BVE-02): the module records each request id on the GM user before and after taking it, so a replayed id gets its first reply back and is never applied twice, even after a reload; a request a reload interrupted is answered with an error asking the GM to check the VTT. Requests are taken one at a time.
- A **failed action** is one the VTT did not take: no GM client connected, a refusal (`ok: false`), or no reply within 15 seconds. The Core logs it with status `failed` and the error, and the agent gets the error. Nothing is retried.

### The ceiling (DEL-19, DEL-19a, DEL-20)

The module enforces its own **ceiling**, whatever the Core asks: one maximum delegation level for every action reaching this world. It is the world setting **Delegation ceiling** of `secondchair-foundry` (`manual`, `propose`, `act-then-review`, `autonomous`), `act-then-review` on a fresh world, so no base profile exceeds it and *autonomous* takes raising it in Foundry on purpose.

- A request whose `level` is above the ceiling, or not a level, is refused before anything is read: `{"type": "reply", "id": …, "ok": false, "error": "Refused by this world's delegation ceiling (propose): …", "reason": "ceiling"}`. A `null` level, the GM's undo, is not bounded. The ceiling is read at each request, so a change applies at once.
- The Core logs the refusal as a failed action and writes a **call** on the GM, `kind: ceiling_refusal`, in `calls/` ([workspace-layout.md](workspace-layout.md)).
- Only a GM user changes it: Foundry keeps world settings to users with the *Modify configuration settings* permission, and the module refuses the change in the client of a user who is not a GM, even when that permission was granted to players. A change by a non-GM user that still lands is put back by the active GM client.
- Each change is an **observation** (below) of kind `ceiling`, visibility `gm`, payload `{"user": <Foundry user id>, "before": …, "after": …}`, captured by the active GM client in every moment: tagged with the live session when one is open, else with `session: null`.

### The Director's Desk (ARC-12, ARC-13, ARC-14)

The **Director's Desk** is a minimal window of `secondchair-foundry`, with no tabs, shown only in the GM client connected to the Core (players' clients never open the bridge, and the module renders nothing and sends no gesture for a user who is not a GM). It opens when the module connects and whenever a call is due now; **Shift+D** (a GM-only keybinding) opens it again. It shows the current moment, the world's ceiling (read-only: it is changed only in the module settings), the calls due now, the break pile once the GM signals a break, the active NPC's **acting cue** (DEL-15: its goal, the line an agent last showed with `show_acting_cue`, what it knows and does not know, with **I voice this one** or, once the GM voices it, **Hand back**; shown at every level, manual included, since it is a read), and the facts and events recorded from the GM's words that await confirmation at the GM-decision rank.

It holds no state (ARC-11): the Core sends the module a **desk** message after `welcome`, whenever the moment, the calls due now, the acting cue or the action log change (it looks every second), and after each gesture. Each button sends a **gesture**, which the Core takes and answers with a **result**:

```json
{"type": "desk", "moment": "live-session", "session": 3, "calls": [{"id": 4, "kind": "proposal", "responsibility": "disclosure", "deadline": "now", "status": "open", "entry": 12, "message": null, "detail": "speak by claude-live on lines/1.md: The bell rings.", "reversible": false}], "decisions": [{"id": "f-1a2b3c4d", "text": "The bell tower fell.", "words": "The bell tower fell in 4710."}], "cue": {"npc": "e-1a2b3c4d", "name": "Tovan Reed", "goal": "Keep the party away from the tower.", "line": "It only rings when the nights are dry.", "knows": [{"id": "f-5e6f7a8b", "statement": "The bell rings on dry nights.", "mode": "knows"}], "does_not_know": [{"id": "f-9c0d1e2f", "statement": "A cracked relay rings the bell."}], "voiced": false}}
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
- **Generic kinds**, captured by `secondchair-foundry`: `chat` (every chat message: author, speaker, text, flavor, whisper recipients' names, rolls' formula and total), `combat` (`start`, `round`, `turn`, `end`, with the combatant), `scene` (`activate`), and `ceiling` (above), the one kind also captured outside a live session. A system adapter's kinds are prefixed by its system id and their payload schemas ship with it.
- **Visibility** (ARC-16): `players` when the whole table saw it; `gm` when it was not shown to the table (GM-only, a whisper even to a player, a hidden combatant's turn); `blind` for a blind roll. Only `players` attests what the party knows: the Core refuses a party knowledge record whose origin quotes a `gm` or `blind` observation (CAP-08: a whisper or a blind roll becomes a call held for the wrap).
- **Durable capture** (transplanted from v3, BVE-02): the module keeps each envelope in the browser's local storage before sending it, and drops it only on its `ack`. Whatever is held (sent before a reload, or captured while the Core was unreachable) is resent on the next welcome. The Core appends each envelope to `observations/<session>.jsonl` in the workspace (`observations/outside-sessions.jsonl` for `session: null`), once per id, before acknowledging it, so a resent envelope is never recorded twice. An envelope the Core cannot take (malformed, or for a session not yet opened) is acknowledged with `ok: false` and an `error`, and the module drops it.

### Prepared scenes (ARC-10, BVE-02)

Prep holds a scene as a **desired state** in the workspace, `scenes/<key>.yaml` ([workspace layout](workspace-layout.md#scenes)), written by the delegated action `prepare_scene` (prep, reversible). Its format is the schema's `desired_scene`: the Scene's Foundry fields (`scene`, `name` required), the objects placed on it (`items`, each `{key, type, data}`, a Token also taking `actor`, the UUID of the world or compendium Actor it is made from), and the GM's `choices`.

While a GM client is connected, the bridge sends it each desired scene it has not realised in this connection, then each one whose file changes (it looks every second), one at a time:

```json
{"type": "realise", "id": "4b7e…", "scene": "goblin-cave", "desired": {"scene": {"name": "Goblin cave"}, "items": [{"key": "boss", "type": "Token", "actor": "Compendium.pf2e.pathfinder-bestiary.Actor.x", "data": {"x": 100, "y": 100, "hidden": true}}]}}
{"type": "realised", "id": "4b7e…", "ok": true, "report": {"scene": "aB3…", "summary": {"create": 2}, "actions": [{"action": "create", "key": "_scene"}, {"action": "create", "key": "boss"}], "errors": []}}
```

With no GM client the desired state waits: every connection starts by sending all of them, which changes nothing in a scene already realised. The Core keeps each scene's last report in `.secondchair/scenes/<key>.json`; the read `scene_report(key)` returns it, with `pending` when the desired state changed since. A compendium Actor is imported into the world once, the first time a token needs it.

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

The **play state** is never compared nor rewritten: a token's position, elevation, rotation, visibility and actor delta, a door's state, a light, sound, tile or drawing's visibility, whether a region's behaviours are disabled. So a token the GM or a player moved stays where it is when prep changes it. A retouch is judged on the fields prep wrote only. The scene itself (`_scene`) is reconciled the same way, never deleted. An object that cannot be written is reported in `errors`; the others are still realised.

### Behaviour traces (TRC-01, TRC-02, TRC-04, TRC-05; ADR 0012)

Behaviour traces record how each consenting user operates Foundry, in every moment. They say nothing about the fiction.

- **Consent** (TRC-01): each user ticks **Record my behaviour traces** in their own module settings. It is off by default and kept in that user's browser, per world and user, so nobody can give it for someone else; the module records nothing and sends nothing until it is on. The user's own client mirrors it in a user flag, `flags.secondchair-foundry.traces`, which the players list shows with a dot; a flag someone else wrote is set back by the user's client. Unticking stops recording at once, unsent records included, and offers to erase every trace already kept: the module sends `erase_traces` for that user, through the active GM's client.
- **Two streams on one clock** (TRC-02): each record carries `t`, milliseconds on the capturing client's clock, and a `stream`. The `semantic` stream holds `event`s: `window.open` and `window.close` (`window`, `app`, `document` UUID or null), `roll` (`formulas`), `target` (`token`, `on`), `move` (`token`), `turn` (`combat`, `round`, `turn`), `focus` and `blur`, plus a system adapter's, prefixed by its system id, sent through `game.modules.get("secondchair-foundry").api.trace(event, data)`. The `input` stream holds `click` (`button`, screen `x`, `y`, `canvas` position or null, `target` element as tag, id, classes and `data-action`, never text), `move` (sampled at the world setting's rate, 10 per second by default, while the window has focus), `wheel` (`dy`), `drag`, `drop` and `key` (`key` and modifiers) outside text fields. In a text field (input, textarea, select, contenteditable) a key press is only `{"input": "type", "del": <Backspace or Delete>}`: the rhythm, never a character.
- **Relay** (TRC-05): each client sends its records about once a second. A player's client sends them on the module's Foundry socket; Foundry reports the sending user, so a player cannot send traces as another, and every client but the active GM's drops them unread. The active GM's client sends the Core one **traces** message per user, its own included. There is no buffer: with no GM client open, or a GM client not connected to the Core, records are dropped and counted, and the next records sent start with a `gap` record (`from`, `to`, `lost`).

```json
{"type": "traces", "user": "aB3dE5fG7hI9jK1l", "name": "Alice", "records": [
  {"t": 1760000090000, "stream": "gap", "from": 1760000000000, "to": 1760000090000, "lost": 42},
  {"t": 1760000091000, "stream": "input", "input": "click", "button": 0, "x": 640, "y": 360, "canvas": {"x": 2100, "y": 1450}, "target": "canvas#board"},
  {"t": 1760000091200, "stream": "input", "input": "type", "del": false}
]}
{"type": "erase_traces", "user": "aB3dE5fG7hI9jK1l"}
```

- **Where they are kept** (TRC-04): the Core appends each record, tagged with the current `moment` and its `seq`, to `$XDG_DATA_HOME/secondchair/traces/<campaign id>/<user id>.jsonl` (default `~/.local/share/secondchair/`), a Source on the GM's machine, outside the workspace, never sent anywhere. Nothing expires them in v4: `erase_traces` deletes a user's file and rewrites the reports that listed their gaps, and the GM may delete any file. Traces are not acknowledged; a message the Core cannot read or keep is lost like one with no GM client.
- **Report**: when a gap arrives, the Core rewrites that moment's friction report in the workspace ([workspace-layout.md](workspace-layout.md#frictions)).
