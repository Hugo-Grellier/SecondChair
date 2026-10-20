// secondchair-foundry-pf2e: the PF2e system adapter registers with the library through its hook
// (ARC-08, ADR 0004). It refuses to start outside Foundry v14 + pf2e 8.x (RUL-02).
import { visibilityOf } from "../../secondchair-foundry/scripts/capture.js";
import { absalomDate, createAdapter, RULES_SETTINGS, unsupported } from "./adapter.js";
import { createExecutor } from "./executor.js";
import { createTracer, DEGREES } from "./outcomes.js";

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

/** How long the GM's modules get to react to an agent's call before its follow-ups (RUL-10). */
const SETTLE_MS = 1500;

/**
 * A stand-in click that makes pf2e skip its roll dialog whatever the GM's preference: shift
 * inverts it (eventToRollParams), and an agent's call cannot wait on a dialog.
 * @param {"showCheckDialogs" | "showDamageDialogs"} key
 */
const noDialog = (key) => ({ shiftKey: game.user.settings[key], ctrlKey: false, metaKey: false });

/** A token's placeable, which pf2e's roll functions take as their target. @param {Doc} token */
function placeable(token) {
  if (!token.object) throw new Error(`${token.uuid} is not on the scene the GM is viewing.`);
  return token.object;
}

/** One of a token's spells, by id or slug. @param {Doc} token @param {string} key */
function spellOf(token, key) {
  const spell = (token.actor.itemTypes?.spell ?? []).find(
    (/** @type {Doc} */ s) => s.id === key || s.slug === key,
  );
  if (!spell) throw new Error(`${token.actor.name} has no spell "${key}".`);
  return spell;
}

/** One of a token's actions or feats, by slug. @param {Doc} token @param {string} slug */
function abilityOf(token, slug) {
  const { action = [], feat = [] } = token.actor.itemTypes ?? {};
  const item = [...action, ...feat].find((/** @type {Doc} */ i) => i.slug === slug);
  if (!item) throw new Error(`${token.actor.name} has no action or feat "${slug}".`);
  return item;
}

/** The slugs of a token's items of one type. @param {Doc} token @param {string} type @returns {string[]} */
const slugs = (token, type) =>
  (token.actor.itemTypes?.[type] ?? []).map((/** @type {Doc} */ i) => String(i.slug));

/** Reactive Strike, and its pre-remaster name. */
const REACTIVE = ["reactive-strike", "attack-of-opportunity"];

/** Where the executor's observations go, once the library starts capture. */
/** @type {import("./executor.js").Env["emit"]} */
let emitted = () => {};

/** The executor's world (executor.js): pf2e's document methods, never a chat card's button. */
/** @type {import("./executor.js").Env} */
const combat = {
  resolve: (uuid) => fromUuid(uuid),
  pc: (token) => /** @type {Doc} */ (token).actor?.hasPlayerOwner === true,
  inEncounter: (token) =>
    game.combat?.started === true &&
    game.combat.combatants.some((/** @type {Doc} */ c) => c.token?.uuid === token.uuid),
  state: (token) => {
    const actor = /** @type {Doc} */ (token).actor;
    return {
      hp: traced.hp(actor),
      conditions: traced.conditions(actor),
      resources: resources(actor),
      effects: Object.fromEntries(
        (actor.itemTypes?.effect ?? []).map((/** @type {Doc} */ e) => [e.id, e.slug]),
      ),
    };
  },
  async spell(token, key) {
    const spell = spellOf(token, key);
    const time = String(spell.system?.time?.value ?? "").trim();
    return {
      id: spell.id,
      name: spell.name,
      // Nothing counted to spend: a cantrip, at will, or from a wand, staff or scroll.
      free:
        spell.isCantrip === true ||
        spell.atWill === true ||
        traced.spent(
          /** @type {Doc} */ (token).actor,
          spell.spellcasting?.id,
          spell.uuid,
          spell.rank,
        ).kind === "none",
      variable: /^\d+ to \d+$/.test(time),
      overlays: [...(spell.overlays?.keys() ?? [])],
    };
  },
  async cast(token, key, rank, variant) {
    const spell = spellOf(token, key);
    const entry = spell.spellcasting;
    if (!entry) throw new Error(`${spell.name} is in no spellcasting entry.`);
    const castRank = rank ?? spell.rank;
    const cast = variant ? spell.loadVariant({ overlayIds: [variant], castRank }) : spell;
    if (!cast) throw new Error(`pf2e could not load ${spell.name}'s variant "${variant}".`);
    await entry.cast(cast, { rank: castRank });
  },
  // The resource keys of `resources` (outcomes.js): focus, a spontaneous entry's slot, a prepared
  // spell's copies in a slot (how many are left unexpended), an innate spell's uses.
  async setResource(token, key, value) {
    const actor = /** @type {Doc} */ (token).actor;
    const [id, slot, copy] = key.split(".");
    if (key === "focus") return actor.update({ "system.resources.focus.value": value });
    if (slot === "uses")
      return actor.items.get(id)?.update({ "system.location.uses.value": value });
    const entry = actor.items.get(id);
    if (!copy) return entry?.update({ [`system.slots.${slot}.value`]: value });
    let left = value;
    const prepared = (entry?.system?.slots?.[slot]?.prepared ?? []).map((/** @type {Doc} */ c) => {
      if (c?.id !== copy) return c;
      left -= 1;
      return { ...c, expended: left < 0 };
    });
    return entry?.update({ [`system.slots.${slot}.prepared`]: prepared });
  },
  async selfEffect(token, slug) {
    const item = abilityOf(token, slug);
    const uuid = item.system?.selfEffect?.uuid;
    if (!uuid) throw new Error(`${item.name} has no self-effect.`);
    const effect = /** @type {Doc} */ (await fromUuid(uuid));
    if (effect?.type !== "effect") throw new Error(`${item.name}'s self-effect ${uuid} is gone.`);
    return { uuid, slug: effect.slug };
  },
  post: (token, slug) => abilityOf(token, slug).toMessage(),
  // ponytail: a bare copy, without the origin context pf2e's chat card adds; add it when an
  // effect's duration or rule elements need the origin.
  async addEffect(token, uuid) {
    const effect = /** @type {Doc} */ (await fromUuid(uuid));
    return /** @type {Doc} */ (token).actor.createEmbeddedDocuments("Item", [effect.toObject()]);
  },
  removeEffect: (token, id) => /** @type {Doc} */ (token).actor.items.get(id)?.delete(),
  pixelsPerFoot: (token) => {
    const grid = /** @type {Doc} */ (token).parent.grid;
    return grid.size / grid.distance;
  },
  // As pf2e's placeRegionFromItem, at the agent's origin rather than the GM's mouse.
  async createRegion(token, { name, area, shape }) {
    const [region] = await /** @type {Doc} */ (token).parent.createEmbeddedDocuments("Region", [
      {
        name,
        shapes: [shape],
        highlightMode: "coverage",
        displayMeasurements: true,
        visibility: CONST.REGION_VISIBILITY.ALWAYS,
        flags: { pf2e: { areaShape: area } },
      },
    ]);
    if (!region?.uuid) throw new Error("The Region was not created.");
    return String(region.uuid);
  },
  deleteRegion: (region) => /** @type {Doc} */ (region).delete(),
  reactionRound(token) {
    const combat = game.combat;
    const turn = combat?.turns?.findIndex((/** @type {Doc} */ c) => c.token?.uuid === token.uuid);
    const round = Number(combat?.round ?? 0) - (turn > Number(combat?.turn ?? 0) ? 1 : 0);
    return `${combat?.id}.${round}`;
  },
  inReach(token, slug, target) {
    const actor = /** @type {Doc} */ (token).actor;
    const strike = actor.system?.actions?.find((/** @type {Doc} */ s) => s.slug === slug);
    if (!strike) throw new Error(`${actor.name} has no strike "${slug}".`);
    const reach = actor.getReach({ action: "attack", weapon: strike.item });
    return placeable(token).distanceTo(placeable(target)) <= reach;
  },
  reactive: (token) => slugs(token, "action").some((slug) => REACTIVE.includes(slug)),
  // As secondchair_pf2e.readers.reaction_used: any known tracker that says so (RUL-07, RUL-19).
  trackerUsed(token) {
    const combatant = game.combat?.combatants?.find(
      (/** @type {Doc} */ c) => c.token?.uuid === token.uuid,
    );
    const checker = active("pf2e-reaction") ? combatant?.flags?.["pf2e-reaction"] : null;
    const combater = active("pf2e-combater") ? combatant?.flags?.["pf2e-combater"] : null;
    const sundry = active("sundry") && slugs(token, "effect").includes("effect-reaction-used");
    return checker?.state === false || combater?.reactionUsed === true || sundry;
  },
  async strike(token, slug, target, map) {
    const actor = /** @type {Doc} */ (token).actor;
    const strike = actor.system?.actions?.find(
      (/** @type {Doc} */ s) => s.type === "strike" && s.slug === slug,
    );
    if (!strike) throw new Error(`${actor.name} has no strike "${slug}".`);
    const variant = strike.variants?.[map];
    if (!variant) throw new Error(`The strike "${slug}" has no attack ${map + 1}.`);
    const object = placeable(target);
    const roll = await variant.roll({ target: object, event: noDialog("showCheckDialogs") });
    if (!roll) throw new Error(`pf2e did not roll the strike "${slug}".`);
    const degree = DEGREES[roll.degreeOfSuccess] ?? null;
    const missed = { degree, damage: null, apply: null };
    if (degree !== "success" && degree !== "criticalSuccess") return missed;
    const damage = await strike[degree === "success" ? "damage" : "critical"]({
      target: object,
      event: noDialog("showDamageDialogs"),
      mapIncreases: map,
    });
    if (!damage || typeof damage === "string") return missed;
    const victim = /** @type {Doc} */ (target).actor;
    return {
      degree,
      damage: damage.total,
      // What the chat card's button does, on the given target rather than the GM's selection.
      // ponytail: no origin roll options nor ephemeral effects; IWR comes from the roll itself.
      apply: () =>
        victim.applyDamage({
          damage,
          token: target,
          item: strike.item,
          rollOptions: new Set(victim.getSelfRollOptions?.() ?? []),
          outcome: degree,
        }),
    };
  },
  async act(token, slug, target) {
    const action = game.pf2e.actions.get(slug);
    if (!action) throw new Error(`pf2e has no system action "${slug}".`);
    const results = await action.use({
      actors: [/** @type {Doc} */ (token).actor],
      target: placeable(target),
      event: noDialog("showCheckDialogs"),
    });
    const outcome = Array.isArray(results) ? results[0]?.outcome : null;
    return { degree: typeof outcome === "string" ? outcome : null };
  },
  async rollSave(token, save, dc) {
    const statistic = /** @type {Doc} */ (token).actor.saves?.[save];
    if (!statistic) throw new Error(`${token.uuid}'s actor has no ${save} save.`);
    const roll = await statistic.roll({ dc: { value: dc }, event: noDialog("showCheckDialogs") });
    return { degree: DEGREES[roll?.degreeOfSuccess] ?? null };
  },
  // pf2e's inline check: its player clicks it and rolls their own save (RUL-04).
  requestSave: (token, save, dc) =>
    ChatMessage.create({
      speaker: ChatMessage.getSpeaker({ token }),
      content: `<p>@Check[${save}|dc:${dc}]</p>`,
    }),
  setHp: (token, hp) =>
    /** @type {Doc} */ (token).actor.update({
      "system.attributes.hp.value": hp.value,
      "system.attributes.hp.temp": hp.temp,
    }),
  async setCondition(token, slug, value) {
    const actor = /** @type {Doc} */ (token).actor;
    if (value === undefined) return actor.decreaseCondition(slug, { forceRemove: true });
    const existing = actor.getCondition(slug);
    if (!existing) return actor.increaseCondition(slug, value === null ? {} : { value });
    if (value !== null && existing.value !== value) {
      return game.pf2e.ConditionManager.updateConditionValue(existing.id, actor, value);
    }
  },
  settle: () => new Promise((resolve) => setTimeout(resolve, SETTLE_MS)),
  emit: (event) => emitted(event),
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
    adapter.ops = { ...adapter.ops, ...createExecutor(combat) };
    adapter.observe = (emit) => {
      emitted = emit;
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
