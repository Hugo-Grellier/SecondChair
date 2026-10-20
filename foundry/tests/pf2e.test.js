// The PF2e system adapter (ARC-08, RUL-02, CAN-20, CAN-21, CAL-11..13), on a stand-in Foundry.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  absalomDate,
  createAdapter,
  stripBilingual,
  unsupported,
} from "../secondchair-foundry-pf2e/scripts/adapter.js";

test("the adapter starts only on Foundry v14 with pf2e 8.x", () => {
  assert.equal(unsupported({ generation: 14, system: "pf2e", systemVersion: "8.6.1" }), null);
  for (const [generation, system, systemVersion] of /** @type {const} */ ([
    [13, "pf2e", "8.6.1"],
    [15, "pf2e", "8.6.1"],
    [14, "pf2e", "7.12.0"],
    [14, "pf2e", "9.0.0"],
    [14, "dnd5e", "5.0.0"],
  ])) {
    const refusal = unsupported({ generation, system, systemVersion });
    assert.match(
      String(refusal),
      /Foundry v14 with the pf2e system 8\.x/,
      `${system} ${systemVersion}`,
    );
  }
});

test("pf2-fr's bilingual suffix is stripped from a translated name", () => {
  assert.equal(
    stripBilingual("Gobelin guerrier (Goblin Warrior)", "Goblin Warrior"),
    "Gobelin guerrier",
  );
  assert.equal(stripBilingual("Gobelin guerrier", "Goblin Warrior"), "Gobelin guerrier");
  assert.equal(stripBilingual("Épée (longue)", "Longsword"), "Épée (longue)");
});

test("the PF2e world clock reads as Absalom Reckoning, 2700 years after the Gregorian date", () => {
  assert.equal(absalomDate({ year: 2025, month: 3, day: 1 }), "4725-03-01");
  assert.equal(absalomDate({ year: 2100, month: 2, day: 28 }), "4800-02-28");
});

/**
 * A stand-in Foundry around a pf2e world clock on 2025-03-01 at 21:30, with a French install
 * whose bestiary pack holds a goblin warrior, translated by pf2-fr in its vf-vo display mode.
 */
function foundry() {
  const day = 86400;
  const sella = {
    uuid: "Actor.sella",
    documentName: "Actor",
    system: { attributes: { hp: { value: 5, temp: 0 } }, resources: { focus: { value: 1 } } },
    /** @param {Record<string, number>} changes */
    async update(changes) {
      sella.system.attributes.hp.value = changes["system.attributes.hp.value"];
    },
  };
  const env = {
    /** seconds since 2025-03-01T00:00Z */
    worldTime: 21.5 * 3600,
    clock() {
      const date = new Date(Date.UTC(2025, 2, 1) + env.worldTime * 1000);
      return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate() };
    },
    /** @param {number} seconds */
    async advance(seconds) {
      env.worldTime += seconds;
    },
    packs: () => [
      {
        collection: "pf2e.pathfinder-bestiary",
        async getIndex() {
          return [
            {
              _id: "a1",
              name: "Gobelin guerrier (Goblin Warrior)",
              system: { slug: "goblin-warrior" },
              flags: { babele: { originalName: "Goblin Warrior" } },
            },
            { _id: "a2", name: "Untranslated Thing", system: { slug: "untranslated-thing" } },
          ];
        },
      },
      {
        collection: "pf2e.pathfinder-monster-core",
        async getIndex() {
          return [
            {
              _id: "b1",
              name: "Gobelin guerrier (Goblin Warrior)",
              system: { slug: "goblin-warrior" },
              flags: { babele: { originalName: "Goblin Warrior" } },
            },
          ];
        },
      },
    ],
    modules: () => ({ "pf2-fr": "8.6.0", babele: "2.9.1" }),
    settings: () => ({ "pf2e.proficiencyVariant": false }),
    versions: () => ({ foundry: "14.369", system: "pf2e", system_version: "8.6.1" }),
    /** @param {string} name */
    slugify: (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    /** @param {string} uuid */
    resolve: async (uuid) => (uuid === sella.uuid ? sella : null),
  };
  return { env, day, adapter: createAdapter(env) };
}

test("the campaign's date is pushed into the world clock, keeping the time of day", async () => {
  const { env, adapter } = foundry();
  const result = await adapter.ops.set_date(
    "time",
    { calendar: "absalom", date: "4725-05-12" },
    null,
  );
  assert.deepEqual(result, { before: { date: "4725-03-01" }, after: { date: "4725-05-12" } });
  assert.equal(env.worldTime % 86400, 21.5 * 3600);
  await adapter.ops.set_date("time", { calendar: "absalom", date: "4725-02-01" }, null);
  assert.equal(absalomDate(env.clock()), "4725-02-01");
});

test("a date after 28 Calistril 4800 AR, or one the PF2e clock lacks, is refused", async () => {
  const { env, adapter } = foundry();
  await adapter.ops.set_date("time", { calendar: "absalom", date: "4800-02-28" }, null);
  const before = env.worldTime;
  for (const date of ["4800-02-29", "4800-03-01", "4801-01-01", "10000-01-01", "4600-02-29"]) {
    await assert.rejects(
      adapter.ops.set_date("time", { calendar: "absalom", date }, null),
      /28 Calistril 4800|does not exist on the PF2e world clock/,
      date,
    );
  }
  assert.equal(env.worldTime, before);
});

test("a discrepancy's fix sets an actor's HP, checking what it expects", async () => {
  const { adapter } = foundry();
  const hp = "system.attributes.hp.value";
  await assert.rejects(adapter.ops.set_actor("Actor.sella", { hp: 3 }, null), /sets system/);
  await assert.rejects(adapter.ops.set_actor("Actor.nobody", { [hp]: 3 }, null), /No actor/);
  await assert.rejects(adapter.ops.set_actor("Actor.sella", { [hp]: 10 }, { [hp]: 7 }), /changed/);
  const result = await adapter.ops.set_actor("Actor.sella", { [hp]: 10 }, { [hp]: 5 });
  assert.deepEqual(result, { before: { [hp]: 5 }, after: { [hp]: 10 } });
});

test("only Absalom Reckoning is synced", async () => {
  const { adapter } = foundry();
  await assert.rejects(
    adapter.ops.set_date("time", { calendar: "lockwatch", date: "0300-01-01" }, null),
    /Absalom/,
  );
});

test("the rules context lists the system, the active modules and the known rules settings", async () => {
  const { adapter } = foundry();
  assert.deepEqual(await adapter.reads?.rules_context({}, { language: "fr" }), {
    foundry: "14.369",
    system: "pf2e",
    system_version: "8.6.1",
    modules: { "pf2-fr": "8.6.0", babele: "2.9.1" },
    settings: { "pf2e.proficiencyVariant": false },
  });
});

test("an official name is offered translated with its English key, its pack only on a collision", async () => {
  const { adapter } = foundry();
  const read = adapter.reads?.official_name;
  assert.ok(read);
  await assert.rejects(
    read({ key: "goblin-warrior" }, { language: "fr" }),
    /pathfinder-monster-core/,
  );
  assert.deepEqual(
    await read({ key: "goblin-warrior", pack: "pf2e.pathfinder-bestiary" }, { language: "fr" }),
    { name: "Gobelin guerrier", key: "goblin-warrior", pack: "pf2e.pathfinder-bestiary" },
  );
  assert.deepEqual(await read({ key: "Untranslated Thing" }, { language: "fr" }), {
    name: null, // never machine-translated: an agent proposes, or the GM chooses
    key: "untranslated-thing",
    pack: null,
  });
  assert.deepEqual(await read({ key: "untranslated-thing" }, { language: "en" }), {
    name: "Untranslated Thing",
    key: "untranslated-thing",
    pack: null,
  });
  await assert.rejects(read({ key: "nothing-like-it" }, { language: "fr" }), /nothing-like-it/);
});

test("the adapter requires pf2-fr for a French campaign", () => {
  assert.equal(foundry().adapter.translations?.fr, "pf2-fr");
});
