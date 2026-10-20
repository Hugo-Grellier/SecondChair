// The PF2e system adapter's logic (ARC-08), free of Foundry globals so it runs under `node --test`;
// main.js hands it the world through `env`.

/** @typedef {import("../../secondchair-foundry/scripts/actions.js").Adapter} Adapter */
/** @typedef {import("../../secondchair-foundry/scripts/actions.js").Fields} Fields */
/** @typedef {{year: number, month: number, day: number}} Ymd */

/**
 * @typedef {object} Pack  a compendium pack
 * @property {string} collection  its id, such as pf2e.pathfinder-bestiary
 * @property {(options: {fields: string[]}) => Promise<Iterable<IndexEntry>>} getIndex
 * @typedef {{_id: string, name: string, system?: {slug?: string | null}, flags?: {babele?: {originalName?: string}}}} IndexEntry
 */

/**
 * @typedef {object} Env  what the adapter reads from and does to the world
 * @property {() => Ymd} clock  the PF2e world clock's Gregorian date
 * @property {(seconds: number) => Promise<unknown>} advance  move the world time
 * @property {() => Iterable<Pack>} packs
 * @property {() => Record<string, string>} modules  active module id -> version
 * @property {() => Record<string, unknown>} settings  the known rules settings -> value
 * @property {() => {foundry: string, system: string, system_version: string}} versions
 * @property {(name: string) => string} slugify  pf2e's slug of an English name
 * @property {(uuid: string) => Promise<import("../../secondchair-foundry/scripts/actions.js").Doc | null>} resolve
 *   the document a UUID names
 */

/** The one Foundry and system major pair the adapter targets (RUL-02). */
export const FOUNDRY_MAJOR = 14;
export const PF2E_MAJOR = 8;

/** Campaign language -> the official translation module it requires (CAN-21, RUL-18). */
export const TRANSLATIONS = { fr: "pf2-fr" };

/**
 * The pf2e world settings the rules context records (RUL-22, RUL-23): variant rules and the
 * system's automation. ponytail: a hand-picked list; add keys as rules checks need them.
 */
export const RULES_SETTINGS = [
  "proficiencyVariant",
  "automaticBonusVariant",
  "freeArchetypeVariant",
  "dualClassVariant",
  "staminaVariant",
  "ancestryParagonVariant",
  "gradualBoostsVariant",
  "mythic",
  "automation.removeExpiredEffects",
  "automation.flankingDetection",
  "automation.rulesBasedVision",
  "automation.encumbrance",
].map((key) => `pf2e.${key}`);

/** Known turn drivers, by module id (RUL-11): a closed list, so a new one is invisible until added. */
export const TURN_DRIVERS = ["pf2e-combater"];

/**
 * The active turn driver's module id, or null (RUL-11).
 * @param {Record<string, string>} modules  active module id -> version
 */
export const turnDriver = (modules) => TURN_DRIVERS.find((id) => id in modules) ?? null;

/**
 * What `set_actor` may set on an actor: the fields a discrepancy's fix touches (RUL-17).
 * ponytail: HP and focus; conditions and spell slots are items, fixed by the GM by hand.
 */
export const ACTOR_FIELDS = [
  "system.attributes.hp.value",
  "system.attributes.hp.temp",
  "system.resources.focus.value",
];

/** @param {Record<string, unknown>} doc @param {string} path */
const field = (doc, path) => path.split(".").reduce((/** @type {any} */ o, k) => o?.[k], doc);

/** The PF2e world clock is Gregorian plus this many years (CONFIG.PF2E.worldClock.AR). */
const YEAR_OFFSET = 2700;

/**
 * The dates the PF2e clock and Absalom Reckoning agree on: Gregorian 1900 and 2100 lack the 29th
 * of Calistril 4600 and 4800 that Paizo's rule keeps, so the clock is a day apart outside them
 * (CAL-13, ADR 0014).
 */
const FIRST_DATE = { year: 4600, month: 3, day: 1 };
const LAST_DATE = { year: 4800, month: 2, day: 28 };

/**
 * Why the adapter must not start here, or null (RUL-02).
 * @param {{generation: number, system: string, systemVersion: string}} found
 */
export function unsupported({ generation, system, systemVersion }) {
  const major = Number(systemVersion.split(".")[0]);
  if (generation === FOUNDRY_MAJOR && system === "pf2e" && major === PF2E_MAJOR) return null;
  return (
    `SecondChair's PF2e adapter targets Foundry v${FOUNDRY_MAJOR} with the pf2e system ` +
    `${PF2E_MAJOR}.x; this world runs Foundry v${generation} with ${system} ${systemVersion}. ` +
    "It stays off: install the versions it targets, or a SecondChair release for these."
  );
}

/**
 * A pf2-fr name without the English original its `vf-vo` display mode appends (CAN-20).
 * @param {string} name
 * @param {string} original
 */
export function stripBilingual(name, original) {
  const suffix = ` (${original})`;
  return name.endsWith(suffix) ? name.slice(0, -suffix.length) : name;
}

/**
 * The world clock's date as an Absalom Reckoning date, `YYYY-MM-DD`.
 * @param {Ymd} gregorian
 */
export function absalomDate({ year, month, day }) {
  const pad = (/** @type {number} */ n, /** @type {number} */ width) =>
    String(n).padStart(width, "0");
  return `${pad(year + YEAR_OFFSET, 4)}-${pad(month, 2)}-${pad(day, 2)}`;
}

/** @param {unknown} value @returns {Ymd | null} */
function parseDate(value) {
  const match = typeof value === "string" ? /^(\d{4,})-(\d{2})-(\d{2})$/.exec(value) : null;
  return match ? { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) } : null;
}

/** @param {Ymd} a @param {Ymd} b */
const after = (a, b) => a.year - b.year || a.month - b.month || a.day - b.day;

/**
 * Days since an epoch for a Gregorian date, null when the date does not exist (Date.UTC would
 * map years 0-99 to 1900-1999, and roll a missing day over to the next month).
 * @param {Ymd} ymd
 */
function dayNumber({ year, month, day }) {
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  if (date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return Math.round(date.getTime() / 86400000);
}

/**
 * @param {Env} env
 * @returns {Adapter}
 */
export function createAdapter(env) {
  /** The PF2e world clock read as Absalom Reckoning. */
  const today = () => ({ date: absalomDate(env.clock()) });

  return {
    translations: TRANSLATIONS,
    ops: {
      /** Set an actor's HP or focus points, such as a discrepancy's fix (RUL-17). */
      async set_actor(target, params, expect) {
        const keys = Object.keys(params);
        if (!keys.length || keys.some((k) => !ACTOR_FIELDS.includes(k))) {
          throw new Error(`set_actor sets ${ACTOR_FIELDS.join(", ")} only.`);
        }
        const actor = await env.resolve(target);
        if (actor?.documentName !== "Actor") throw new Error(`No actor ${target} in this world.`);
        const pick = () => Object.fromEntries(keys.map((k) => [k, field(actor, k)]));
        const before = pick();
        if (expect && Object.entries(expect).some(([k, v]) => before[k] !== v)) {
          throw new Error(`${target} changed since: nothing was done.`);
        }
        await actor.update(params);
        return { before, after: pick() };
      },
      /**
       * Push a campaign date into the world clock, keeping its time of day (CAL-11): a whole
       * number of days, so the hour stays. Refused before 1 Pharast 4600 or after 28 Calistril 4800
       * AR (CAL-13).
       */
      async set_date(_target, params, expect) {
        if (params.calendar !== "absalom") {
          throw new Error(
            `The PF2e adapter syncs only Absalom Reckoning with the world clock, not ${String(params.calendar)}.`,
          );
        }
        const date = parseDate(params.date);
        if (!date) throw new Error(`${String(params.date)} is not a full date, YYYY-MM-DD.`);
        if (after(date, FIRST_DATE) < 0 || after(date, LAST_DATE) > 0) {
          throw new Error(
            `${String(params.date)} is outside 1 Pharast 4600 to 28 Calistril 4800 AR, where the PF2e world clock ` +
              "drifts from Absalom Reckoning: it was not set. Set the world clock by hand.",
          );
        }
        const before = today();
        if (expect && expect.date !== before.date) {
          throw new Error("The world clock changed since: nothing was done.");
        }
        const target = dayNumber({ ...date, year: date.year - YEAR_OFFSET });
        if (target === null) {
          throw new Error(
            `${String(params.date)} does not exist on the PF2e world clock: it was not set. Set ` +
              "the world clock by hand.",
          );
        }
        await env.advance((target - Number(dayNumber(env.clock()))) * 86400);
        return { before, after: today() };
      },
    },
    reads: {
      /** The rules context (RUL-22), with the active turn driver (RUL-11). */
      async rules_context() {
        const modules = env.modules();
        return {
          ...env.versions(),
          modules,
          settings: env.settings(),
          turn_driver: turnDriver(modules),
        };
      },
      /**
       * An official entry's name in the GM's install (CAN-20), by its stable English key (the
       * slug, else the English name). Null when the entry has no translation (CAN-21).
       * ponytail: reads every pack's index on each call; cache it if lookups become frequent.
       */
      async official_name(params, { language }) {
        const key = String(params.key ?? "");
        /** @type {{pack: string, entry: IndexEntry}[]} */
        const found = [];
        for (const pack of env.packs()) {
          const index = await pack.getIndex({
            fields: ["system.slug", "flags.babele.originalName"],
          });
          for (const entry of index) {
            const original = entry.flags?.babele?.originalName ?? entry.name;
            const slug = entry.system?.slug || env.slugify(original);
            if (key === slug || key === original) found.push({ pack: pack.collection, entry });
          }
        }
        const packs = [...new Set(found.map((f) => f.pack))];
        const chosen = params.pack ? found.filter((f) => f.pack === params.pack) : found;
        if (!chosen.length) throw new Error(`No official entry "${key}" in this world's packs.`);
        if (new Set(chosen.map((f) => f.pack)).size > 1) {
          throw new Error(`"${key}" is in several packs (${packs.join(", ")}): give the pack.`);
        }
        const { entry, pack } = chosen[0];
        const original = entry.flags?.babele?.originalName;
        const english = language.toLowerCase().split("-")[0] === "en";
        return {
          name: english
            ? (original ?? entry.name)
            : original
              ? stripBilingual(entry.name, original)
              : null,
          key: entry.system?.slug || env.slugify(original ?? entry.name),
          pack: packs.length > 1 ? pack : null,
        };
      },
    },
  };
}
