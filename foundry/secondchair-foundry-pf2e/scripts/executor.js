// SecondChair's own executor for GM creatures' turns (RUL-09): strikes, system actions, saves,
// spells, self-effects, area Regions and Reactive Strike, each one call to pf2e's document methods,
// never a chat-card button (RUL-05, RUL-06, RUL-07). Agents act only for
// GM creatures, in encounters (RUL-03), never for a PC (RUL-04). A follow-up condition is applied
// only if the GM's modules did not apply it while the call settled; an ambiguous one is traced for
// a discrepancy, never applied (RUL-10). Free of Foundry globals, so it runs under `node --test`;
// main.js hands it the world through `env`.
//
// Each op answers {before, after}, `state` holding each token's HP and conditions. The GM's undo
// sends the logged `before` as params and the logged `after` as expect: the op then puts every
// token back, unless one changed since.

import { canonical } from "../../secondchair-foundry/scripts/scenes.js";

/** @typedef {import("../../secondchair-foundry/scripts/actions.js").Fields} Fields */
/**
 * A token's state: HP and conditions, and in the adapter its spell resources (outcomes.js keys)
 * and its effects (id to slug), which an undo puts back too.
 * @typedef {{hp: {value: number, temp: number}, conditions: Record<string, number | null>,
 *   resources?: Record<string, number>, effects?: Record<string, string>}} State
 */
/** @typedef {{uuid: string, actor?: {uuid: string} | null} & Record<string, unknown>} Token */

/**
 * @typedef {object} Env
 * @property {(uuid: string) => Promise<unknown>} resolve  the document a UUID names
 * @property {(token: Token) => boolean} pc  whether a player owns its actor
 * @property {(token: Token) => boolean} inEncounter  a combatant of the started combat
 * @property {(token: Token) => State} state
 * @property {(token: Token, strike: string, target: Token, map: number) => Promise<{degree: string | null, damage: number | null, apply: (() => Promise<unknown>) | null}>} strike
 *   roll the attack and, on a hit, the damage, with how to apply it to the target
 * @property {(token: Token, action: string, target: Token) => Promise<{degree: string | null}>} act
 *   use a system action (`game.pf2e.actions`)
 * @property {(token: Token, save: string, dc: number) => Promise<{degree: string | null}>} rollSave
 * @property {(token: Token, save: string, dc: number) => Promise<unknown>} requestSave
 *   ask the token's player to roll it
 * @property {(token: Token, hp: State["hp"]) => Promise<unknown>} setHp
 * @property {(token: Token, slug: string, value: number | null | undefined) => Promise<unknown>} setCondition
 *   set a condition's value, null for a condition with none, undefined to remove it
 * @property {(token: Token, spell: string) => Promise<{id: string, name: string, free: boolean, variable: boolean, overlays: string[]}>} spell
 *   one of the token's spells, by id or slug: whether casting it spends nothing (a cantrip, at
 *   will), whether its cost is variable ("1 to 3"), and the ids of its overlay variants
 * @property {(token: Token, spell: string, rank: number | null, variant: string | null) => Promise<unknown>} cast
 *   cast it through its spellcasting entry, spending its resource, at `rank` (its own if null)
 * @property {(token: Token, key: string, value: number) => Promise<unknown>} setResource
 * @property {(token: Token, item: string) => Promise<{uuid: string, slug: string}>} selfEffect
 *   the self-effect of one of the token's actions or feats, by slug
 * @property {(token: Token, item: string) => Promise<unknown>} post  post that item to the chat
 * @property {(token: Token, effect: string) => Promise<unknown>} addEffect  an Effect item, by UUID
 * @property {(token: Token, id: string) => Promise<unknown>} removeEffect
 * @property {(token: Token) => number} pixelsPerFoot  on the token's scene
 * @property {(token: Token, data: {name: string, area: string, shape: Record<string, unknown>}) => Promise<string>} createRegion
 *   create an area Region on the token's scene, answering its UUID
 * @property {(region: unknown) => Promise<unknown>} deleteRegion
 * @property {(token: Token) => string} reactionRound  its reaction's round: the combat and the
 *   round its last turn started in, since a creature gets its reaction back on its turn
 * @property {(token: Token) => boolean} reactive  whether it has Reactive Strike
 * @property {(token: Token, strike: string, target: Token) => boolean} inReach  whether the
 *   target is within the reach of that strike
 * @property {(token: Token) => boolean} trackerUsed  whether a known reaction tracker says its
 *   reaction is used this round
 * @property {() => Promise<unknown>} settle  wait for the GM's modules to react to a call
 * @property {(event: import("../../secondchair-foundry/scripts/capture.js").Event) => void} emit
 *   an observation, through the library's durable capture
 */

/**
 * What a system action's degree gives its target, as secondchair_pf2e.checks.ACTIVITIES.
 * ponytail: three actions; add one when a table needs it.
 * @type {Record<string, Record<string, [string, number | null]>>}
 */
export const FOLLOW_UPS = {
  demoralize: { success: ["frightened", 1], criticalSuccess: ["frightened", 2] },
  trip: { success: ["prone", null], criticalSuccess: ["prone", null] },
  grapple: { success: ["grabbed", null], criticalSuccess: ["restrained", null] },
};

const SAVES = ["fortitude", "reflex", "will"];

/** Reactive Strike's triggers within reach, the closed list agents fire it on (RUL-07). */
export const TRIGGERS = ["leaves-reach", "manipulate", "move", "ranged-attack"];

/**
 * An area Region's shape, in scene pixels, as pf2e's own shapeDataFromEffectArea draws it, from
 * the origin (x, y), `direction` in degrees. ponytail: burst, cone and line; emanation (from the
 * creature, not a chosen origin), cube and ring wait for a need.
 * @param {string} area @param {number} feet @param {number} x @param {number} y
 * @param {number} direction @param {number} perFoot
 */
export function areaShape(area, feet, x, y, direction, perFoot) {
  const distance = feet * perFoot;
  if (area === "burst") return { type: "circle", x, y, radius: distance };
  if (area === "cone")
    return { type: "cone", x, y, radius: distance, angle: 90, rotation: direction };
  if (area === "line") {
    return { type: "line", x, y, length: distance, width: 5 * perFoot, rotation: direction };
  }
  throw new Error(`area is burst, cone or line, not "${area}".`);
}

/** @param {Env} env */
export function createExecutor(env) {
  /** @param {unknown} uuid @returns {Promise<Token>} */
  async function tokenOf(uuid) {
    const token = /** @type {Token | null} */ (await env.resolve(String(uuid)));
    if (token?.documentName !== "Token" || !token.actor) {
      throw new Error(`No token with an actor ${uuid} on a scene here.`);
    }
    return token;
  }

  /** @param {Token} token */
  function inEncounter(token) {
    if (!env.inEncounter(token)) {
      throw new Error(
        `${token.uuid} is in no started combat: agents act for GM creatures in encounters ` +
          "only (RUL-03).",
      );
    }
  }

  /** A GM creature in an encounter. @param {string} uuid */
  async function acting(uuid) {
    const token = await tokenOf(uuid);
    if (env.pc(token)) {
      throw new Error(
        `${uuid} is a player character: SecondChair never acts or rolls for a PC, its player ` +
          "does (RUL-04).",
      );
    }
    inEncounter(token);
    return token;
  }

  /** @param {Token[]} tokens @returns {Record<string, State>} */
  const snapshot = (tokens) => Object.fromEntries(tokens.map((t) => [t.uuid, env.state(t)]));

  /** The GM's undo. @param {Fields} params @param {Fields} expect */
  async function restore(params, expect) {
    const was = /** @type {Record<string, State>} */ (params.state);
    const settled = /** @type {Record<string, State>} */ (expect.state);
    const uuids = Object.keys(settled ?? {});
    if (!was || !uuids.length || uuids.some((uuid) => !was[uuid])) {
      throw new Error("No recorded state to put back: nothing was done.");
    }
    /** @type {[Token, State][]} */
    const back = [];
    for (const uuid of uuids) {
      const token = await tokenOf(uuid);
      // Only what was logged: an entry logged before resources and effects were tracked.
      const now = /** @type {Record<string, unknown>} */ (env.state(token));
      const logged = Object.fromEntries(Object.keys(settled[uuid]).map((k) => [k, now[k]]));
      if (canonical(logged) !== canonical(settled[uuid])) {
        throw new Error(`${uuid} changed since: nothing was done.`);
      }
      back.push([token, was[uuid]]);
    }
    for (const [token, before] of back) {
      if (canonical(env.state(token).hp) !== canonical(before.hp)) {
        await env.setHp(token, before.hp);
      }
      for (const [key, value] of Object.entries(before.resources ?? {})) {
        if (env.state(token).resources?.[key] !== value) await env.setResource(token, key, value);
      }
      const had = before.effects;
      for (const id of had ? Object.keys(env.state(token).effects ?? {}) : []) {
        if (had && !Object.hasOwn(had, id)) await env.removeEffect(token, id);
      }
      // Twice: pf2e's own rules can add a condition on the way (losing dying leaves wounded).
      for (let pass = 0; pass < 2; pass++) {
        const now = env.state(token).conditions;
        for (const slug of new Set([...Object.keys(before.conditions), ...Object.keys(now)])) {
          const value = Object.hasOwn(before.conditions, slug)
            ? before.conditions[slug]
            : undefined;
          const current = Object.hasOwn(now, slug) ? now[slug] : undefined;
          if (value !== current) await env.setCondition(token, slug, value);
        }
      }
    }
    return { before: expect, after: params };
  }

  /**
   * Apply the condition `action` at `degree` gives `target`, unless a module did (RUL-10).
   * @param {string} action @param {string | null} degree @param {Token} target @param {State} before
   */
  async function followUp(action, degree, target, before) {
    const [slug, value = null] = (degree && FOLLOW_UPS[action]?.[degree]) || [];
    if (!slug) return [];
    const has = (/** @type {State} */ s) => Object.hasOwn(s.conditions, slug);
    const settled = env.state(target);
    const now = settled.conditions[slug];
    let result = "ambiguous";
    if (has(settled) && (value === null || (now ?? 0) >= value)) result = "already";
    else if (has(settled) === has(before) && now === before.conditions[slug]) {
      await env.setCondition(target, slug, value);
      result = "applied";
    }
    env.emit({
      actor: target.actor?.uuid ?? null,
      kind: "pf2e.outcome",
      visibility: "gm",
      anytime: true,
      payload: {
        type: "follow-up",
        message: null,
        user: null,
        actor: target.actor?.uuid ?? null,
        target: null,
        action,
        degree,
        flags: {},
        follow_up: {
          condition: slug,
          value,
          ...(has(before) && { before: before.conditions[slug] }),
          ...(has(settled) && { settled: now }),
          result,
        },
      },
    });
    return [{ token: target.uuid, condition: slug, value, result }];
  }

  /**
   * `creature` strikes the token `params.target` names at MAP step `map`: attack, then damage
   * applied on a hit unless a module did (RUL-10).
   * @param {Token} creature @param {Fields} params @param {number} map
   */
  async function hit(creature, params, map) {
    const victim = await tokenOf(params.target);
    const before = snapshot([creature, victim]);
    const struck = await env.strike(creature, String(params.strike), victim, map);
    /** Whether the executor applied the damage, or found a module had (RUL-10). */
    let applied = null;
    if (struck.apply) {
      await env.settle();
      const hp = canonical(env.state(victim).hp) === canonical(before[victim.uuid].hp);
      if (hp) await struck.apply();
      applied = hp ? "applied" : "already";
    }
    const { degree, damage } = struck;
    return {
      before: { state: before },
      after: { state: snapshot([creature, victim]), degree, damage, applied },
    };
  }

  /** The adapter's reaction counter: the round each GM creature last reacted in (RUL-07). */
  /** @type {Map<string, string>} */
  const reacted = new Map();

  /** @type {Record<string, (target: string, params: Fields, expect: Fields | null) => Promise<{before: Fields, after: Fields}>>} */
  const ops = {
    /** A GM creature strikes a token: attack, then damage applied on a hit. */
    async strike(target, params, expect) {
      if (expect) return restore(params, expect);
      const creature = await acting(target);
      const map = Number(params.map ?? 0);
      if (![0, 1, 2].includes(map)) throw new Error("map is 0, 1 or 2: the attack's MAP step.");
      return hit(creature, params, map);
    },
    /**
     * Reactive Strike on a listed trigger, once per round: refused when the adapter's counter or
     * any known reaction tracker says the creature's reaction is used. Free of MAP. The undo frees
     * the reaction again. ponytail: the counter lives in the GM client; a reload forgets it, and
     * the trackers still speak.
     */
    async reaction(target, params, expect) {
      if (expect) {
        const done = await restore(params, expect);
        if (reacted.get(target) === expect.round) reacted.delete(target);
        return done;
      }
      const creature = await acting(target);
      const trigger = String(params.trigger);
      if (!TRIGGERS.includes(trigger)) {
        throw new Error(
          `Agents fire Reactive Strike on ${TRIGGERS.join(", ")} only; every other reaction is ` +
            "the GM's (RUL-07, RUL-08).",
        );
      }
      if (!env.reactive(creature)) throw new Error(`${target} has no Reactive Strike.`);
      const victim = await tokenOf(params.target);
      if (!env.inReach(creature, String(params.strike), victim)) {
        throw new Error(`${params.target} is not within the reach of ${params.strike} (RUL-07).`);
      }
      const round = env.reactionRound(creature);
      if (reacted.get(target) === round || env.trackerUsed(creature)) {
        throw new Error(`${target} already used its reaction this round (RUL-07).`);
      }
      const done = await hit(creature, params, 0);
      reacted.set(target, round);
      return { before: done.before, after: { ...done.after, trigger, round } };
    },
    /**
     * A GM creature casts one of its spells, spending its slot, focus point or innate use, at
     * `rank` (heightened) and as the overlay `variant`. A variable-cost spell with no overlay is
     * the GM's: an agent only proposes its cost (`actions`), cast once the GM approves (RUL-08).
     */
    async cast_spell(target, params, expect) {
      if (expect) return restore(params, expect);
      const creature = await acting(target);
      const rank = params.rank == null ? null : Number(params.rank);
      if (rank !== null && !(Number.isInteger(rank) && rank >= 1 && rank <= 10)) {
        throw new Error("rank is a whole number from 1 to 10.");
      }
      const variant = params.variant == null ? null : String(params.variant);
      const spell = await env.spell(creature, String(params.spell));
      if (variant !== null && !spell.overlays.includes(variant)) {
        const known = spell.overlays.join(", ") || "none";
        throw new Error(`${spell.name} has no variant "${variant}"; its variants: ${known}.`);
      }
      const actions = params.actions == null ? null : Number(params.actions);
      if (spell.variable && !spell.overlays.length && actions === null) {
        throw new Error(
          `${spell.name} has a variable cost and no overlay: an agent proposes its cost ` +
            "(actions) and the GM resolves it (RUL-08).",
        );
      }
      const before = snapshot([creature]);
      await env.cast(creature, spell.id, rank, variant);
      const after = snapshot([creature]);
      const was = before[creature.uuid].resources ?? {};
      const now = after[creature.uuid].resources ?? {};
      const spent = Object.keys(was).filter((key) => (now[key] ?? 0) < was[key]);
      if (!spell.free && !spent.length) {
        throw new Error(`${spell.name} was not cast: pf2e found no slot, focus point or use left.`);
      }
      return { before: { state: before }, after: { state: after, spent, actions } };
    },
    /**
     * A GM creature uses one of its actions or feats that has a self-effect: the item goes to the
     * chat, then the adapter applies the effect itself, unless a module already did (RUL-06,
     * RUL-10).
     */
    async self_effect(target, params, expect) {
      if (expect) return restore(params, expect);
      const creature = await acting(target);
      const item = String(params.item);
      const effect = await env.selfEffect(creature, item);
      const before = snapshot([creature]);
      await env.post(creature, item);
      await env.settle();
      const has = Object.values(env.state(creature).effects ?? {}).includes(effect.slug);
      if (!has) await env.addEffect(creature, effect.uuid);
      const follow_ups = [
        { token: creature.uuid, effect: effect.slug, result: has ? "already" : "applied" },
      ];
      return { before: { state: before }, after: { state: snapshot([creature]), follow_ups } };
    },
    /**
     * A GM creature places an area Region on its scene from an origin the agent chose (RUL-06).
     * The undo deletes it, refused when it is gone already.
     */
    async place_area(target, params, expect) {
      if (expect) {
        const region = await env.resolve(String(expect.region));
        if (!region) throw new Error(`${expect.region} changed since: nothing was done.`);
        await env.deleteRegion(region);
        return { before: expect, after: params };
      }
      const creature = await acting(target);
      const [feet, x, y, direction] = [params.size, params.x, params.y, params.direction ?? 0].map(
        Number,
      );
      if (!(feet > 0 && feet % 5 === 0)) throw new Error("size is a positive multiple of 5 feet.");
      if (![x, y, direction].every(Number.isFinite)) {
        throw new Error("x and y are the origin's scene pixels; direction is in degrees.");
      }
      const area = String(params.area);
      const shape = areaShape(area, feet, x, y, direction, env.pixelsPerFoot(creature));
      const name = String(params.name ?? `${area} ${feet} ft`);
      const region = await env.createRegion(creature, { name, area, shape });
      return { before: { region: null }, after: { region, area, shape } };
    },
    /**
     * A GM creature uses a system action against a token. ponytail: a target is required, since
     * pf2e falls back to the GM's own targets without one; actions without one wait for a need.
     */
    async use_action(target, params, expect) {
      if (expect) return restore(params, expect);
      if (!params.target) throw new Error("use_action needs the target token of the action.");
      const creature = await acting(target);
      const victim = await tokenOf(params.target);
      const before = snapshot([creature, victim]);
      const action = String(params.action);
      const { degree } = await env.act(creature, action, victim);
      await env.settle();
      const follow_ups = await followUp(action, degree, victim, before[victim.uuid]);
      const after = { state: snapshot([creature, victim]), degree, follow_ups };
      return { before: { state: before }, after };
    },
    /** A save: a GM creature's is rolled, a PC's is asked of its player (RUL-04). */
    async saving_throw(target, params, expect) {
      if (expect) return restore(params, expect);
      const token = await tokenOf(target);
      inEncounter(token);
      const save = String(params.save);
      const dc = Number(params.dc);
      if (!SAVES.includes(save)) throw new Error(`save is one of ${SAVES.join(", ")}.`);
      if (!Number.isInteger(dc)) throw new Error("dc must be a whole number.");
      const state = snapshot([token]);
      if (env.pc(token)) {
        await env.requestSave(token, save, dc);
        return { before: { state }, after: { state, requested: true, degree: null } };
      }
      const { degree } = await env.rollSave(token, save, dc);
      return {
        before: { state },
        after: { state: snapshot([token]), requested: false, degree },
      };
    },
  };
  return ops;
}
