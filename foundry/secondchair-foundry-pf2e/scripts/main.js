// secondchair-foundry-pf2e: the PF2e system adapter registers with the library through its hook
// (ARC-08, ADR 0004). It refuses to start outside Foundry v14 + pf2e 8.x (RUL-02).
import { visibilityOf } from "../../secondchair-foundry/scripts/capture.js";
import { absalomDate, createAdapter, RULES_SETTINGS, unsupported } from "./adapter.js";
import { createTracer } from "./outcomes.js";

/** @typedef {import("./adapter.js").Env} Env @typedef {import("./outcomes.js").Doc} Doc */

const MODULE = "secondchair-foundry-pf2e";

/** Third-party modules whose token or combatant flags the trace readers know (RUL-19). */
const TOKEN_FLAGS = ["pf2e-visioner"];
const COMBATANT_FLAGS = ["pf2e-reaction", "pf2e-combater"];

/** @param {string} id */
const active = (id) => game.modules.get(id)?.active === true;

/** A spontaneous or flexible prepared entry spends its slots' value, not a prepared copy. */
const spendsSlots = (/** @type {Doc} */ entry) =>
  entry.system?.prepared?.value === "spontaneous" ||
  (entry.system?.prepared?.value === "prepared" && entry.system?.prepared?.flexible === true);

/** Every countable spell resource of an actor, by key (outcomes.js). @param {Doc} actor */
function resources(actor) {
  /** @type {Record<string, number>} */
  const found = {};
  const focus = actor.system?.resources?.focus?.value;
  if (typeof focus === "number") found.focus = focus;
  for (const entry of actor.itemTypes?.spellcastingEntry ?? []) {
    const mode = spendsSlots(entry) ? "spontaneous" : entry.system?.prepared?.value;
    for (const [slot, data] of Object.entries(entry.system?.slots ?? {})) {
      const s = /** @type {Doc} */ (data);
      if (mode === "spontaneous") found[`${entry.id}.${slot}`] = Number(s.value);
      if (mode !== "prepared") continue;
      for (const copy of s.prepared ?? []) {
        if (!copy?.id) continue;
        const key = `${entry.id}.${slot}.${copy.id}`;
        found[key] = (found[key] ?? 0) + (copy.expended ? 0 : 1);
      }
    }
  }
  for (const spell of actor.itemTypes?.spell ?? []) {
    const uses = spell.system?.location?.uses;
    if (uses?.max && typeof uses.value === "number") found[`${spell.id}.uses`] = uses.value;
  }
  return found;
}

/** @type {import("./outcomes.js").Env} */
const traced = {
  actor: (uuid) => fromUuidSync(uuid, { strict: false }),
  hp: (actor) => ({
    value: Number(actor.system?.attributes?.hp?.value ?? 0),
    temp: Number(actor.system?.attributes?.hp?.temp ?? 0),
  }),
  resources,
  spent(actor, casting, spellUuid, rank) {
    const entry = casting ? actor.items?.get(casting) : null;
    const spell = spellUuid ? fromUuidSync(spellUuid, { strict: false }) : null;
    if (!entry || !spell || spell.isCantrip) return { kind: "none", key: null };
    const mode = entry.system?.prepared?.value;
    if (mode === "focus") return { kind: "focus", key: "focus" };
    if (spendsSlots(entry)) return { kind: "slot", key: `${entry.id}.slot${rank}` };
    if (mode === "prepared") return { kind: "slot", key: `${entry.id}.slot${rank}.${spell.id}` };
    if (mode === "innate" && spell.system?.location?.uses?.max) {
      return { kind: "innate", key: `${spell.id}.uses` };
    }
    return { kind: "none", key: null };
  },
  conditions: (actor) =>
    Object.fromEntries(
      (actor.itemTypes?.condition ?? []).map((/** @type {Doc} */ c) => [c.slug, c.value ?? null]),
    ),
  evidence(actor) {
    /** @type {Record<string, Record<string, unknown>>} */
    const flags = {};
    const token = actor.getActiveTokens?.(false, true)?.[0];
    const combatant = game.combat?.combatants?.find((/** @type {Doc} */ c) => c.actor === actor);
    for (const id of TOKEN_FLAGS) if (active(id) && token?.flags?.[id]) flags[id] = token.flags[id];
    for (const id of COMBATANT_FLAGS) {
      if (active(id) && combatant?.flags?.[id]) flags[id] = combatant.flags[id];
    }
    if (active("sundry")) {
      flags.sundry = {
        effects: (actor.itemTypes?.effect ?? []).map((/** @type {Doc} */ e) => e.slug),
      };
    }
    return flags;
  },
};

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
  resolve: (uuid) =>
    /** @type {Promise<import("../../secondchair-foundry/scripts/actions.js").Doc | null>} */ (
      fromUuid(uuid)
    ),
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
      // Each outcome's trace, in every mode of play (RUL-13): emitted while a live session is open.
      const tracer = createTracer(traced);
      for (const actor of game.actors.contents) tracer.remember(actor);
      Hooks.on("createChatMessage", (/** @type {Doc} */ msg) => {
        const payload = tracer.message({
          id: msg.id,
          flags: msg.flags ?? {},
          rolls: msg.rolls ?? [],
          content: msg.content ?? "",
          actor: msg.actor ?? null,
          user: msg.author?.id ?? null,
        });
        if (!payload) return;
        emit({
          scene: msg.speaker?.scene ? (game.scenes.get(msg.speaker.scene)?.uuid ?? null) : null,
          actor: /** @type {string | null} */ (payload.actor),
          kind: "pf2e.outcome",
          visibility: visibilityOf({ blind: msg.blind, whisper: msg.whisper ?? [] }),
          payload,
        });
      });
      // createItem and deleteItem pass (item, options, userId), updateItem (item, changes, …).
      /** @param {Doc} item @param {unknown[]} rest */
      const condition = (item, ...rest) => {
        if (item.type !== "condition" || !item.actor) return;
        const user = rest.at(-1);
        const payload = tracer.conditions(item.actor, typeof user === "string" ? user : null);
        emit({ actor: item.actor.uuid, kind: "pf2e.outcome", visibility: "gm", payload });
      };
      for (const hook of ["createItem", "updateItem", "deleteItem"]) Hooks.on(hook, condition);
      // A resource grown back (a rest, Refocus) raises what the next cast starts from.
      // ponytail: one lowered by hand keeps the higher before, so a cast that spent nothing
      // after it passes; telling a hand edit from a cast's spending needs the update's origin.
      Hooks.on("updateActor", (/** @type {Doc} */ actor) => tracer.raise(actor));
      Hooks.on("updateItem", (/** @type {Doc} */ item) => item.actor && tracer.raise(item.actor));
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
