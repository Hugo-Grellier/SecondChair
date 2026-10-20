// Outcome traces (RUL-13, RUL-19), from pf2e-shaped chat messages on a stand-in world.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createTracer, iwrOf } from "../secondchair-foundry-pf2e/scripts/outcomes.js";
import { validOutcome } from "./schema.js";

/** A stand-in world: a goblin shaman with a spontaneous entry and focus, and Sella. */
function world() {
  const shaman = {
    uuid: "Actor.shaman",
    focus: 1,
    slots: 3,
    conditions: /** @type {Record<string, number | null>} */ ({}),
  };
  const sella = { uuid: "Actor.sella", hp: { value: 20, temp: 0 } };
  /** @type {Record<string, any>} */
  const actors = { "Actor.shaman": shaman, "Actor.sella": sella };
  /** @type {import("../secondchair-foundry-pf2e/scripts/outcomes.js").Env} */
  const env = {
    actor: (uuid) => actors[uuid] ?? null,
    hp: (actor) => ({ ...actor.hp }),
    resources: (actor) => ({ focus: actor.focus, "entry1.slot1": actor.slots }),
    spent: (_actor, casting, _spell, rank) =>
      casting === "focus-entry"
        ? { kind: "focus", key: "focus" }
        : rank === 0
          ? { kind: "none", key: null }
          : { kind: "slot", key: `entry1.slot${rank}` },
    conditions: (actor) => ({ ...actor.conditions }),
    evidence: () => ({ "pf2e-visioner": { cover: { t2: "standard" } } }),
  };
  return { shaman, sella, tracer: createTracer(env) };
}

/** @param {Record<string, any>} fields */
const message = (fields) => ({
  id: "m1",
  flags: {},
  rolls: [],
  content: "",
  actor: null,
  user: "gm",
  ...fields,
});

test("a check carries its roll breakdown, DC, degrees and adjustments", () => {
  const { shaman, tracer } = world();
  const payload = tracer.message(
    message({
      actor: shaman,
      flags: {
        pf2e: {
          context: {
            type: "skill-check",
            dc: { value: 18 },
            outcome: "success",
            unadjustedOutcome: "success",
            dosAdjustments: {},
            options: ["action:demoralize", "self:trait:goblin"],
            target: { actor: "Actor.sella" },
          },
          modifiers: [
            { label: "Intimidation", modifier: 7, enabled: true },
            { label: "Frightened", modifier: -1, enabled: true, ignored: true },
          ],
        },
        "pf2e-toolbelt": { targetHelper: { type: "check" } },
      },
      rolls: [{ total: 19, dice: [{ faces: 20, total: 12 }] }],
    }),
  );
  assert.ok(validOutcome(payload), JSON.stringify(validOutcome.errors));
  assert.deepEqual(payload?.roll, {
    total: 19,
    natural: 12,
    modifiers: [
      { label: "Intimidation", modifier: 7, enabled: true },
      { label: "Frightened", modifier: -1, enabled: false },
    ],
  });
  assert.equal(payload?.action, "demoralize");
  assert.equal(payload?.target, "Actor.sella");
  assert.deepEqual(Object.keys(payload?.flags ?? {}).sort(), [
    "pf2e",
    "pf2e-toolbelt",
    "pf2e-visioner",
  ]);
});

test("damage taken carries the damage roll, the IWR shown and the HP before and after", () => {
  const { sella, tracer } = world();
  const origin = { uuid: "Actor.shaman.Item.fire" };
  tracer.message(
    message({
      flags: { pf2e: { context: { type: "damage-roll" }, origin } },
      rolls: [{ total: 15, instances: [{ type: "fire", total: 15 }] }],
    }),
  );
  sella.hp.value = 10;
  const applications = JSON.stringify([{ category: "resistance", type: "fire", adjustment: -5 }]);
  const payload = tracer.message(
    message({
      flags: {
        pf2e: {
          context: { type: "damage-taken" },
          origin,
          appliedDamage: {
            uuid: "Actor.sella",
            isHealing: false,
            shield: null,
            updates: [{ path: "system.attributes.hp.value", value: 10 }],
          },
        },
      },
      content: `<span class="iwr" data-applications="${applications.replaceAll('"', "&quot;")}">`,
    }),
  );
  assert.ok(validOutcome(payload), JSON.stringify(validOutcome.errors));
  assert.deepEqual(payload?.damage, { total: 15, instances: [{ type: "fire", total: 15 }] });
  assert.deepEqual(payload?.iwr, [{ category: "resistance", type: "fire", adjustment: -5 }]);
  assert.deepEqual(payload?.hp, { before: { value: 20, temp: 0 }, after: { value: 10, temp: 0 } });
  assert.equal(payload?.actor, "Actor.sella");
});

test("a cast carries what it spent, from the last cast or a rest that restored it", () => {
  const { shaman, tracer } = world();
  const cast = (/** @type {string} */ casting, /** @type {number} */ rank) =>
    tracer.message(
      message({
        actor: shaman,
        flags: {
          pf2e: {
            context: { type: "spell-cast" },
            casting: { id: casting },
            origin: { castRank: rank },
          },
        },
      }),
    )?.resource;
  assert.equal(cast("entry1", 1), undefined); // never seen: no before
  shaman.slots = 2;
  assert.deepEqual(cast("entry1", 1), { kind: "slot", before: 3, after: 2 });
  shaman.focus = 0;
  tracer.raise(shaman); // spent: kept as the next cast's before
  assert.deepEqual(cast("focus-entry", 1), { kind: "focus", before: 1, after: 0 });
  shaman.focus = 1;
  tracer.raise(shaman); // Refocus
  assert.deepEqual(cast("focus-entry", 1), { kind: "focus", before: 1, after: 1 });
  assert.deepEqual(cast("entry1", 0), { kind: "none", before: 0, after: 0 });
});

test("a condition change carries the conditions before, once seen, and after", () => {
  const { shaman, tracer } = world();
  shaman.conditions = { frightened: 2 };
  const first = tracer.conditions(shaman, "gm");
  assert.deepEqual(first.conditions, { after: { frightened: 2 } });
  shaman.conditions = { frightened: 1 };
  const second = tracer.conditions(shaman, "gm");
  assert.ok(validOutcome(second), JSON.stringify(validOutcome.errors));
  assert.deepEqual(second.conditions, { before: { frightened: 2 }, after: { frightened: 1 } });
});

test("a message with no pf2e outcome is no trace, and unreadable IWR is none", () => {
  const { tracer } = world();
  assert.equal(tracer.message(message({})), null);
  assert.deepEqual(iwrOf('<span data-applications="not json">'), []);
  assert.deepEqual(iwrOf("no applications"), []);
});
