// The module's side of a VTT action (docs/contracts/foundry-bridge.md, "Actions").
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CEILING,
  createActions,
  missingTranslation,
} from "../secondchair-foundry/scripts/actions.js";

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
    ["Scene.s.Token.t", "Token", { x: 100, y: 200, hidden: true }],
    ["Scene.s.Wall.w", "Wall", { ds: 0 }],
    ["JournalEntry.j", "JournalEntry", { ownership: { default: 0 } }],
    ["User.u", "User", { name: "Alice" }],
  ])) {
    docs[uuid] = {
      documentName,
      ...structuredClone(fields),
      updates: 0,
      async update(changes) {
        await new Promise((resolve) => setTimeout(resolve, 5));
        for (const [path, value] of Object.entries(changes)) {
          // Foundry expands a dotted key into the nested field it names.
          const keys = path.split(".");
          const last = /** @type {string} */ (keys.pop());
          /** @type {any} */
          let at = this;
          for (const k of keys) at = at[k];
          at[last] = value;
        }
        this.updates += 1;
      },
    };
  }
  /** @type {string[]} */
  const said = [];
  /** @param {unknown} _token @param {string} line */
  const say = async (_token, line) => {
    said.push(line);
    return `m${said.length}`;
  };
  /** @type {[unknown, string][]} */
  const told = [];
  /** @param {unknown} user @param {string} line */
  const tell = async (user, line) => {
    told.push([/** @type {any} */ (user).name, line]);
    return `w${told.length}`;
  };
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
    language: () => "fr",
    say,
    tell,
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
  /** @param {object} request */
  const read = async (request) => {
    const message = /** @type {import("../secondchair-foundry/scripts/actions.js").Read} */ ({
      type: "read",
      ...request,
    });
    assert.ok(valid(message), JSON.stringify(valid.errors));
    const reply = await actions.read(message);
    assert.ok(valid(reply), JSON.stringify(valid.errors));
    return reply;
  };
  return {
    docs,
    said,
    told,
    handle,
    read,
    store,
    reload: () =>
      createActions({
        resolve: async (uuid) => docs[uuid] ?? null,
        store,
        adapter: () => adapter,
        ceiling: () => ceiling,
        language: () => "fr",
        say,
        tell,
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

test("a disclosure reveals a token and publishes a journal entry to the players", async () => {
  const { docs, handle } = world();
  const token = { op: "reveal_token", target: "Scene.s.Token.t", params: { hidden: false } };
  const shown = await handle({ id: "r1", expect: null, ...token });
  assert.deepEqual(shown, {
    type: "reply",
    id: "r1",
    ok: true,
    before: { hidden: true },
    after: { hidden: false },
  });
  const journal = { op: "publish_journal", target: "JournalEntry.j" };
  const published = await handle({
    id: "r2",
    expect: null,
    params: { "ownership.default": 2 },
    ...journal,
  });
  assert.deepEqual(published, {
    type: "reply",
    id: "r2",
    ok: true,
    before: { "ownership.default": 0 },
    after: { "ownership.default": 2 },
  });
  assert.equal(docs["Scene.s.Token.t"].hidden, false);
});

test("a creature speaks a line aloud, which no undo takes back", async () => {
  const { said, handle } = world();
  const line = { op: "speak", target: "Scene.s.Token.t", params: { content: "Die, longshanks!" } };
  const spoken = await handle({ id: "s1", expect: null, ...line });
  assert.deepEqual(spoken, {
    type: "reply",
    id: "s1",
    ok: true,
    before: { message: null },
    after: { message: "m1" },
  });
  assert.deepEqual(said, ["Die, longshanks!"]);
  const undo = await handle({
    id: "s2",
    ...line,
    params: { message: null },
    expect: { message: "m1" },
  });
  assert.equal(undo.ok, false);
  const wall = await handle({ id: "s3", expect: null, ...line, target: "Scene.s.Wall.w" });
  assert.match(wall.ok ? "" : wall.error, /not a Token/);
  assert.deepEqual(said, ["Die, longshanks!"]);
});

test("a whisper reaches one player, and no undo takes it back", async () => {
  const { told, handle } = world();
  const line = { op: "whisper", target: "User.u", params: { content: "The gauge is dry." } };
  const whispered = await handle({ id: "w1", expect: null, ...line });
  assert.deepEqual(whispered, {
    type: "reply",
    id: "w1",
    ok: true,
    before: { message: null },
    after: { message: "w1" },
  });
  assert.deepEqual(told, [["Alice", "The gauge is dry."]]);
  const undo = await handle({
    id: "w2",
    ...line,
    params: { message: null },
    expect: { message: "w1" },
  });
  assert.equal(undo.ok, false);
  const token = await handle({ id: "w3", expect: null, ...line, target: "Scene.s.Token.t" });
  assert.match(token.ok ? "" : token.error, /not a User/);
  assert.equal(told.length, 1);
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

test("a read goes to the system adapter with the campaign language, outside the queue", async () => {
  /** @type {unknown[]} */
  const asked = [];
  const adapter = {
    ops: {},
    reads: {
      official_name: async (/** @type {object} */ params, /** @type {object} */ context) => {
        asked.push(params, context);
        return { name: "Gobelin guerrier", key: "goblin-warrior", pack: null };
      },
    },
  };
  const { read, store } = world({ adapter });
  const reply = await read({ id: "q", op: "official_name", params: { key: "goblin-warrior" } });
  assert.deepEqual(reply, {
    type: "reply",
    id: "q",
    ok: true,
    result: { name: "Gobelin guerrier", key: "goblin-warrior", pack: null },
  });
  assert.deepEqual(asked, [{ key: "goblin-warrior" }, { language: "fr" }]);
  assert.deepEqual(store.load(), []);
});

test("a read with no system adapter, or one it does not know, is refused", async () => {
  for (const adapter of [null, { ops: {}, reads: {} }]) {
    const { read } = world({ adapter });
    const reply = await read({ id: "q", op: "rules_context", params: {} });
    assert.equal(reply.ok, false);
  }
});

test("a mechanical action reaches the adapter with its target, which it resolves itself", async () => {
  /** @type {unknown[]} */
  const targets = [];
  const adapter = {
    ops: {
      set_date: async (/** @type {string} */ target) => {
        targets.push(target);
        return { before: { date: "4725-03-01" }, after: { date: "4725-05-12" } };
      },
    },
  };
  const { handle } = world({ adapter });
  const reply = await handle({
    id: "c",
    op: "set_date",
    target: "time",
    params: { calendar: "absalom", date: "4725-05-12" },
    expect: null,
    level: null,
  });
  assert.equal(reply.ok, true);
  assert.deepEqual(targets, ["time"]);
});

test("a campaign language whose translation module is inactive refuses the connection", () => {
  const adapter = { ops: {}, translations: { fr: "pf2-fr" } };
  const active = (/** @type {string} */ id) => id === "pf2-fr";
  assert.match(String(missingTranslation(adapter, "fr", () => false)), /pf2-fr/);
  assert.match(String(missingTranslation(adapter, "fr-CA", () => false)), /pf2-fr/);
  assert.equal(missingTranslation(adapter, "fr", active), null);
  // No module for German; no adapter at all.
  assert.equal(
    missingTranslation(adapter, "de", () => false),
    null,
  );
  assert.equal(
    missingTranslation(null, "fr", () => false),
    null,
  );
});
