// The module's half of the handshake (docs/contracts/foundry-bridge.md), against the contract's schema.
import assert from "node:assert/strict";
import { test } from "node:test";
import { connect, coreUrl, createLink, hello } from "../secondchair-foundry/scripts/bridge.js";

import { validMessage as valid } from "./schema.js";

/** A WebSocket stand-in recording what the module sends; the test plays the Core. */
class FakeSocket extends EventTarget {
  /** @type {FakeSocket[]} */
  static opened = [];
  /** @type {string[]} */
  sent = [];
  closed = false;
  /** @param {string} url */
  constructor(url) {
    super();
    this.url = url;
    FakeSocket.opened.push(this);
  }
  /** @param {string} data */
  send(data) {
    this.sent.push(data);
  }
  /** @param {object} message */
  reply(message) {
    this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(message) }));
  }
  close() {
    this.closed = true;
    this.dispatchEvent(new Event("close"));
  }
}

/** Dial a fake Core; return the socket and the callbacks it triggered. */
function dial() {
  /** @type {string[]} */
  const calls = [];
  connect({
    url: coreUrl(7240),
    hello: hello({ token: "t0k3n", world: "secondchair-dev", campaign: "" }),
    onWelcome: (welcome) => calls.push(`welcome ${welcome.campaign}`),
    onRefused: (refusal) => calls.push(`refused ${refusal.reason}`),
    onUnreachable: () => calls.push("unreachable"),
    onPending: () => calls.push("pending"),
    WebSocketImpl: /** @type {typeof WebSocket} */ (/** @type {unknown} */ (FakeSocket)),
  });
  const socket = /** @type {FakeSocket} */ (FakeSocket.opened.at(-1));
  return { socket, calls };
}

test("the module dials the loopback Core and sends a hello the contract accepts", () => {
  const { socket } = dial();
  assert.equal(socket.url, "ws://127.0.0.1:7240/foundry");
  socket.dispatchEvent(new Event("open"));
  const sent = JSON.parse(socket.sent[0]);
  assert.ok(valid(sent), JSON.stringify(valid.errors));
  assert.deepEqual(sent, {
    type: "hello",
    protocol: "0.1.0",
    token: "t0k3n",
    world: "secondchair-dev",
    campaign: null,
  });
});

test("a welcome is handed over once", () => {
  const { socket, calls } = dial();
  socket.reply({ type: "welcome", protocol: "0.1.0", campaign: "c1", campaign_language: "fr" });
  socket.dispatchEvent(new Event("close"));
  assert.deepEqual(calls, ["welcome c1"]);
});

test("a refusal is reported with its reason, not as an unreachable Core", () => {
  const { socket, calls } = dial();
  socket.reply({ type: "refused", reason: "busy", message: "Another GM client is connected." });
  socket.dispatchEvent(new Event("close"));
  assert.deepEqual(calls, ["refused busy"]);
});

test("a socket closed before any answer means the Core is unreachable", () => {
  const { socket, calls } = dial();
  socket.dispatchEvent(new Event("close"));
  assert.deepEqual(calls, ["unreachable"]);
});

test("a socket still pending after a few seconds is reported, without giving up", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { socket, calls } = dial();
  t.mock.timers.tick(4999);
  assert.deepEqual(calls, []);
  t.mock.timers.tick(1);
  assert.deepEqual(calls, ["pending"]);
  socket.dispatchEvent(new Event("open"));
  socket.reply({ type: "welcome", protocol: "0.1.0", campaign: "c1", campaign_language: "fr" });
  assert.deepEqual(calls, ["pending", "welcome c1"]);
});

test("a socket that opens or closes in time is never reported as pending", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const opened = dial();
  opened.socket.dispatchEvent(new Event("open"));
  const closed = dial();
  closed.socket.dispatchEvent(new Event("close"));
  t.mock.timers.tick(9999); // within the reply timeout, which the next tests cover
  assert.deepEqual(opened.calls, []);
  assert.deepEqual(closed.calls, ["unreachable"]);
});

const WELCOME = { type: "welcome", protocol: "0.1.0", campaign: "c1", campaign_language: "fr" };

/** A link to a fake Core; the hello is rebuilt from `bound` at each dial. */
function link() {
  /** @type {string[]} */
  const statuses = [];
  /** @type {string[]} */
  const welcomed = [];
  const bound = { campaign: "" };
  const l = createLink({
    url: coreUrl(7240),
    hello: () => hello({ token: "t0k3n", world: "w", campaign: bound.campaign }),
    onWelcome: (welcome) => welcomed.push(welcome.campaign),
    onStatus: (status) => statuses.push(status.state),
    WebSocketImpl: /** @type {typeof WebSocket} */ (/** @type {unknown} */ (FakeSocket)),
  });
  const last = () => /** @type {FakeSocket} */ (FakeSocket.opened.at(-1));
  return { l, statuses, welcomed, bound, last };
}

test("Retry dials an unreachable Core again, with no reload, and never on its own", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { l, statuses, welcomed, bound, last } = link();
  const before = FakeSocket.opened.length;
  assert.equal(l.dial(), true);
  last().close(); // closed during the dial: unreachable, not stuck dialing
  assert.deepEqual(l.status, { state: "unreachable", url: "ws://127.0.0.1:7240/foundry" });
  t.mock.timers.tick(60000);
  assert.equal(FakeSocket.opened.length, before + 1, "no dial without a Retry");
  bound.campaign = "c1"; // bound by a welcome meanwhile: the next hello carries it
  assert.equal(l.dial(), true);
  last().dispatchEvent(new Event("open"));
  assert.equal(JSON.parse(last().sent[0]).campaign, "c1");
  last().reply(WELCOME);
  assert.deepEqual(statuses, ["dialing", "unreachable", "dialing", "connected"]);
  assert.deepEqual(welcomed, ["c1"]);
});

test("a double click on Retry dials once; a connected link is not dialed again", () => {
  const { l, statuses, last } = link();
  const before = FakeSocket.opened.length;
  assert.equal(l.dial(), true);
  assert.equal(l.dial(), false);
  assert.equal(FakeSocket.opened.length, before + 1);
  assert.deepEqual(statuses, ["dialing"], "no second status for an ignored dial");
  last().reply(WELCOME);
  assert.equal(l.dial(), false);
  assert.equal(FakeSocket.opened.length, before + 1);
});

test("a refusal, busy included, keeps the Core's reason and message and allows a Retry", () => {
  const { l, last } = link();
  l.dial();
  const message = "Another GM client is already connected to this campaign; close it first.";
  last().reply({ type: "refused", reason: "busy", message });
  last().close(); // the Core closes after refusing: still refused, not unreachable
  assert.deepEqual(l.status, { state: "refused", reason: "busy", message });
  assert.equal(l.dial(), true);
  assert.equal(l.status?.state, "dialing");
});

test("a reply that is not a welcome nor a refusal closes the socket as malformed", () => {
  for (const data of [
    "not json",
    "null",
    "42",
    '"welcome"',
    "[]",
    '{"type": "hello"}',
    '{"type": "refused"}', // no reason: never shown as "undefined"
  ]) {
    const { l, last } = link();
    l.dial();
    last().dispatchEvent(new MessageEvent("message", { data }));
    assert.equal(l.status?.state, "refused", data);
    assert.equal(/** @type {{reason: string}} */ (l.status).reason, "malformed", data);
    assert.doesNotMatch(/** @type {{message: string}} */ (l.status).message, /undefined/);
    assert.ok(last().closed, data);
    assert.equal(l.dial(), true, `${data}: Retry is offered`);
  }
});

test("an open socket that never answers the hello is unreachable, so Retry is offered", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { l, statuses, last } = link();
  l.dial();
  last().dispatchEvent(new Event("open"));
  t.mock.timers.tick(9999);
  assert.equal(l.status?.state, "dialing");
  t.mock.timers.tick(1);
  assert.deepEqual(l.status, { state: "unreachable", url: "ws://127.0.0.1:7240/foundry" });
  assert.ok(last().closed);
  assert.deepEqual(statuses, ["dialing", "unreachable"], "reported once, close included");
  last().reply(WELCOME); // too late: ignored
  assert.equal(l.status?.state, "unreachable");
});

test("an answer in time stops the reply timeout", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { l, last } = link();
  l.dial();
  last().dispatchEvent(new Event("open"));
  last().reply(WELCOME);
  t.mock.timers.tick(60000);
  assert.equal(l.status?.state, "connected");
  assert.equal(last().closed, false);
});

test("a connection that closes is lost, and Reconnect dials again", () => {
  const { l, statuses, last } = link();
  l.dial();
  last().reply(WELCOME);
  last().close();
  assert.equal(l.status?.state, "lost");
  assert.equal(l.dial(), true);
  last().reply(WELCOME);
  assert.deepEqual(statuses, ["dialing", "connected", "lost", "dialing", "connected"]);
});

test("a welcomed connection the module drops says why, not that it was lost", () => {
  const { l, last } = link();
  l.dial();
  last().reply(WELCOME);
  const socket = last();
  l.fail("Install and enable the French translation module.");
  assert.ok(socket.closed);
  assert.deepEqual(l.status, {
    state: "refused",
    reason: "module",
    message: "Install and enable the French translation module.",
  });
});
