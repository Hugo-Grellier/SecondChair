// SecondChair's own executor for GM creatures' turns (RUL-09): strikes, system actions and saves,
// each one call to pf2e's document methods, never a chat-card button (RUL-05). Agents act only for
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
/** @typedef {{hp: {value: number, temp: number}, conditions: Record<string, number | null>}} State */
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
      if (canonical(env.state(token)) !== canonical(settled[uuid])) {
        throw new Error(`${uuid} changed since: nothing was done.`);
      }
      back.push([token, was[uuid]]);
    }
    for (const [token, before] of back) {
      if (canonical(env.state(token).hp) !== canonical(before.hp)) {
        await env.setHp(token, before.hp);
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

  /** @type {Record<string, (target: string, params: Fields, expect: Fields | null) => Promise<{before: Fields, after: Fields}>>} */
  const ops = {
    /** A GM creature strikes a token: attack, then damage applied on a hit. */
    async strike(target, params, expect) {
      if (expect) return restore(params, expect);
      const creature = await acting(target);
      const victim = await tokenOf(params.target);
      const map = Number(params.map ?? 0);
      if (![0, 1, 2].includes(map)) throw new Error("map is 0, 1 or 2: the attack's MAP step.");
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
