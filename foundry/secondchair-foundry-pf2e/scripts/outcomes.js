// Outcome traces (RUL-13): the PF2e adapter enriches each outcome it sees, in every mode of play,
// with its trace, a `pf2e.outcome` observation (docs/contracts/pf2e-outcome.schema.json). The
// Python System extension checks each one against its own trace (RUL-14). Free of Foundry
// globals, so it runs under `node --test`; main.js hands it the world through `env`.

/**
 * @typedef {Record<string, any>} Doc  a pf2e document, read loosely
 * @typedef {{value: number, temp: number}} Hp
 * @typedef {{kind: "slot" | "focus" | "innate" | "none", key: string | null}} Spent
 * @typedef {object} Env
 * @property {(uuid: string) => Doc | null} actor  the actor a UUID names
 * @property {(actor: Doc) => Hp} hp
 * @property {(actor: Doc) => Record<string, number>} resources  every countable resource, by key
 * @property {(actor: Doc, casting: string | null, spell: string | null, rank: number | null) => Spent} spent
 *   what a cast spends: its kind and its key in `resources`
 * @property {(actor: Doc) => Record<string, number | null>} conditions  slug -> value
 * @property {(actor: Doc) => Record<string, Record<string, unknown>>} evidence
 *   the trace readers' module flags from the actor's token and combatant (RUL-19)
 * @property {() => string | null} driver  the active turn driver's module id (RUL-11), or null
 */

/** The degree pf2e records on a check message. */
export const DEGREES = ["criticalFailure", "failure", "success", "criticalSuccess"];

/** Message types whose roll is not a check. */
const NOT_CHECKS = ["damage-roll", "damage-taken", "spell-cast", "self-effect"];

/**
 * pf2e's damage-taken message shows the IWR it applied in its content's `data-applications`.
 * @param {string} content
 * @returns {{category: string, type: string, adjustment: number}[]}
 */
export function iwrOf(content) {
  const found = /data-applications="([^"]*)"/.exec(content ?? "");
  if (!found) return [];
  const json = found[1]
    .replaceAll("&quot;", '"')
    .replaceAll("&#x27;", "'")
    .replaceAll("&#39;", "'")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&");
  try {
    const list = JSON.parse(json);
    return Array.isArray(list)
      ? list.map((a) => ({
          category: String(a.category),
          type: String(a.type),
          adjustment: Number(a.adjustment),
        }))
      : [];
  } catch {
    return [];
  }
}

/** @param {Record<string, unknown>} o */
const defined = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined));

/** @param {Env} env */
export function createTracer(env) {
  /** The last damage roll seen, by its origin item's UUID: what damage taken applies. */
  /** @type {Map<string, {total: number, instances: {type: string, total: number}[]}>} */
  const damageRolls = new Map();
  /** Resources as last seen by a cast, raised when they grow back. */
  /** @type {Map<string, Record<string, number>>} */
  const resources = new Map();
  /** Conditions as last seen, by actor UUID. */
  /** @type {Map<string, Record<string, number | null>>} */
  const conditions = new Map();

  /** @param {Doc | null} actor */
  const flagsOf = (actor) => (actor ? env.evidence(actor) : {});

  return {
    /** Start tracking an actor's resources, so its next cast has a before. @param {Doc} actor */
    remember(actor) {
      resources.set(actor.uuid, env.resources(actor));
      conditions.set(actor.uuid, env.conditions(actor));
    },
    /**
     * An actor or one of its items changed: a resource that grew back (a rest, Refocus) raises
     * what the next cast starts from; a spent one stays, as the cast's before.
     * @param {Doc} actor
     */
    raise(actor) {
      const known = resources.get(actor.uuid);
      if (!known) return;
      for (const [key, value] of Object.entries(env.resources(actor))) {
        if (key in known && value > known[key]) known[key] = value;
      }
    },
    /**
     * The outcome a pf2e chat message records, or null when it records none.
     * @param {{id: string, flags: Doc, rolls: Doc[], content: string, actor: Doc | null, user: string | null}} message
     */
    message({ id, flags, rolls, content, actor, user }) {
      const pf2e = flags.pf2e ?? {};
      const context = pf2e.context ?? null;
      const toolbelt = flags["pf2e-toolbelt"];
      if (!context?.type && !toolbelt) return null;
      const type = String(context?.type ?? "message");
      const roll = rolls[0];
      /** @type {Record<string, unknown>} */
      const payload = {
        type,
        message: id,
        user,
        actor: actor?.uuid ?? null,
        target: context?.target?.actor ?? null,
        action:
          (context?.options ?? [])
            .map((/** @type {string} */ o) => /^action:([a-z0-9-]+)$/.exec(o)?.[1])
            .find(Boolean) ?? null,
      };
      /** @type {Record<string, Record<string, unknown>>} */
      const evidence = { ...flagsOf(actor) };
      if (context?.dosAdjustments) evidence.pf2e = { dosAdjustments: context.dosAdjustments };
      if (toolbelt) evidence["pf2e-toolbelt"] = toolbelt;

      if (roll && Array.isArray(pf2e.modifiers) && !NOT_CHECKS.includes(type)) {
        const d20 = (roll.dice ?? []).find((/** @type {Doc} */ d) => d.faces === 20);
        payload.roll = {
          total: roll.total,
          natural: d20 ? d20.total : null,
          modifiers: pf2e.modifiers.map((/** @type {Doc} */ m) => ({
            label: String(m.label),
            modifier: Number(m.modifier),
            enabled: Boolean(m.enabled) && !m.ignored,
          })),
        };
        payload.dc = context.dc?.value ?? null;
        payload.degree = DEGREES.includes(context.outcome) ? context.outcome : null;
        payload.unadjusted = DEGREES.includes(context.unadjustedOutcome)
          ? context.unadjustedOutcome
          : null;
      }
      if (type === "damage-roll" && roll) {
        damageRolls.set(pf2e.origin?.uuid ?? "", {
          total: roll.total,
          instances: (roll.instances ?? []).map((/** @type {Doc} */ i) => ({
            type: String(i.type),
            total: Number(i.total),
          })),
        });
      }
      const applied = pf2e.appliedDamage;
      if (type === "damage-taken" && applied && !applied.isHealing) {
        const hurt = env.actor(applied.uuid);
        if (hurt) {
          payload.actor = hurt.uuid;
          Object.assign(evidence, flagsOf(hurt));
          const after = env.hp(hurt);
          /** @param {string} path */
          const lost = (path) =>
            (applied.updates ?? []).find((/** @type {Doc} */ u) => u.path === path)?.value ?? 0;
          payload.hp = {
            before: {
              value: after.value + lost("system.attributes.hp.value"),
              temp: after.temp + lost("system.attributes.hp.temp"),
            },
            after,
          };
          payload.iwr = iwrOf(content);
          payload.shield = applied.shield?.damage ?? null;
          // ponytail: the last damage roll of the same item; one applied twice, or from
          // another message, is matched wrong: the check then sees an inconsistency.
          const dealt = damageRolls.get(pf2e.origin?.uuid ?? "");
          if (dealt) payload.damage = dealt;
        }
      }
      if (type === "spell-cast" && actor) {
        const { kind, key } = env.spent(
          actor,
          pf2e.casting?.id ?? null,
          pf2e.origin?.uuid ?? null,
          pf2e.origin?.castRank ?? null,
        );
        const now = env.resources(actor);
        const before = key === null ? undefined : resources.get(actor.uuid)?.[key];
        if (kind === "none") payload.resource = { kind, before: 0, after: 0 };
        else if (key !== null && before !== undefined && key in now) {
          payload.resource = { kind, before, after: now[key] };
        }
        resources.set(actor.uuid, now);
      }
      payload.flags = evidence;
      payload.turn_driver = env.driver() ?? undefined;
      return defined(payload);
    },
    /**
     * An actor's conditions changed: its conditions before (when seen before) and after.
     * @param {Doc} actor @param {string | null} user
     */
    conditions(actor, user) {
      const after = env.conditions(actor);
      const before = conditions.get(actor.uuid);
      conditions.set(actor.uuid, after);
      const driver = env.driver();
      return {
        ...(driver && { turn_driver: driver }),
        type: "condition",
        message: null,
        user,
        actor: actor.uuid,
        target: null,
        action: null,
        conditions: before ? { before, after } : { after },
        flags: flagsOf(actor),
      };
    },
  };
}
