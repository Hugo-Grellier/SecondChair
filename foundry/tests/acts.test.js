// The PF2e adapter's trace events (TRC-02, TRC-03): which act a check or chat card starts.
import assert from "node:assert/strict";
import { test } from "node:test";
import { actOf } from "../secondchair-foundry-pf2e/scripts/acts.js";

const CAST = "origin:action:slug:cast-a-spell";

test("a weapon's attack roll starts a strike, a spell's a spell", () => {
  assert.equal(actOf({ type: "attack-roll", item: "weapon" }), "strike");
  assert.equal(actOf({ type: "attack-roll", item: "melee", options: ["action:strike"] }), "strike");
  assert.equal(actOf({ type: "attack-roll", item: "spell" }), "spell");
});

test("casting a spell starts a spell, sending it to chat does not", () => {
  assert.equal(actOf({ type: "spell-cast", item: "spell", options: [CAST] }), "spell");
  assert.equal(actOf({ item: "spell", options: [CAST] }), "spell");
  assert.equal(actOf({ item: "spell" }), null);
});

test("a system action, an action card or a self-effect starts an action", () => {
  assert.equal(actOf({ type: "skill-check", options: ["action:demoralize"] }), "action");
  assert.equal(actOf({ item: "action" }), "action");
  assert.equal(actOf({ type: "self-effect", item: "feat" }), "action");
});

test("damage, a plain check or a re-roll starts nothing", () => {
  assert.equal(actOf({ type: "damage-roll", item: "weapon", options: ["action:strike"] }), null);
  assert.equal(actOf({ type: "damage-taken" }), null);
  assert.equal(actOf({ type: "saving-throw", options: ["origin:action:slug:fireball"] }), null);
  assert.equal(actOf({ type: "skill-check", options: ["skill:athletics"] }), null);
  assert.equal(actOf({ type: "attack-roll", item: "weapon", reroll: true }), null);
  assert.equal(actOf({}), null);
});
