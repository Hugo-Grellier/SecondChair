// Durable observation capture (CAP-03, ARC-16; docs/contracts/foundry-bridge.md, "Observations").
import assert from "node:assert/strict";
import { test } from "node:test";
import { createCapture, visibilityOf } from "../secondchair-foundry/scripts/capture.js";
import { validEnvelope, validMessage } from "./schema.js";

/** A browser's storage: it outlives a reload of the page. */
function storage() {
  /** @type {unknown[]} */
  let kept = [];
  return {
    load: () => kept,
    save: (/** @type {unknown[]} */ list) => {
      kept = list;
    },
  };
}

/** The Core's side: records each observation once, acknowledges it, and can be unreachable. */
function core() {
  /** @type {Map<string, object>} */
  const recorded = new Map();
  return {
    recorded,
    /** @param {ReturnType<typeof createCapture>} capture */
    link: (capture) => (/** @type {object} */ message) => {
      assert.ok(validMessage(message), JSON.stringify(validMessage.errors));
      const { envelope } = /** @type {{envelope: {id: string}}} */ (message);
      recorded.set(envelope.id, envelope);
      capture.ack(envelope.id);
    },
  };
}

/** @type {import("../secondchair-foundry/scripts/capture.js").Event} */
const chat = { kind: "chat", visibility: "players", payload: { text: "The bell rings." } };

test("nothing is captured outside a live session", () => {
  const capture = createCapture({ store: storage() });
  assert.equal(capture.observe(chat), null);
  assert.deepEqual(capture.pending(), []);
});

test("an observation is a valid envelope tagged with the session", () => {
  const capture = createCapture({ store: storage() });
  capture.setSession(3);
  const envelope = capture.observe({ ...chat, scene: "Scene.s1", actor: "Actor.a1" });
  assert.ok(validEnvelope(envelope), JSON.stringify(validEnvelope.errors));
  assert.equal(envelope?.session, 3);
});

test("a reload mid-session loses no observation", () => {
  const store = storage();
  const theCore = core();
  const before = createCapture({ store });
  before.setSession(1);
  before.connect(theCore.link(before));
  const sent = before.observe(chat);
  before.disconnect(); // the Core is unreachable for a moment
  const held = before.observe({ ...chat, visibility: "blind" });
  assert.deepEqual(
    before.pending().map((e) => /** @type {{id: string}} */ (e).id),
    [held?.id],
  );

  const after = createCapture({ store }); // the page reloads
  after.connect(theCore.link(after));

  assert.deepEqual([...theCore.recorded.keys()], [sent?.id, held?.id]);
  assert.deepEqual(after.pending(), []);
});

test("only what the whole table saw has players visibility", () => {
  const gm = { isGM: true };
  const player = { isGM: false };
  assert.equal(visibilityOf({ blind: false, whisper: [] }), "players");
  assert.equal(visibilityOf({ blind: true, whisper: [gm] }), "blind");
  assert.equal(visibilityOf({ blind: false, whisper: [gm] }), "gm");
  assert.equal(visibilityOf({ blind: false, whisper: [player, gm] }), "gm");
});
