# SecondChair Foundry modules

`secondchair-foundry` connects a Foundry VTT v14 world to SecondChair. The Core runs on the GM's own computer (`secondchair serve`); the module, in the GM's browser, opens a WebSocket to it on `127.0.0.1`. Foundry itself never needs to reach the Core, so a remotely hosted Foundry (The Forge, a homelab) works the same as a local one.

## Install

1. On the computer you play from, install SecondChair and serve your campaign (see the [repository README](../README.md)).
2. Run `secondchair token` and copy the token it prints. It is created once and kept in `~/.config/secondchair/foundry-token`, readable only by you.
3. In Foundry's setup screen, **Install Module** and paste the manifest URL:
   `https://raw.githubusercontent.com/Hugo-Grellier/SecondChair/main/foundry/secondchair-foundry/module.json`
4. Enable the module in your world. As GM, open **Configure Settings → SecondChair**, paste the token into **Core token**, and set **Core port** if you changed it from 7240. Both settings stay in this browser only.
5. Reload. A notification says "connected to the Core", or why the Core refused.
6. For a Pathfinder Second Edition world, also install **SecondChair for Pathfinder Second Edition** from its manifest URL,
   `https://raw.githubusercontent.com/Hugo-Grellier/SecondChair/main/foundry/secondchair-foundry-pf2e/module.json`,
   and enable it. It targets Foundry v14 with the pf2e system 8.x and stays off on any other pair. A French campaign also needs the official translation module **pf2-fr** enabled: without it SecondChair refuses to connect and says so.

**Your browser may ask once before connecting.** Firefox, and recent Chrome versions, ask for each site whether it may connect to services on your own computer (the "local network" or "apps and services on this device" prompt). Allow it for your Foundry site. While the prompt waits for an answer, the module cannot connect; after a few seconds it shows a notice pointing to the prompt. If you refused it, the module reports that it cannot reach the Core: allow the site in the browser's site permissions, then click **Retry** on the Director's Desk (reload if it still cannot connect).

**Delegation ceiling.** In the same settings, the GM sets the most any SecondChair agent may do in this world, whatever the campaign's delegation table says. It starts at *act then review*; an action above it is refused and becomes a call for you. Only a GM can change it, and each change is recorded.

**Director's Desk.** Once connected, the GM gets a small window: the calls due now, to approve or reject with a reason; **Break**, which shows what was held for the break; **Start session** and **End session**; the decisions taken from your words that await your confirmation; and the ceiling, shown read-only. It opens on connection and whenever a call is due now; **Shift+D** opens it again. Players never see it. When it is not connected, the Desk says why (the Core is not reachable, the Core refused the connection and its message, or the connection closed) and offers one button, **Retry** or **Reconnect**, which dials the Core again without reloading the world; nothing redials on its own.

Only the active GM connects, and only one GM client at a time. The first connection binds the world to the campaign; another campaign's world is refused ([contract](../docs/contracts/foundry-bridge.md)).

## Licence and Foundry package policy

The modules are Apache-2.0 (`LICENSE` in each module's folder; [ADR 0006](../docs/adr/0006-agpl-core-apache-connector-cla.md)). They are self-distributed but kept compliant with the official package listing (LIC-16): the listing category is **AI Tools**, they ship no AI-made prepared content, the author attests to the listing's AI policy, and they never send third-party content (other modules, purchased assets) to a model on their own.

## Development

From the repository root: `npm ci`, then `npm run check` runs Biome (lint and format), `tsc` with `checkJs`, and `node --test`, as CI and pre-commit do.
