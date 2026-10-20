// secondchair-foundry-pf2e: the PF2e system adapter registers with the library through its hook
// (ARC-08, ADR 0004). It refuses to start outside Foundry v14 + pf2e 8.x (RUL-02).
import { absalomDate, createAdapter, RULES_SETTINGS, unsupported } from "./adapter.js";

/** @typedef {import("./adapter.js").Env} Env */

const MODULE = "secondchair-foundry-pf2e";

/** The rules settings this world registers, with their values. */
function rulesSettings() {
  return Object.fromEntries(
    RULES_SETTINGS.filter((key) => game.settings.settings.has(key)).map((key) => {
      const [namespace, ...rest] = key.split(".");
      return [key, game.settings.get(namespace, rest.join("."))];
    }),
  );
}

/** @type {Env} */
const env = {
  clock: () => {
    const { year, month, day } = game.pf2e.worldClock.worldTime;
    return { year, month, day };
  },
  advance: (seconds) => game.time.advance(seconds),
  packs: () => game.packs,
  modules: () =>
    Object.fromEntries(
      [...game.modules].filter((m) => m.active).map((m) => [m.id, String(m.version)]),
    ),
  settings: rulesSettings,
  slugify: (name) => game.pf2e.system.sluggify(name),
  versions: () => ({
    foundry: game.version,
    system: game.system.id,
    system_version: game.system.version,
  }),
};

Hooks.once(
  "secondchairFoundryInit",
  /** @param {{registerAdapter(adapter: import("./adapter.js").Adapter): void}} api */ (api) => {
    const refusal = unsupported({
      generation: game.release.generation,
      system: game.system.id,
      systemVersion: game.system.version,
    });
    if (refusal) {
      Hooks.once("ready", () => {
        if (game.user.isGM) ui.notifications.error(`${MODULE}: ${refusal}`, { permanent: true });
      });
      return;
    }
    const adapter = createAdapter(env);
    adapter.observe = (emit) => {
      // Clock advances (CAL-12), as Absalom Reckoning dates, in every moment.
      Hooks.on("updateWorldTime", (/** @type {number} */ worldTime) =>
        emit({
          kind: "clock",
          visibility: "gm",
          payload: { date: absalomDate(env.clock()), world_time: worldTime },
          anytime: true,
        }),
      );
      // A rules setting changed (RUL-22); a module toggled reloads the client, and the Core reads
      // the rules context again when it reconnects.
      Hooks.on("updateSetting", (/** @type {{key: string}} */ setting) => {
        if (!RULES_SETTINGS.includes(setting.key)) return;
        void adapter.reads?.rules_context({}, { language: "" }).then((context) =>
          emit({
            kind: "rules_context",
            visibility: "gm",
            payload: /** @type {Record<string, unknown>} */ (context),
            anytime: true,
          }),
        );
      });
    };
    api.registerAdapter(adapter);
  },
);
