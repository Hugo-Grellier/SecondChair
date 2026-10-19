// secondchair-foundry: the active GM's browser dials the loopback Core (ADR 0010).
import { createActions } from "./actions.js";
import { connect, coreUrl, hello } from "./bridge.js";

/** @typedef {import("./actions.js").Adapter} Adapter @typedef {import("./actions.js").Doc} Doc */

const MODULE = "secondchair-foundry";

/** The system adapter, once one registered (ARC-08); without it mechanical actions fail (ARC-09). */
/** @type {Adapter | null} */
let adapter = null;

Hooks.once("init", () => {
  /** @type {{api?: object}} */ (game.modules.get(MODULE)).api = {
    /** @param {Adapter} systemAdapter */
    registerAdapter: (systemAdapter) => {
      adapter = systemAdapter;
    },
  };
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
  // ponytail: no reconnection yet; reload the world to dial again.
  connect({
    url,
    hello: hello({ token, world: game.world.id, campaign }),
    onWelcome: async (welcome, socket) => {
      const actions = createActions({
        resolve: async (uuid) => /** @type {Doc | null} */ (await fromUuid(uuid)),
        // Handled requests live on the GM user, so a reload still knows them (BVE-02).
        store: {
          load: () => /** @type {unknown[]} */ (game.user.getFlag(MODULE, "requests") ?? []),
          save: (list) => game.user.setFlag(MODULE, "requests", list),
        },
        adapter: () => adapter,
      });
      socket.addEventListener("message", async (event) => {
        try {
          const request = JSON.parse(String(event.data));
          if (request.type === "request")
            socket.send(JSON.stringify(await actions.handle(request)));
        } catch (error) {
          // A malformed frame or a closed socket: the Core times the request out as failed.
          console.error("SecondChair:", error);
        }
      });
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
