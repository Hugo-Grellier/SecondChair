// The PF2e system adapter (ARC-08, RUL-02, CAN-20, CAN-21, CAL-11..13), on a stand-in Foundry.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  absalomDate,
  createAdapter,
  stripBilingual,
  turnDriver,
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

/** An invented NPC sheet: one strike with its pf2e-labelled variants, one action, one condition. */
function gruk() {
  return {
    name: "Gruk",
    getReach: () => 10,
    system: {
      actions: [
        {
          type: "strike",
          slug: "club",
          label: "Club",
          item: {},
          variants: [{ label: "Strike +9" }, { label: "MAP -5 (+4)" }, { label: "MAP -10 (-1)" }],
        },
        { type: "action", slug: "ignored" },
      ],
    },
    itemTypes: {
      action: [
        {
          slug: "snarl",
          name: "Snarl",
          system: { actionType: { value: "action" }, actions: { value: 2 } },
        },
      ],
      condition: [{ slug: "frightened", name: "Frightened", system: { value: { value: 1 } } }],
    },
  };
}

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
  /** An invented goblin sheet in pf2e's shape, a hidden PC and a visible one around it. */
  const tokens = Object.fromEntries(
    [
      { id: "g", name: "Gruk", x: 0, reaction: true, actor: gruk() },
      { id: "p1", name: "Sella", x: 5 },
      { id: "p2", name: "Ghost", x: 5, hidden: true },
      { id: "p3", name: "Far", x: 30 },
      { id: "n1", name: "Unsaid", x: 60, reaction: null, actor: gruk() },
      { id: "n2", name: "Fresh", x: 90, reaction: false, actor: gruk() },
    ].map((t) => [
      `Scene.s.Token.${t.id}`,
      { documentName: "Token", uuid: `Scene.s.Token.${t.id}`, ...t },
    ]),
  );
  const env = {
    gm: true,
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
    resolve: async (uuid) =>
      /** @type {any} */ (uuid === sella.uuid ? sella : (tokens[uuid] ?? null)),
    sceneTokens: () => Object.values(tokens),
    /** @param {any} a @param {any} b */
    distance: (a, b) => Math.abs(a.x - b.x),
    /** @param {any} token */
    reactionUsed: (token) => token.reaction ?? null,
    isGM: () => env.gm,
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

test("a date outside 1 Pharast 4600 to 28 Calistril 4800 AR, or one that does not exist, is refused", async () => {
  const { env, adapter } = foundry();
  await adapter.ops.set_date("time", { calendar: "absalom", date: "4600-03-01" }, null);
  await adapter.ops.set_date("time", { calendar: "absalom", date: "4800-02-28" }, null);
  const before = env.worldTime;
  for (const date of [
    "4800-02-29",
    "4800-03-01",
    "4801-01-01",
    "10000-01-01",
    "4600-02-29",
    "4600-02-28",
    "4599-12-31",
    "0001-01-01",
    "4725-02-30",
  ]) {
    await assert.rejects(
      adapter.ops.set_date("time", { calendar: "absalom", date }, null),
      /1 Pharast 4600 to 28 Calistril 4800|does not exist on the PF2e world clock/,
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
    turn_driver: null,
  });
});

test("PF2e Combater, when active, is the turn driver", async () => {
  const { env, adapter } = foundry();
  env.modules = () => ({ "pf2-fr": "8.6.0", babele: "2.9.1", "pf2e-combater": "1.4.2" });
  const context = await adapter.reads?.rules_context({}, { language: "fr" });
  assert.equal(/** @type {any} */ (context).turn_driver, "pf2e-combater");
  assert.equal(turnDriver({ "pf2e-combater": "1.4.2" }), "pf2e-combater");
  assert.equal(turnDriver({ "pf2e-toolbelt": "3.0.0" }), null);
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

test("a GM creature's turn card lists what pf2e reports, hides hidden tokens, reads reaction used", async () => {
  const { env, adapter } = foundry();
  const card = /** @type {any} */ (
    await adapter.reads?.turn_card({ token: "Scene.s.Token.g" }, { language: "en" })
  );
  assert.deepEqual(card.strikes, [
    {
      slug: "club",
      label: "Club",
      variants: ["Strike +9", "MAP -5 (+4)", "MAP -10 (-1)"],
      reach: 10,
    },
  ]);
  assert.deepEqual(card.actions, [{ slug: "snarl", name: "Snarl", type: "action", cost: 2 }]);
  assert.deepEqual(card.conditions, [{ slug: "frightened", name: "Frightened", value: 1 }]);
  assert.equal(card.reaction_used, true);
  // the hidden token is not leaked; the far one is out of reach
  assert.deepEqual(
    card.in_reach.map((/** @type {any} */ t) => t.name),
    ["Sella"],
  );
  const gm = /** @type {any} */ (
    await adapter.reads?.turn_card(
      { token: "Scene.s.Token.g", include_hidden: true },
      { language: "en" },
    )
  );
  assert.deepEqual(
    gm.in_reach.map((/** @type {any} */ t) => [t.name, t.hidden]),
    [
      ["Sella", false],
      ["Ghost", true],
    ],
  );
  for (const [id, said] of [
    ["n1", null],
    ["n2", false],
  ]) {
    const other = /** @type {any} */ (
      await adapter.reads?.turn_card({ token: `Scene.s.Token.${id}` }, { language: "en" })
    );
    assert.equal(other.reaction_used, said); // null: no tracker speaks (RUL-07)
  }
  env.gm = false; // a player client never learns of hidden tokens, whatever the caller asks
  const player = /** @type {any} */ (
    await adapter.reads?.turn_card(
      { token: "Scene.s.Token.g", include_hidden: true },
      { language: "en" },
    )
  );
  assert.deepEqual(
    player.in_reach.map((/** @type {any} */ t) => t.name),
    ["Sella"],
  );
  await assert.rejects(
    /** @type {any} */ (adapter.reads).turn_card(
      { token: "Scene.s.Token.none" },
      { language: "en" },
    ),
    /No token/,
  );
});
