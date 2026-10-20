// Realising a prepared scene by reconciliation (ARC-10, BVE-02, docs/contracts/foundry-bridge.md).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Ajv2020 } from "ajv/dist/2020.js";
import {
  canonical,
  MODULE,
  realise,
  reconcile,
  summary,
  withoutPlayed,
} from "../secondchair-foundry/scripts/scenes.js";

const schema = JSON.parse(
  readFileSync(new URL("../../docs/contracts/foundry-bridge.schema.json", import.meta.url), "utf8"),
);
const valid = new Ajv2020().compile(schema);

// The v3 reconciliation cases, carried as tests (BVE-01, BVE-02).

/** @param {string} key */
const want = (key, spec = "s1", type = "AmbientLight") => ({ key, type, spec });
/** @param {string} key @param {{spec?: string, local?: string, current?: string, type?: string}} [o] */
const have = (key, { spec = "s1", local = "l1", current = "l1", type = "AmbientLight" } = {}) => ({
  key,
  type,
  id: `id-${key}`,
  spec,
  local,
  current,
});

test("a first realisation creates everything", () => {
  assert.deepEqual(summary(reconcile([want("a"), want("b")], [])), { create: 2 });
});

test("realising again with no change writes nothing", () => {
  assert.deepEqual(summary(reconcile([want("a")], [have("a")], { a: true })), { noop: 1 });
});

test("prep changed, nothing retouched: updated", () => {
  const [a] = reconcile([want("a", "s2")], [have("a")], { a: true });
  assert.equal(a.action, "update");
  assert.equal(a.id, "id-a");
});

test("retouched by the GM, prep unchanged: kept with no conflict", () => {
  const [a] = reconcile([want("a")], [have("a", { current: "l9" })], { a: true });
  assert.equal(a.action, "retouched");
});

test("retouched by the GM and prep changed: a conflict, then the GM's choice", () => {
  /** @type {[ReturnType<typeof want>[], ReturnType<typeof have>[], Record<string, boolean>]} */
  const args = [[want("a", "s2")], [have("a", { current: "l9" })], { a: true }];
  assert.equal(reconcile(...args)[0].action, "conflict");
  assert.equal(reconcile(...args, { a: "keep" })[0].action, "retouched");
  assert.equal(reconcile(...args, { a: "overwrite" })[0].action, "update");
});

test("deleted in play: never recreated silently", () => {
  assert.equal(reconcile([want("gob")], [], { gob: true })[0].action, "kept-deleted");
  assert.equal(
    reconcile([want("gob")], [], { gob: true }, { gob: "recreate" })[0].action,
    "create",
  );
});

test("removed from prep: deleted, unless retouched", () => {
  assert.equal(reconcile([], [have("a")])[0].action, "delete");
  assert.equal(reconcile([], [have("a", { current: "l9" })])[0].action, "conflict");
});

test("play state is not a retouch", () => {
  const wall = { c: [0, 0, 100, 0], door: 1, ds: 0 };
  assert.equal(
    canonical(withoutPlayed("Wall", wall)),
    canonical(withoutPlayed("Wall", { ...wall, ds: 1 })),
  );
  const region = { name: "Trap", behaviors: [{ type: "executeScript", disabled: false }] };
  assert.equal(
    canonical(withoutPlayed("Region", region)),
    canonical(
      withoutPlayed("Region", {
        ...region,
        behaviors: [{ type: "executeScript", disabled: true }],
      }),
    ),
  );
  const token = { name: "Goblin", x: 100, y: 100, hidden: true, disposition: -1 };
  assert.equal(
    canonical(withoutPlayed("Token", token)),
    canonical(withoutPlayed("Token", { ...token, x: 300, hidden: false })),
  );
  assert.notEqual(
    canonical(withoutPlayed("Token", token)),
    canonical(withoutPlayed("Token", { ...token, name: "Other" })),
  );
});

test("canonical ignores key order", () => {
  assert.equal(
    canonical({ b: 1, a: [1, { d: 2, c: 3 }] }),
    canonical({ a: [1, { c: 3, d: 2 }], b: 1 }),
  );
});

// The realisation in a Foundry world, with a stand-in for the Scene documents.

/** @param {Record<string, any>} target @param {Record<string, any>} changes */
function merge(target, changes) {
  for (const [k, v] of Object.entries(changes)) {
    if (
      v &&
      typeof v === "object" &&
      !Array.isArray(v) &&
      target[k] &&
      typeof target[k] === "object"
    )
      merge(target[k], v);
    else target[k] = structuredClone(v);
  }
}

let ids = 0;
/** @param {Record<string, any>} data */
function doc(data) {
  /** @type {Record<string, any>} */
  const source = { ...structuredClone(data), _id: `d${++ids}` };
  return {
    get id() {
      return source._id;
    },
    get flags() {
      return source.flags ?? {};
    },
    source,
    toObject: () => structuredClone(source),
    /** @param {Record<string, any>} changes */
    update: async (changes) => merge(source, changes),
  };
}

function world() {
  /** @type {ReturnType<typeof fakeScene>[]} */
  const scenes = [];
  function fakeScene(/** @type {Record<string, any>} */ data) {
    const scene = doc(data);
    /** @type {Record<string, ReturnType<typeof doc>[]>} */
    const embedded = {};
    const coll = (/** @type {string} */ type) => {
      embedded[type] ??= [];
      return embedded[type];
    };
    return Object.assign(scene, {
      embedded,
      getEmbeddedCollection: coll,
      /** @param {string} type @param {Record<string, any>[]} datas */
      createEmbeddedDocuments: async (type, datas) => {
        const made = datas.map(doc);
        coll(type).push(...made);
        return made;
      },
      /** @param {string} type @param {Record<string, any>[]} updates */
      updateEmbeddedDocuments: async (type, updates) =>
        Promise.all(
          updates.map(async ({ _id, ...changes }) => {
            const d = /** @type {ReturnType<typeof doc>} */ (coll(type).find((e) => e.id === _id));
            await d.update(changes);
            return d;
          }),
        ),
      /** @param {string} type @param {string[]} gone */
      deleteEmbeddedDocuments: async (type, gone) => {
        embedded[type] = coll(type).filter((d) => !gone.includes(d.id));
      },
    });
  }
  const deps = {
    findScene: (/** @type {string} */ key) =>
      scenes.find((s) => s.flags[MODULE]?.scene === key) ?? null,
    createScene: async (/** @type {Record<string, any>} */ data) => {
      const scene = fakeScene(data);
      scenes.push(scene);
      return scene;
    },
    /** @param {{actor?: string, data: Record<string, any>}} item @returns {Promise<Record<string, any>>} */
    tokenData: async (item) => ({ actorId: `actor-of-${item.actor}`, ...item.data }),
  };
  return { scenes, deps };
}

/** @param {object} [overrides] */
const cave = (overrides = {}) => ({
  scene: { name: "Goblin cave", width: 2000, height: 1500 },
  items: [
    {
      key: "boss",
      type: "Token",
      actor: "Compendium.pf2e.pathfinder-bestiary.Actor.goblin",
      data: { name: "Goblin boss", x: 100, y: 100, hidden: true },
    },
    { key: "torch", type: "AmbientLight", data: { x: 500, y: 500, config: { bright: 10 } } },
  ],
  ...overrides,
});

/** @param {ReturnType<typeof world>} w @param {any} desired */
async function realiseChecked(w, desired) {
  const message = { type: "realise", id: "r1", scene: "cave", desired };
  assert.ok(valid(message), JSON.stringify(valid.errors));
  const report = await realise("cave", desired, w.deps);
  const reply = { type: "realised", id: "r1", ok: true, report };
  assert.ok(valid(reply), JSON.stringify(valid.errors));
  return report;
}

test("a first realisation creates the scene and its objects, tokens from their actor", async () => {
  const w = world();
  const report = await realiseChecked(w, cave());
  assert.deepEqual(report.summary, { create: 3 });
  const [scene] = w.scenes;
  assert.equal(scene.source.name, "Goblin cave");
  const [boss] = scene.embedded.Token;
  assert.equal(boss.source.actorId, "actor-of-Compendium.pf2e.pathfinder-bestiary.Actor.goblin");
  assert.equal(boss.source.flags[MODULE].key, "boss");
  assert.deepEqual((await realiseChecked(w, cave())).summary, { noop: 3 });
});

test("a token the GM moved by hand survives a second reconciliation", async () => {
  const w = world();
  await realiseChecked(w, cave());
  const [boss] = w.scenes[0].embedded.Token;
  await boss.update({ x: 700, y: 300, hidden: false }); // moved and revealed in play

  assert.deepEqual((await realiseChecked(w, cave())).summary, { noop: 3 });
  const renamed = cave();
  renamed.items[0].data.name = "Goblin chief";
  const report = await realiseChecked(w, renamed);

  assert.equal(report.actions.find((a) => a.key === "boss")?.action, "update");
  assert.deepEqual([boss.source.name, boss.source.x, boss.source.y], ["Goblin chief", 700, 300]);
  assert.equal(boss.source.hidden, false);
});

test("a GM retouch is kept, and a prep change to it waits for the GM's choice", async () => {
  const w = world();
  await realiseChecked(w, cave());
  const [torch] = w.scenes[0].embedded.AmbientLight;
  assert.ok(torch);
  await torch.update({ config: { bright: 30 } });

  assert.equal((await realiseChecked(w, cave())).summary.retouched, 1);
  const brighter = cave();
  /** @type {any} */ (brighter.items[1].data).config.bright = 20;
  const report = await realiseChecked(w, brighter);
  assert.equal(report.summary.conflict, 1);
  assert.equal(torch.source.config.bright, 30);

  await realiseChecked(w, { ...brighter, choices: { torch: "overwrite" } });
  assert.equal(torch.source.config.bright, 20);
});

test("an object removed in play is not recreated; one dropped from prep is deleted", async () => {
  const w = world();
  await realiseChecked(w, cave());
  const scene = w.scenes[0];
  await scene.deleteEmbeddedDocuments("Token", [scene.embedded.Token[0].id]); // killed

  const report = await realiseChecked(w, cave());
  assert.equal(report.actions.find((a) => a.key === "boss")?.action, "kept-deleted");
  assert.equal(scene.embedded.Token.length, 0);

  await realiseChecked(w, cave({ items: [] }));
  assert.equal(scene.embedded.AmbientLight.length, 0);
});

test("an object that cannot be written is reported, the others are realised", async () => {
  const w = world();
  w.deps.tokenData = async () => {
    throw new Error("Compendium.pf2e.x: not found");
  };
  const report = await realiseChecked(w, cave());
  assert.deepEqual(report.errors, ["boss: Compendium.pf2e.x: not found"]);
  assert.equal(w.scenes[0].embedded.AmbientLight.length, 1);
});

test("an object dropped from prep and added back is created again", async () => {
  const w = world();
  await realiseChecked(w, cave());
  await realiseChecked(w, cave({ items: [cave().items[0]] }));
  const report = await realiseChecked(w, cave());
  assert.equal(report.actions.find((a) => a.key === "torch")?.action, "create");
});

test("a copy the GM pasted stays the GM's: dropping the item from prep deletes one object", async () => {
  const w = world();
  await realiseChecked(w, cave());
  const scene = w.scenes[0];
  await scene.createEmbeddedDocuments("Token", [scene.embedded.Token[0].toObject()]);

  await realiseChecked(w, cave({ items: [cave().items[1]] }));
  assert.equal(scene.embedded.Token.length, 1);
});

test("a prep change of a token's actor or of an object's type takes effect", async () => {
  const w = world();
  await realiseChecked(w, cave());
  const changed = cave();
  changed.items[0].actor = "Compendium.pf2e.pathfinder-bestiary.Actor.ogre";
  /** @type {any[]} */ (changed.items)[1] = {
    key: "torch",
    type: "Tile",
    data: { x: 500, y: 500 },
  };
  const report = await realiseChecked(w, changed);

  assert.deepEqual(report.errors, []);
  const scene = w.scenes[0];
  assert.equal(
    scene.embedded.Token[0].source.actorId,
    "actor-of-Compendium.pf2e.pathfinder-bestiary.Actor.ogre",
  );
  assert.equal(scene.embedded.AmbientLight.length, 0);
  assert.equal(scene.embedded.Tile.length, 1);
});

test("a created object keeps the flags its data or actor gave it", async () => {
  const w = world();
  w.deps.tokenData = async (item) => ({ ...item.data, flags: { pf2e: { linkToActorSize: true } } });
  await realiseChecked(w, cave());
  const { flags } = w.scenes[0].embedded.Token[0].source;
  assert.deepEqual(flags.pf2e, { linkToActorSize: true });
  assert.equal(flags[MODULE].key, "boss");
});
