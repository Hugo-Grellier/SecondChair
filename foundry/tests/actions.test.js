// The module's side of a VTT action (docs/contracts/foundry-bridge.md, "Actions").
import assert from "node:assert/strict";
import { test } from "node:test";
import { CEILING, createActions } from "../secondchair-foundry/scripts/actions.js";

import { validMessage as valid } from "./schema.js";

/** @typedef {import("../secondchair-foundry/scripts/actions.js").Request} Request */

/**
 * A world with one token and one door, a store of handled requests, and the module's handler.
 * Requests are at act-then-review unless they say otherwise.
 * @param {{adapter?: import("../secondchair-foundry/scripts/actions.js").Adapter | null, ceiling?: string}} [options]
 */
function world({ adapter = null, ceiling = CEILING.default } = {}) {
  /** @type {Record<string, {documentName: string, updates: number, update: (c: object) => Promise<void>} & Record<string, unknown>>} */
  const docs = {};
  for (const [uuid, documentName, fields] of /** @type {const} */ ([
    ["Scene.s.Token.t", "Token", { x: 100, y: 200 }],
    ["Scene.s.Wall.w", "Wall", { ds: 0 }],
  ])) {
    docs[uuid] = {
      documentName,
      ...fields,
      updates: 0,
      async update(changes) {
        await new Promise((resolve) => setTimeout(resolve, 5));
        Object.assign(this, changes);
        this.updates += 1;
      },
    };
  }
  /** @type {unknown[]} */
  let saved = [];
  const store = {
    load: () => saved,
    save: async (/** @type {unknown[]} */ list) => {
      saved = structuredClone(list);
    },
  };
  const actions = createActions({
    resolve: async (uuid) => docs[uuid] ?? null,
    store,
    adapter: () => adapter,
    ceiling: () => ceiling,
  });
  /** @param {object} request */
  const handle = async (request) => {
    const message = /** @type {Request} */ ({
      type: "request",
      level: "act-then-review",
      ...request,
    });
    assert.ok(valid(message), JSON.stringify(valid.errors));
    const reply = await actions.handle(message);
    assert.ok(valid(reply), JSON.stringify(valid.errors));
    return reply;
  };
  return {
    docs,
    handle,
    store,
    reload: () =>
      createActions({
        resolve: async (uuid) => docs[uuid] ?? null,
        store,
        adapter: () => adapter,
        ceiling: () => ceiling,
      }),
  };
}

/** @param {string} id @param {number} x @param {number} y @param {object | null} [expect] */
const move = (id, x, y, expect = null) => ({
  id,
  op: "move_token",
  target: "Scene.s.Token.t",
  params: { x, y },
  expect,
});

test("a token move replies with its before and after positions", async () => {
  const { docs, handle } = world();
  const reply = await handle(move("r1", 300, 200));
  assert.deepEqual(reply, {
    type: "reply",
    id: "r1",
    ok: true,
    before: { x: 100, y: 200 },
    after: { x: 300, y: 200 },
  });
  assert.equal(docs["Scene.s.Token.t"].x, 300);
});

test("a replayed request id is applied once and gets the first reply", async () => {
  const { docs, handle } = world();
  const [first, second] = await Promise.all([
    handle(move("r1", 300, 200)),
    handle(move("r1", 300, 200)),
  ]);
  const third = await handle(move("r1", 300, 200));
  assert.deepEqual(second, first);
  assert.deepEqual(third, first);
  assert.equal(docs["Scene.s.Token.t"].updates, 1);
});

test("a replayed request id is applied once after a reload of the GM client", async () => {
  const { docs, handle, reload } = world();
  const first = await handle(move("r1", 300, 200));
  const replay = /** @type {Request} */ ({
    type: "request",
    level: "act-then-review",
    ...move("r1", 300, 200),
  });
  assert.deepEqual(await reload().handle(replay), first);
  assert.equal(docs["Scene.s.Token.t"].updates, 1);
});

test("writes are queued one at a time", async () => {
  const { handle } = world();
  const replies = await Promise.all([handle(move("a", 300, 200)), handle(move("b", 500, 200))]);
  assert.deepEqual(
    replies.map((r) => r.ok && r.before),
    [
      { x: 100, y: 200 },
      { x: 300, y: 200 },
    ],
  );
});

test("an undo is refused when the token moved since", async () => {
  const { docs, handle } = world();
  await handle(move("r1", 300, 200));
  docs["Scene.s.Token.t"].x = 700; // the GM moved it by hand
  const reply = await handle(move("r2", 100, 200, { x: 300, y: 200 }));
  assert.equal(reply.ok, false);
  assert.match(reply.ok ? "" : reply.error, /changed since/);
  assert.equal(docs["Scene.s.Token.t"].x, 700);
});

test("a door opens", async () => {
  const { docs, handle } = world();
  const reply = await handle({
    id: "d",
    op: "set_door",
    target: "Scene.s.Wall.w",
    params: { ds: 1 },
    expect: null,
  });
  assert.deepEqual(reply.ok && reply.after, { ds: 1 });
  assert.equal(docs["Scene.s.Wall.w"].ds, 1);
});

test("a generic action refuses the wrong document or fields", async () => {
  const { handle } = world();
  for (const request of [
    { id: "1", op: "move_token", target: "Scene.s.Wall.w", params: { x: 1 }, expect: null },
    {
      id: "2",
      op: "move_token",
      target: "Scene.s.Token.t",
      params: { hidden: true },
      expect: null,
    },
    { id: "3", op: "move_token", target: "Scene.s.Token.gone", params: { x: 1 }, expect: null },
  ]) {
    assert.equal((await handle(request)).ok, false, request.id);
  }
});

test("a mechanical action with no system adapter is refused", async () => {
  const { handle } = world();
  const reply = await handle({
    id: "s",
    op: "strike",
    target: "Scene.s.Token.t",
    params: {},
    expect: null,
  });
  assert.equal(reply.ok, false);
  assert.match(reply.ok ? "" : reply.error, /no system adapter/i);
});

test("a mechanical action goes to the system adapter when there is one", async () => {
  const adapter = { ops: { strike: async () => ({ before: { hp: 10 }, after: { hp: 4 } }) } };
  const { handle } = world({ adapter });
  const reply = await handle({
    id: "s",
    op: "strike",
    target: "Scene.s.Token.t",
    params: {},
    expect: null,
  });
  assert.deepEqual(reply.ok && reply.after, { hp: 4 });
});

test("a fresh world's ceiling is act-then-review", () => {
  assert.equal(CEILING.default, "act-then-review");
  assert.equal(CEILING.scope, "world");
  assert.deepEqual(Object.keys(CEILING.choices), [
    "manual",
    "propose",
    "act-then-review",
    "autonomous",
  ]);
});

test("an action above the ceiling is refused as a ceiling refusal and nothing is done", async () => {
  const { docs, handle } = world({ ceiling: "propose" });
  const reply = await handle(move("r1", 300, 200));
  assert.equal(reply.ok, false);
  assert.equal(!reply.ok && reply.reason, "ceiling");
  assert.match(reply.ok ? "" : reply.error, /ceiling \(propose\)/);
  assert.equal(docs["Scene.s.Token.t"].updates, 0);
});

test("an action at or under the ceiling, and the GM's undo, are taken", async () => {
  const { handle } = world({ ceiling: "propose" });
  assert.equal((await handle({ ...move("r1", 300, 200), level: "propose" })).ok, true);
  const undo = await handle({ ...move("r2", 100, 200, { x: 300, y: 200 }), level: null });
  assert.equal(undo.ok, true);
});

test("an unknown ceiling refuses every action", async () => {
  assert.equal((await world({ ceiling: "unknown" }).handle(move("r1", 1, 2))).ok, false);
});

test("at the manual ceiling no action is taken", async () => {
  const reply = await world({ ceiling: "manual" }).handle({
    ...move("r1", 1, 2),
    level: "propose",
  });
  assert.equal(!reply.ok && reply.reason, "ceiling");
});
