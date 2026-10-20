// secondchair-foundry: the active GM's browser dials the loopback Core (ADR 0010).
import { CEILING, createActions } from "./actions.js";
import { connect, coreUrl, hello } from "./bridge.js";
import { createCapture, visibilityOf } from "./capture.js";
import { MODULE, realise } from "./scenes.js";

/** @typedef {import("./actions.js").Adapter} Adapter @typedef {import("./actions.js").Doc} Doc */

/** The system adapter, once one registered (ARC-08); without it mechanical actions fail (ARC-09). */
/** @type {Adapter | null} */
let adapter = null;

/** Observations held in this browser until the Core acknowledges them, per world (CAP-03). */
const capture = createCapture({
  store: {
    load: () => {
      try {
        return JSON.parse(localStorage.getItem(`${MODULE}.observations.${game.world.id}`) ?? "[]");
      } catch {
        return [];
      }
    },
    save: (list) =>
      localStorage.setItem(`${MODULE}.observations.${game.world.id}`, JSON.stringify(list)),
  },
});

/** @param {string | null | undefined} id */
const sceneUuid = (id) => (id ? game.scenes.get(id) : game.scenes.active)?.uuid ?? null;
/** @param {string | null | undefined} id */
const actorUuid = (id) => (id ? (game.actors.get(id)?.uuid ?? null) : null);
/** @param {string} html */
const plain = (html) =>
  html
    .replace(/<[^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

/** The generic events captured during a live session; a system adapter adds its own (ARC-16). */
function watch() {
  Hooks.on("createChatMessage", (/** @type {ChatMessageLike} */ msg) => {
    const whisper = msg.whisper.map((id) => game.users.get(id)).filter((u) => u !== undefined);
    capture.observe({
      scene: sceneUuid(msg.speaker?.scene),
      actor: actorUuid(msg.speaker?.actor),
      kind: "chat",
      visibility: visibilityOf({ blind: msg.blind, whisper }),
      payload: {
        author: msg.author?.name ?? null,
        speaker: msg.speaker?.alias ?? null,
        text: plain(msg.content ?? ""),
        flavor: plain(msg.flavor ?? ""),
        whisper: whisper.map((u) => u.name),
        rolls: (msg.rolls ?? []).map((r) => ({ formula: r.formula, total: r.total })),
      },
    });
  });
  // combatRound and combatTurn fire before the change, which their second argument holds.
  /** @param {string} action @returns {(combat: CombatLike, to?: {round?: number, turn?: number}) => void} */
  const combat = (action) => (c, to) => {
    const round = to?.round ?? c.round;
    const turn = to?.turn ?? c.turn;
    const combatant = action === "end" ? null : (c.turns[turn ?? -1] ?? c.combatant);
    capture.observe({
      scene: sceneUuid(c.scene?.id),
      actor: combatant?.actor?.uuid ?? null,
      kind: "combat",
      visibility: combatant?.hidden ? "gm" : "players",
      payload: {
        action,
        combat: c.id,
        round,
        turn,
        combatant: combatant?.name ?? null,
      },
    });
  };
  Hooks.on("combatStart", combat("start"));
  Hooks.on("combatRound", combat("round"));
  Hooks.on("combatTurn", combat("turn"));
  Hooks.on("deleteCombat", combat("end"));
  Hooks.on(
    "updateScene",
    (
      /** @type {{uuid: string, name: string}} */ scene,
      /** @type {{active?: boolean}} */ changes,
    ) => {
      if (changes.active)
        capture.observe({
          scene: scene.uuid,
          actor: null,
          kind: "scene",
          visibility: "players",
          payload: { action: "activate", name: scene.name },
        });
    },
  );
}

/** Whether this client is the one GM client that talks to the Core (PKG-08). */
const isActiveGM = () => game.user.isGM && game.users.activeGM?.id === game.user.id;

/** The ceiling as this client last saw it, to record each change's before. */
let ceiling = CEILING.default;

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
  // The ceiling (DEL-19a): each change is recorded as an observation by the active GM client,
  // which also puts back a change made by a user who is not a GM.
  game.settings.register(MODULE, "ceiling", {
    ...CEILING,
    onChange: (value, _options, userId) => {
      const before = ceiling;
      ceiling = String(value);
      if (!isActiveGM()) return;
      // Recorded in every moment, tagged with the live session when one is open.
      capture.observe({
        kind: "ceiling",
        visibility: "gm",
        payload: { user: userId ?? null, before, after: ceiling },
        anytime: true,
      });
      if (userId && !game.users.get(userId)?.isGM) {
        ui.notifications.warn("SecondChair: only a GM may change the delegation ceiling.");
        // The revert is itself a change, recorded as one.
        game.settings
          .set(MODULE, "ceiling", before)
          .catch((/** @type {unknown} */ error) => console.error("SecondChair:", error));
      }
    },
  });
  // Only a GM changes the ceiling (DEL-19a), even where players were granted world settings.
  // ponytail: refused in the changing client; a tampered client is put back by the active GM.
  /** @param {{key: string}} setting */
  const guard = (setting) => {
    if (setting.key !== `${MODULE}.ceiling` || game.user.isGM) return true;
    ui.notifications.error("SecondChair: only a GM may change the delegation ceiling.");
    return false;
  };
  Hooks.on("preCreateSetting", guard);
  Hooks.on("preUpdateSetting", guard);
});

Hooks.once("ready", () => {
  ceiling = String(game.settings.get(MODULE, "ceiling"));
  // One GM connection at a time (PKG-08): only the active GM dials the Core.
  if (!isActiveGM()) return;
  const token = String(game.settings.get(MODULE, "token") ?? "");
  if (!token) {
    ui.notifications.warn(
      "SecondChair: run `secondchair token` on the computer running the Core and paste the token into this module's settings.",
    );
    return;
  }
  watch();
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
        // Read at each request, so a change applies at once (DEL-19).
        ceiling: () => game.settings.get(MODULE, "ceiling"),
      });
      socket.addEventListener("message", async (event) => {
        try {
          const message = JSON.parse(String(event.data));
          if (message.type === "request")
            socket.send(JSON.stringify(await actions.handle(message)));
          else if (message.type === "session") capture.setSession(message.session);
          else if (message.type === "ack") {
            if (!message.ok) console.error("SecondChair: observation refused:", message.error);
            capture.ack(message.id);
          } else if (message.type === "realise")
            socket.send(JSON.stringify(await realiseScene(message)));
        } catch (error) {
          // A malformed frame or a closed socket: the Core times the request out as failed.
          console.error("SecondChair:", error);
        }
      });
      socket.addEventListener("close", () => capture.disconnect());
      capture.connect((message) => socket.send(JSON.stringify(message)));
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

/** Scenes are realised one at a time. */
/** @type {Promise<unknown>} */
let realising = Promise.resolve();

/** The Foundry calls a realisation makes (scenes.js stays free of Foundry globals). */
/** @type {import("./scenes.js").World} */
const world = {
  findScene: (key) => game.scenes.find((s) => s.flags?.[MODULE]?.scene === key) ?? null,
  createScene: (data) => Scene.create({ navigation: false, ...data }),
  tokenData: async (item) => {
    const actor = await worldActor(/** @type {string} */ (item.actor));
    return (await actor.getTokenDocument(item.data)).toObject();
  },
};

/** A world Actor for a UUID, importing a compendium one once. @param {string} uuid */
async function worldActor(uuid) {
  const source = /** @type {any} */ (await fromUuid(uuid));
  if (!source) throw new Error(`No Actor ${uuid} in this world or its compendiums.`);
  if (!source.pack) return source;
  const imported = game.actors.find((a) => a.flags?.[MODULE]?.source === uuid);
  if (imported) return imported;
  const data = game.actors.fromCompendium(source);
  data.flags = { ...data.flags, [MODULE]: { source: uuid } };
  return Actor.create(data);
}

/**
 * Realise a desired scene the Core sent, and report back (docs/contracts/foundry-bridge.md).
 * Reconciliation is idempotent, so a replayed request only finds nothing to do.
 * @param {{id: string, scene: string, desired: import("./scenes.js").Desired}} request
 */
function realiseScene({ id, scene, desired }) {
  const run = realising.then(async () => {
    try {
      const report = await realise(scene, desired, world);
      const { conflict = 0 } = report.summary;
      if (conflict || report.errors.length) {
        ui.notifications.warn(
          `SecondChair: scene "${desired.scene.name}" realised with ${conflict} conflict(s) and ${report.errors.length} error(s); ask your agent for the report.`,
        );
      }
      return { type: "realised", id, ok: true, report };
    } catch (err) {
      return {
        type: "realised",
        id,
        ok: false,
        error: String(/** @type {Error} */ (err)?.message ?? err),
      };
    }
  });
  realising = run;
  return run;
}
