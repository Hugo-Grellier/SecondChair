// Behaviour traces (TRC-01, TRC-02, TRC-05; docs/contracts/foundry-bridge.md, "Behaviour traces").
import assert from "node:assert/strict";
import { test } from "node:test";
import { createOutbox, createRecorder, keyInput } from "../secondchair-foundry/scripts/traces.js";
import { validMessage } from "./schema.js";

/** A clock that ticks one second per reading. */
function clock() {
  let t = 1_760_000_000_000;
  return () => (t += 1000);
}

/** A client: a recorder flushing into an outbox, with what reached the network. */
function client({ consent = false, ready = true } = {}) {
  /** @type {{user: string, records: object[]}[]} */
  const sent = [];
  const state = { consent, ready };
  const outbox = createOutbox({
    ready: () => state.ready,
    send: (user, records) => {
      const message = { type: "traces", user, name: "Alice", records };
      assert.ok(validMessage(message), JSON.stringify(validMessage.errors));
      sent.push({ user, records });
    },
  });
  const recorder = createRecorder({
    consented: () => state.consent,
    flush: (records) => outbox.push("alice0000000001", records),
    now: clock(),
  });
  return { sent, state, recorder, outbox };
}

/** @param {any} el */
const field = (el) => ({ closest: (/** @type {string} */ sel) => (el && sel ? el : null) });
const canvas = { closest: () => null, isContentEditable: false };

test("before consent, the client emits nothing", () => {
  const { sent, recorder } = client();
  recorder.record("input", { input: "click", button: 0 });
  recorder.record("semantic", { event: "window.open" });
  recorder.flush();
  recorder.flush();
  assert.deepEqual(sent, []);
});

test("once consented, both streams leave on one clock, in order", () => {
  const { sent, state, recorder } = client();
  state.consent = true;
  recorder.record("semantic", { event: "window.open", app: "ActorSheet" });
  recorder.record("input", { input: "click", button: 0 });
  recorder.flush();
  const [{ records }] = sent;
  assert.deepEqual(
    records.map((r) => /** @type {{stream: string}} */ (r).stream),
    ["semantic", "input"],
  );
  const [a, b] = /** @type {{t: number}[]} */ (records);
  assert.ok(a.t < b.t);
});

test("what SecondChair does through this client is tagged as its own, never the user's", () => {
  /** @type {object[]} */
  let flushed = [];
  let acting = false;
  const recorder = createRecorder({
    consented: () => true,
    flush: (records) => {
      flushed = records;
    },
    acting: () => acting,
  });
  recorder.record("semantic", { event: "move", token: "Scene.s.Token.t" });
  acting = true;
  recorder.record("semantic", { event: "move", token: "Scene.s.Token.t" });
  recorder.record("input", { input: "click", button: 0 });
  recorder.flush();
  assert.deepEqual(
    flushed.map((r) => /** @type {{by?: string}} */ (r).by),
    [undefined, "secondchair", undefined],
  );
  const message = { type: "traces", user: "gm", name: "GM", gm: true, records: flushed };
  assert.ok(validMessage(message), JSON.stringify(validMessage.errors));
});

test("revoking stops capture, even of what was waiting to be sent", () => {
  const { sent, state, recorder } = client({ consent: true });
  recorder.record("input", { input: "click", button: 0 });
  state.consent = false;
  recorder.flush();
  recorder.record("input", { input: "click", button: 0 });
  recorder.flush();
  assert.deepEqual(sent, []);
});

test("typing in a text field records rhythm only, never a character", () => {
  const typed = [..."Secret plan", "Backspace"].map((key) =>
    keyInput({
      key,
      ctrlKey: false,
      shiftKey: false,
      altKey: false,
      metaKey: false,
      target: field(true),
    }),
  );
  assert.deepEqual(typed.at(0), { input: "type", del: false });
  assert.deepEqual(typed.at(-1), { input: "type", del: true });
  const { sent, recorder } = client({ consent: true });
  for (const input of typed) recorder.record("input", input);
  recorder.flush();
  const [{ records }] = sent;
  assert.equal(records.length, 12);
  for (const record of records)
    assert.deepEqual(Object.keys(record).sort(), ["del", "input", "stream", "t"]);
});

test("outside a text field, the key itself is kept", () => {
  assert.deepEqual(
    keyInput({
      key: "z",
      ctrlKey: true,
      shiftKey: false,
      altKey: false,
      metaKey: false,
      target: canvas,
    }),
    { input: "key", key: "z", ctrl: true, shift: false, alt: false, meta: false },
  );
});

test("with no GM client to relay them, traces are lost and the gap is sent once one is back", () => {
  const { sent, state, recorder } = client({ consent: true, ready: false });
  recorder.record("input", { input: "click", button: 0 });
  recorder.record("input", { input: "click", button: 0 });
  recorder.flush();
  recorder.record("input", { input: "click", button: 2 });
  recorder.flush();
  assert.equal(sent.length, 0);
  state.ready = true;
  recorder.flush();
  const [{ records }] = sent;
  assert.equal(records.length, 1);
  const gap = /** @type {{stream: string, from: number, to: number, lost: number}} */ (records[0]);
  assert.equal(gap.stream, "gap");
  assert.equal(gap.lost, 3);
  assert.ok(gap.from < gap.to);
});

test("a relay that drops a gap keeps counting what it lost", () => {
  /** @type {object[][]} */
  const sent = [];
  let ready = false;
  const relay = createOutbox({ ready: () => ready, send: (_user, records) => sent.push(records) });
  relay.push("bob", [{ t: 10, stream: "gap", from: 1, to: 9, lost: 5 }]);
  relay.push("bob", [{ t: 20, stream: "input", input: "click" }]);
  ready = true;
  relay.push("bob", []);
  assert.deepEqual(sent, [[{ t: 20, stream: "gap", from: 1, to: 20, lost: 6 }]]);
});

test("a relay ignores records without a time instead of corrupting the gap", () => {
  /** @type {object[][]} */
  const sent = [];
  let ready = false;
  const relay = createOutbox({ ready: () => ready, send: (_user, records) => sent.push(records) });
  relay.push("bob", [/** @type {any} */ ({ stream: "input" }), { t: 7, stream: "input" }]);
  ready = true;
  relay.push("bob", [/** @type {any} */ ({ stream: "input" })]);
  assert.deepEqual(sent, [[{ t: 7, stream: "gap", from: 7, to: 7, lost: 1 }]]);
});
