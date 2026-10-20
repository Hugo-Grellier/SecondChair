// The monster-turn executor (RUL-03..05, RUL-09, RUL-10), on a stand-in pf2e encounter.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  areaShape,
  createExecutor,
  TRIGGERS,
} from "../secondchair-foundry-pf2e/scripts/executor.js";
import { validOutcome } from "./schema.js";

/**
 * @typedef {{uuid: string, documentName: string, actor: {uuid: string}, pc: boolean, fighting: boolean,
 *   hp: {value: number, temp: number}, conditions: Record<string, number | null>,
 *   resources: Record<string, number>, effects: Record<string, string>}} Token
 */

/**
 * The goblin's spells, by id: the resource key pf2e spends on casting each (outcomes.js).
 * @type {Record<string, {id: string, name: string, free: boolean, variable: boolean, overlays: string[], key: string | null}>}
 */
const SPELLS = {
  fear: {
    id: "fear",
    name: "Fear",
    free: false,
    variable: false,
    overlays: [],
    key: "e1.slot1.fear",
  },
  blast: {
    id: "blast",
    name: "Blast",
    free: false,
    variable: false,
    overlays: [],
    key: "e2.slot3",
  },
  ward: { id: "ward", name: "Ward", free: false, variable: false, overlays: [], key: "focus" },
  daze: { id: "daze", name: "Daze", free: true, variable: false, overlays: [], key: null },
  heal: {
    id: "heal",
    name: "Heal",
    free: false,
    variable: true,
    overlays: ["o1", "o2"],
    key: "focus",
  },
  bless: {
    id: "bless",
    name: "Bless",
    free: false,
    variable: true,
    overlays: [],
    key: "bless.uses",
  },
};

/**
 * A goblin and Sella the PC fighting, a bandit standing outside the encounter. `script` decides
 * what pf2e does on each call; `module` stands for a GM's module acting while the call settles.
 */
function encounter() {
  /** @param {string} id @param {boolean} pc @param {boolean} fighting @returns {Token} */
  const token = (id, pc, fighting) => ({
    uuid: `Scene.s1.Token.${id}`,
    documentName: "Token",
    actor: { uuid: `Actor.${id}` },
    pc,
    fighting,
    hp: { value: 20, temp: 0 },
    conditions: {},
    resources: {},
    effects: {},
  });
  /** @type {Record<string, Token>} */
  const tokens = Object.fromEntries(
    [token("goblin", false, true), token("sella", true, true), token("bandit", false, false)].map(
      (t) => [t.uuid, t],
    ),
  );
  tokens[GOBLIN].resources = { "e1.slot1.fear": 1, "e2.slot3": 2, focus: 1, "bless.uses": 1 };
  /** @type {Record<string, {uuid: string, shape: unknown}>} */
  const regions = {};
  const world = {
    tokens,
    regions,
    round: 1,
    tracker: false,
    /** @type {string[]} */
    calls: [],
    /** @type {Record<string, unknown>[]} */
    emitted: [],
    degree: "success",
    /** @type {((target: Token) => void) | null} */
    module: null,
    /** @type {string | null} the active turn driver's module id */
    driver: null,
  };
  /** @param {unknown} t */
  const as = (t) => /** @type {Token} */ (t);
  const env = {
    resolve: async (/** @type {string} */ uuid) => tokens[uuid] ?? regions[uuid] ?? null,
    pc: (/** @type {unknown} */ t) => as(t).pc,
    inEncounter: (/** @type {unknown} */ t) => as(t).fighting,
    state: (/** @type {unknown} */ t) =>
      structuredClone({
        hp: as(t).hp,
        conditions: as(t).conditions,
        resources: as(t).resources,
        effects: as(t).effects,
      }),
    /** @param {unknown} _t @param {string} slug @param {unknown} target @param {number} map */
    async strike(_t, slug, target, map) {
      world.calls.push(`strike ${slug} map ${map}`);
      if (slug !== "dogslicer") throw new Error(`No strike "${slug}".`);
      const hit = world.degree === "success" || world.degree === "criticalSuccess";
      if (!hit) return { degree: world.degree, damage: null, apply: null };
      const damage = world.degree === "success" ? 6 : 12;
      world.module?.(as(target)); // such as a module applying the damage roll itself
      const apply = async () => {
        world.calls.push(`apply ${damage}`);
        as(target).hp.value -= damage;
      };
      return { degree: world.degree, damage, apply };
    },
    /** @param {unknown} _t @param {string} slug @param {unknown} target */
    async act(_t, slug, target) {
      world.calls.push(`action ${slug}`);
      world.module?.(as(target));
      return { degree: world.degree };
    },
    /** @param {unknown} _t @param {string} save @param {number} dc */
    async rollSave(_t, save, dc) {
      world.calls.push(`roll ${save} ${dc}`);
      return { degree: world.degree };
    },
    /** @param {unknown} t @param {string} save @param {number} dc */
    async requestSave(t, save, dc) {
      world.calls.push(`request ${save} ${dc} from ${as(t).uuid}`);
    },
    /** @param {unknown} t @param {{value: number, temp: number}} hp */
    async setHp(t, hp) {
      as(t).hp = { ...hp };
    },
    /** @param {unknown} t @param {string} slug @param {number | null | undefined} value */
    async setCondition(t, slug, value) {
      world.calls.push(`set ${slug} ${value}`);
      if (value === undefined) delete as(t).conditions[slug];
      else as(t).conditions[slug] = value;
      // pf2e's own rule: losing dying leaves a creature wounded.
      if (slug === "dying" && value === undefined) as(t).conditions.wounded = 1;
    },
    /** @param {unknown} _t @param {string} id */
    async spell(_t, id) {
      const spell = Object.values(SPELLS).find((s) => s.id === id);
      if (!spell) throw new Error(`No spell ${id}.`);
      return spell;
    },
    /** @param {unknown} t @param {string} id @param {number | null} rank @param {string | null} variant */
    async cast(t, id, rank, variant) {
      world.calls.push(`cast ${id} rank ${rank} variant ${variant}`);
      const { key } = SPELLS[id];
      // pf2e spends nothing and posts nothing when nothing is left.
      if (key && as(t).resources[key] > 0) as(t).resources[key] -= 1;
    },
    /** @param {unknown} t @param {string} key @param {number} value */
    async setResource(t, key, value) {
      as(t).resources[key] = value;
    },
    /** @param {unknown} _t @param {string} item */
    async selfEffect(_t, item) {
      if (item !== "raise-a-shield") throw new Error(`No self-effect on ${item}.`);
      return { uuid: "Compendium.pf2e.effects.raise", slug: "effect-raise-a-shield" };
    },
    /** @param {unknown} _t @param {string} item */
    async post(_t, item) {
      world.calls.push(`post ${item}`);
      world.module?.(as(_t));
    },
    /** @param {unknown} t @param {string} uuid */
    async addEffect(t, uuid) {
      world.calls.push(`effect ${uuid}`);
      as(t).effects.e9 = "effect-raise-a-shield";
    },
    /** @param {unknown} t @param {string} id */
    async removeEffect(t, id) {
      delete as(t).effects[id];
    },
    pixelsPerFoot: () => 20,
    /** @param {unknown} _t @param {{shape: unknown}} data */
    async createRegion(_t, data) {
      const uuid = `Scene.s1.Region.r${Object.keys(regions).length + 1}`;
      regions[uuid] = { uuid, shape: data.shape };
      return uuid;
    },
    /** @param {unknown} region */
    async deleteRegion(region) {
      delete regions[/** @type {{uuid: string}} */ (region).uuid];
    },
    reactionRound: () => `c1.${world.round}`,
    /** @param {unknown} _t @param {string} _s @param {unknown} target */
    inReach: (_t, _s, target) => as(target).uuid !== BANDIT,
    reactive: (/** @type {unknown} */ t) => !as(t).pc,
    trackerUsed: () => world.tracker,
    settle: async () => {},
    driver: () => world.driver,
    emit: (/** @type {Record<string, unknown>} */ event) => world.emitted.push(event),
  };
  return { world, ops: createExecutor(env) };
}

const GOBLIN = "Scene.s1.Token.goblin";
const SELLA = "Scene.s1.Token.sella";
const BANDIT = "Scene.s1.Token.bandit";

test("a strike is one system call; its damage lands on a PC and undo restores it", async () => {
  const { world, ops } = encounter();
  const done = await ops.strike(GOBLIN, { strike: "dogslicer", target: SELLA, map: 1 }, null);
  assert.deepEqual(world.calls, ["strike dogslicer map 1", "apply 6"]);
  assert.equal(world.tokens[SELLA].hp.value, 14);
  assert.equal(done.after.degree, "success");
  assert.equal(done.after.damage, 6);
  assert.deepEqual(/** @type {any} */ (done.before).state[SELLA].hp, { value: 20, temp: 0 });

  // The GM's undo: the logged before as params, the logged after as expect.
  await ops.strike(GOBLIN, done.before, done.after);
  assert.equal(world.tokens[SELLA].hp.value, 20);
});

test("undo refuses a creature changed by hand since", async () => {
  const { world, ops } = encounter();
  const done = await ops.strike(GOBLIN, { strike: "dogslicer", target: SELLA, map: 0 }, null);
  world.tokens[SELLA].hp.value = 3;
  await assert.rejects(ops.strike(GOBLIN, done.before, done.after), /changed since/);
  assert.equal(world.tokens[SELLA].hp.value, 3);
});

test("agents never act for a PC, nor outside an encounter", async () => {
  const { world, ops } = encounter();
  const strike = { strike: "dogslicer", target: GOBLIN, map: 0 };
  await assert.rejects(ops.strike(SELLA, strike, null), /player character.*RUL-04/);
  await assert.rejects(ops.strike(BANDIT, strike, null), /encounter.*RUL-03/);
  await assert.rejects(ops.use_action(SELLA, { action: "trip", target: GOBLIN }, null), /RUL-04/);
  await assert.rejects(ops.saving_throw(BANDIT, { save: "will", dc: 18 }, null), /RUL-03/);
  assert.deepEqual(world.calls, []);
});

test("with a turn driver active, every monster-turn action is refused; undo still works", async () => {
  const { world, ops } = encounter();
  const done = await ops.strike(GOBLIN, { strike: "dogslicer", target: SELLA, map: 0 }, null);
  world.calls = [];
  world.driver = "pf2e-combater";
  const refused = /pf2e-combater runs the GM creatures' turns.*DEL-22/;
  await assert.rejects(ops.strike(GOBLIN, { strike: "dogslicer", target: SELLA }, null), refused);
  await assert.rejects(ops.use_action(GOBLIN, { action: "trip", target: SELLA }, null), refused);
  await assert.rejects(ops.saving_throw(GOBLIN, { save: "will", dc: 18 }, null), refused);
  await assert.rejects(ops.saving_throw(SELLA, { save: "will", dc: 18 }, null), refused);
  await assert.rejects(ops.cast_spell(GOBLIN, { spell: "fear" }, null), refused);
  await assert.rejects(ops.self_effect(GOBLIN, { item: "raise-a-shield" }, null), refused);
  const area = { area: "burst", size: 10, x: 0, y: 0, direction: 0, name: "Fire" };
  await assert.rejects(ops.place_area(GOBLIN, area, null), refused);
  // Agent reactions are off too (RUL-12).
  const reactive = { strike: "dogslicer", target: SELLA, trigger: "move" };
  await assert.rejects(ops.reaction(GOBLIN, reactive, null), refused);
  assert.deepEqual(world.calls, []);
  // The GM's undo of an action taken before the driver came on is not a monster-turn action.
  await ops.strike(GOBLIN, done.before, done.after);
  assert.equal(world.tokens[SELLA].hp.value, 20);
});

test("a PC's save is requested from its player, a GM creature's is rolled", async () => {
  const { world, ops } = encounter();
  const asked = await ops.saving_throw(SELLA, { save: "reflex", dc: 20 }, null);
  assert.deepEqual(asked.after, { state: asked.before.state, requested: true, degree: null });
  await ops.saving_throw(GOBLIN, { save: "will", dc: 18 }, null);
  assert.deepEqual(world.calls, [`request reflex 20 from ${SELLA}`, "roll will 18"]);
  await assert.rejects(ops.saving_throw(GOBLIN, { save: "luck", dc: 18 }, null), /fortitude/);
});

test("a system action's follow-up condition is applied once the call settles", async () => {
  const { world, ops } = encounter();
  const done = await ops.use_action(GOBLIN, { action: "demoralize", target: SELLA }, null);
  assert.deepEqual(world.tokens[SELLA].conditions, { frightened: 1 });
  assert.deepEqual(done.after.follow_ups, [
    { token: SELLA, condition: "frightened", value: 1, result: "applied" },
  ]);
  await ops.use_action(GOBLIN, done.before, done.after);
  assert.deepEqual(world.tokens[SELLA].conditions, {});
});

test("a follow-up a module already applied is not applied again", async () => {
  const { world, ops } = encounter();
  world.degree = "criticalSuccess";
  world.module = (target) => {
    target.conditions.frightened = 2;
  };
  const done = await ops.use_action(GOBLIN, { action: "demoralize", target: SELLA }, null);
  assert.ok(!world.calls.some((c) => c.startsWith("set")));
  assert.equal(/** @type {any} */ (done.after.follow_ups)[0].result, "already");
});

test("an ambiguous follow-up is never applied: it is traced for a discrepancy", async () => {
  const { world, ops } = encounter();
  world.degree = "criticalSuccess";
  world.module = (target) => {
    target.conditions.frightened = 1; // a module applied it, but not as the degree says
  };
  const done = await ops.use_action(GOBLIN, { action: "demoralize", target: SELLA }, null);
  assert.ok(!world.calls.some((c) => c.startsWith("set")));
  assert.equal(/** @type {any} */ (done.after.follow_ups)[0].result, "ambiguous");
  const [event] = world.emitted;
  assert.equal(event.kind, "pf2e.outcome");
  assert.ok(validOutcome(event.payload), JSON.stringify(validOutcome.errors));
  assert.deepEqual(/** @type {any} */ (event.payload).follow_up, {
    condition: "frightened",
    value: 2, // frightened was absent before: no `before`
    settled: 1,
    result: "ambiguous",
  });
});

test("an action with no known follow-up, or missed, applies nothing", async () => {
  const { world, ops } = encounter();
  world.degree = "failure";
  const done = await ops.use_action(GOBLIN, { action: "demoralize", target: SELLA }, null);
  assert.deepEqual(done.after.follow_ups, []);
  world.degree = "success";
  await ops.use_action(GOBLIN, { action: "shove", target: SELLA }, null);
  assert.deepEqual(world.tokens[SELLA].conditions, {});
});

test("a system action needs its target: pf2e would fall back to the GM's own targets", async () => {
  const { world, ops } = encounter();
  await assert.rejects(ops.use_action(GOBLIN, { action: "seek" }, null), /target/);
  assert.deepEqual(world.calls, []);
});

test("damage a module already applied from the roll is not applied again", async () => {
  const { world, ops } = encounter();
  world.module = (target) => {
    target.hp.value -= 6;
  };
  const done = await ops.strike(GOBLIN, { strike: "dogslicer", target: SELLA, map: 0 }, null);
  assert.equal(world.tokens[SELLA].hp.value, 14);
  assert.equal(done.after.applied, "already");
  assert.deepEqual(world.calls, ["strike dogslicer map 0"]);
});

test("undo puts conditions back even when pf2e's own rules add one on the way", async () => {
  const { world, ops } = encounter();
  world.module = (target) => {
    target.conditions.dying = 1;
    target.conditions.unconscious = null;
  };
  world.degree = "criticalSuccess";
  const done = await ops.strike(GOBLIN, { strike: "dogslicer", target: SELLA, map: 0 }, null);
  await ops.strike(GOBLIN, done.before, done.after);
  assert.deepEqual(world.tokens[SELLA].conditions, {});
  assert.deepEqual(world.tokens[SELLA].hp, { value: 20, temp: 0 });
});

test("a spell spends its own resource, heightened, and undo gives it back", async () => {
  const { world, ops } = encounter();
  const blast = await ops.cast_spell(GOBLIN, { spell: "blast", rank: 3 }, null);
  assert.deepEqual(blast.after.spent, ["e2.slot3"]);
  await ops.cast_spell(GOBLIN, { spell: "fear" }, null);
  const done = await ops.cast_spell(GOBLIN, { spell: "ward" }, null);
  assert.deepEqual(world.tokens[GOBLIN].resources, {
    "e1.slot1.fear": 0,
    "e2.slot3": 1,
    focus: 0,
    "bless.uses": 1,
  });
  assert.deepEqual(world.calls, [
    "cast blast rank 3 variant null",
    "cast fear rank null variant null",
    "cast ward rank null variant null",
  ]);

  await ops.cast_spell(GOBLIN, done.before, done.after);
  assert.equal(world.tokens[GOBLIN].resources.focus, 1);
  // An earlier cast, the creature changed since: refused.
  await assert.rejects(ops.cast_spell(GOBLIN, blast.before, blast.after), /changed since/);
});

test("a spell with nothing left to spend is refused, a cantrip spends nothing", async () => {
  const { world, ops } = encounter();
  await ops.cast_spell(GOBLIN, { spell: "fear" }, null);
  await assert.rejects(ops.cast_spell(GOBLIN, { spell: "fear" }, null), /no slot, focus/);
  const cantrip = await ops.cast_spell(GOBLIN, { spell: "daze" }, null);
  assert.deepEqual(cantrip.after.spent, []);
  await assert.rejects(ops.cast_spell(GOBLIN, { spell: "blast", rank: 11 }, null), /rank/);
  await assert.rejects(ops.cast_spell(SELLA, { spell: "daze" }, null), /RUL-04/);
  assert.equal(world.calls.length, 3);
});

test("a variant is one of the spell's overlays", async () => {
  const { world, ops } = encounter();
  await assert.rejects(ops.cast_spell(GOBLIN, { spell: "heal", variant: "o7" }, null), /o1, o2/);
  await ops.cast_spell(GOBLIN, { spell: "heal", variant: "o2", rank: 2 }, null);
  assert.deepEqual(world.calls, ["cast heal rank 2 variant o2"]);
});

test("a variable-cost spell without overlay is never cast on an agent's own say", async () => {
  const { world, ops } = encounter();
  await assert.rejects(ops.cast_spell(GOBLIN, { spell: "bless" }, null), /GM resolves.*RUL-08/);
  assert.deepEqual(world.calls, []);
  // Its cost proposed and approved by the GM: cast, the cost recorded.
  const done = await ops.cast_spell(GOBLIN, { spell: "bless", actions: 2 }, null);
  assert.equal(done.after.actions, 2);
  assert.deepEqual(done.after.spent, ["bless.uses"]);
});

test("a self-effect is applied by the adapter once, and undone", async () => {
  const { world, ops } = encounter();
  const done = await ops.self_effect(GOBLIN, { item: "raise-a-shield" }, null);
  assert.deepEqual(world.calls, ["post raise-a-shield", "effect Compendium.pf2e.effects.raise"]);
  assert.deepEqual(world.tokens[GOBLIN].effects, { e9: "effect-raise-a-shield" });
  assert.equal(/** @type {any} */ (done.after.follow_ups)[0].result, "applied");
  await ops.self_effect(GOBLIN, done.before, done.after);
  assert.deepEqual(world.tokens[GOBLIN].effects, {});

  world.module = (t) => {
    t.effects.m1 = "effect-raise-a-shield"; // a module applied it from the chat card
  };
  const again = await ops.self_effect(GOBLIN, { item: "raise-a-shield" }, null);
  assert.equal(/** @type {any} */ (again.after.follow_ups)[0].result, "already");
  assert.deepEqual(world.tokens[GOBLIN].effects, { m1: "effect-raise-a-shield" });
  await assert.rejects(ops.self_effect(GOBLIN, { item: "stride" }, null), /self-effect/);
});

test("an area Region is placed from the agent's origin and undone", async () => {
  const { world, ops } = encounter();
  const params = { area: "burst", size: 20, x: 500, y: 300 };
  const done = await ops.place_area(GOBLIN, params, null);
  const region = String(done.after.region);
  assert.deepEqual(world.regions[region].shape, { type: "circle", x: 500, y: 300, radius: 400 });

  await ops.place_area(GOBLIN, done.before, done.after);
  assert.deepEqual(world.regions, {});
  await assert.rejects(ops.place_area(GOBLIN, done.before, done.after), /changed since/);
  await assert.rejects(ops.place_area(GOBLIN, { ...params, size: 7 }, null), /multiple of 5/);
  await assert.rejects(ops.place_area(GOBLIN, { ...params, area: "ring" }, null), /burst/);
  await assert.rejects(ops.place_area(BANDIT, params, null), /RUL-03/);
});

test("cones and lines point the agent's way, as pf2e draws them", () => {
  assert.deepEqual(areaShape("cone", 15, 0, 0, 90, 20), {
    type: "cone",
    x: 0,
    y: 0,
    radius: 300,
    angle: 90,
    rotation: 90,
  });
  assert.deepEqual(areaShape("line", 30, 0, 0, 45, 20), {
    type: "line",
    x: 0,
    y: 0,
    length: 600,
    width: 100,
    rotation: 45,
  });
});

test("Reactive Strike fires on each listed trigger, once per round", async () => {
  const { world, ops } = encounter();
  for (const trigger of TRIGGERS) {
    const done = await ops.reaction(GOBLIN, { strike: "dogslicer", target: SELLA, trigger }, null);
    assert.equal(done.after.trigger, trigger);
    const again = { strike: "dogslicer", target: SELLA, trigger };
    await assert.rejects(ops.reaction(GOBLIN, again, null), /already used.*RUL-07/);
    world.round += 1;
  }
  // No MAP: always the first attack.
  assert.deepEqual(
    world.calls.filter((c) => c.startsWith("strike")),
    TRIGGERS.map(() => "strike dogslicer map 0"),
  );
});

test("Reactive Strike is refused when a known tracker says the reaction is used", async () => {
  const { world, ops } = encounter();
  world.tracker = true;
  const params = { strike: "dogslicer", target: SELLA, trigger: "move" };
  await assert.rejects(ops.reaction(GOBLIN, params, null), /already used/);
  assert.deepEqual(world.calls, []);
});

test("other reactions and PCs' stay manual; undo frees the reaction", async () => {
  const { world, ops } = encounter();
  const params = { strike: "dogslicer", target: SELLA, trigger: "move" };
  await assert.rejects(ops.reaction(GOBLIN, { ...params, trigger: "cast" }, null), /RUL-08/);
  await assert.rejects(ops.reaction(GOBLIN, { ...params, target: BANDIT }, null), /reach/);
  await assert.rejects(ops.reaction(SELLA, { ...params, target: GOBLIN }, null), /RUL-04/);
  const done = await ops.reaction(GOBLIN, params, null);
  await ops.reaction(GOBLIN, done.before, done.after);
  assert.equal(world.tokens[SELLA].hp.value, 20);
  await ops.reaction(GOBLIN, params, null); // the same round: the undone one is not counted
});

test("an entry logged with HP and conditions only is still undone", async () => {
  const { world, ops } = encounter();
  const done = await ops.strike(GOBLIN, { strike: "dogslicer", target: SELLA, map: 0 }, null);
  /** @param {any} fields */
  const older = (fields) => ({
    ...fields,
    state: Object.fromEntries(
      Object.entries(fields.state).map(([uuid, { hp, conditions }]) => [uuid, { hp, conditions }]),
    ),
  });
  await ops.strike(GOBLIN, older(done.before), older(done.after));
  assert.equal(world.tokens[SELLA].hp.value, 20);
});
