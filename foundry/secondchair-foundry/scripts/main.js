// secondchair-foundry: the active GM's browser dials the loopback Core (ADR 0010).
import { connect, coreUrl, hello } from "./bridge.js";

const MODULE = "secondchair-foundry";

Hooks.once("init", () => {
  // Client settings live in this browser only: the token never reaches the Foundry server.
  game.settings.register(MODULE, "token", {
    name: "Core token",
    hint: "Printed by `secondchair token` on the computer running the Core. Kept in this browser only.",
    scope: "client",
    config: true,
    type: String,
    default: "",
    requiresReload: true,
  });
  game.settings.register(MODULE, "port", {
    name: "Core port",
    hint: "The port `secondchair serve` listens on, on this computer's loopback (127.0.0.1).",
    scope: "client",
    config: true,
    type: Number,
    default: 7240,
    requiresReload: true,
  });
  // The campaign this world is bound to (ARC-18), set by the Core's first welcome.
  game.settings.register(MODULE, "campaign", {
    scope: "world",
    config: false,
    type: String,
    default: "",
  });
});

Hooks.once("ready", () => {
  // One GM connection at a time (PKG-08): only the active GM dials the Core.
  if (!game.user.isGM || game.users.activeGM?.id !== game.user.id) return;
  const token = String(game.settings.get(MODULE, "token") ?? "");
  if (!token) {
    ui.notifications.warn(
      "SecondChair: run `secondchair token` on the computer running the Core and paste the token into this module's settings.",
    );
    return;
  }
  const url = coreUrl(Number(game.settings.get(MODULE, "port")));
  const campaign = String(game.settings.get(MODULE, "campaign") ?? "");
  // ponytail: no reconnection yet; reload the world to dial again (the bridge grows with #48).
  connect({
    url,
    hello: hello({ token, world: game.world.id, campaign }),
    onWelcome: async (welcome) => {
      if (campaign !== welcome.campaign) {
        await game.settings.set(MODULE, "campaign", welcome.campaign);
      }
      ui.notifications.info("SecondChair: connected to the Core.");
    },
    onRefused: (refusal) =>
      ui.notifications.error(`SecondChair: ${refusal.message}`, { permanent: true }),
    onUnreachable: () =>
      ui.notifications.error(
        `SecondChair: cannot reach the Core at ${url}. Is \`secondchair serve\` running on this computer? If the browser asked whether this site may access local devices, allow it and reload.`,
        { permanent: true },
      ),
  });
});
