// The module's half of the handshake (docs/contracts/foundry-bridge.md), against the contract's schema.
import assert from "node:assert/strict";
import { test } from "node:test";
import { connect, coreUrl, hello } from "../secondchair-foundry/scripts/bridge.js";

import { validMessage as valid } from "./schema.js";

/** A WebSocket stand-in recording what the module sends; the test plays the Core. */
class FakeSocket extends EventTarget {
  /** @type {FakeSocket[]} */
  static opened = [];
  /** @type {string[]} */
  sent = [];
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
  t.mock.timers.tick(10000);
  assert.deepEqual(opened.calls, []);
  assert.deepEqual(closed.calls, ["unreachable"]);
});
