// The monster-turn executor (RUL-03..05, RUL-09, RUL-10), on a stand-in pf2e encounter.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createExecutor } from "../secondchair-foundry-pf2e/scripts/executor.js";
import { validOutcome } from "./schema.js";

/**
 * @typedef {{uuid: string, documentName: string, actor: {uuid: string}, pc: boolean, fighting: boolean,
 *   hp: {value: number, temp: number}, conditions: Record<string, number | null>}} Token
 */

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
  });
  /** @type {Record<string, Token>} */
  const tokens = Object.fromEntries(
    [token("goblin", false, true), token("sella", true, true), token("bandit", false, false)].map(
      (t) => [t.uuid, t],
    ),
  );
  const world = {
    tokens,
    /** @type {string[]} */
    calls: [],
    /** @type {Record<string, unknown>[]} */
    emitted: [],
    degree: "success",
    /** @type {((target: Token) => void) | null} */
    module: null,
  };
  /** @param {unknown} t */
  const as = (t) => /** @type {Token} */ (t);
  const env = {
    resolve: async (/** @type {string} */ uuid) => tokens[uuid] ?? null,
    pc: (/** @type {unknown} */ t) => as(t).pc,
    inEncounter: (/** @type {unknown} */ t) => as(t).fighting,
    state: (/** @type {unknown} */ t) =>
      structuredClone({ hp: as(t).hp, conditions: as(t).conditions }),
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
    settle: async () => {},
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
