# Contract: the Foundry bridge and its handshake

Protocol version: **0.1.0** (`secondchair.core.PROTOCOL_VERSION`). Messages: [`foundry-bridge.schema.json`](foundry-bridge.schema.json), validated by the Python tests and the module's `node --test`. Requirements: ARC-06, ARC-07, ARC-17, ARC-18, PKG-07, PKG-08, PKG-09, PKG-10, PKG-14.

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
{"type": "request", "id": "9f1c…", "op": "move_token", "target": "Scene.s1.Token.t1", "params": {"x": 300, "y": 200}, "expect": null}
{"type": "reply", "id": "9f1c…", "ok": true, "before": {"x": 100, "y": 200}, "after": {"x": 300, "y": 200}}
{"type": "reply", "id": "9f1c…", "ok": false, "error": "Scene.s1.Token.t1 changed since: nothing was done."}
```

- `target` is the Foundry UUID of the document acted on; `params` the fields to set; `before` and `after` the fields the module read before and after, which the Core logs.
- `expect`, when not null, holds the fields the document must still have: an **undo** sends the logged `before` as `params` and the logged `after` as `expect`, so a token the GM moved by hand since is not moved back.
- **Generic operations**, taken by `secondchair-foundry` itself: `move_token` (a Token's `x`, `y`) and `set_door` (a Wall's `ds`: 0 closed, 1 open, 2 locked). Any other `op` is a **mechanical action**, handed to the system adapter that registered it through `game.modules.get("secondchair-foundry").api.registerAdapter({ops: {<op>: async (doc, params, expect) => ({before, after})}})`. With no adapter, the module refuses it (ARC-09).
- **Idempotent write queue** (transplanted from v3, BVE-02): the module records each request id on the GM user before and after taking it, so a replayed id gets its first reply back and is never applied twice, even after a reload; a request a reload interrupted is answered with an error asking the GM to check the VTT. Requests are taken one at a time.
- A **failed action** is one the VTT did not take: no GM client connected, a refusal (`ok: false`), or no reply within 15 seconds. The Core logs it with status `failed` and the error, and the agent gets the error. Nothing is retried.

The GM's approval or undo of a VTT action from the CLI needs the GM client, which only the `serve` process holds: the CLI relays it to `POST /gm` on the served Core ([tool-registration.md](tool-registration.md)).
