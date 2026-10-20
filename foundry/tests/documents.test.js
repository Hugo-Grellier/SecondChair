// Realising a prepared world document, its references, and the generic reads (ARC-07, ARC-10,
// docs/contracts/foundry-bridge.md).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  dataPath,
  finder,
  genericReads,
  guardedScene,
  LIMIT,
  realiseDocument,
  resolve,
} from "../secondchair-foundry/scripts/documents.js";
import { MODULE } from "../secondchair-foundry/scripts/scenes.js";
import { validMessage as valid } from "./schema.js";

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

/** The embedded field each embedded document type lives in. */
/** @type {Record<string, string>} */
const FIELD = { JournalEntryPage: "pages", PlaylistSound: "sounds", Item: "items" };

/** A stand-in for Foundry's expandObject: `a.b` keys become nested objects.
 * @param {Record<string, any>} data @returns {Record<string, any>} */
function expand(data) {
  /** @type {Record<string, any>} */
  const out = {};
  for (const [path, value] of Object.entries(data)) {
    const keys = path.split(".");
    const last = /** @type {string} */ (keys.pop());
    let at = out;
    for (const k of keys) at = at[k] ??= {};
    at[last] = value && typeof value === "object" && !Array.isArray(value) ? expand(value) : value;
  }
  return out;
}

let ids = 0;
/** A stand-in for a world document, its embedded documents kept in its source.
 * @param {string} documentName @param {Record<string, any>} data */
function doc(documentName, data) {
  /** @type {Record<string, any>} */
  const source = { ...structuredClone(data), _id: `d${++ids}` };
  for (const field of Object.values(FIELD))
    source[field] = source[field]?.map((/** @type {any} */ e) => ({ ...e, _id: `e${++ids}` }));
  /** @param {string} type */
  const list = (type) => /** @type {any[]} */ ((source[FIELD[type]] ??= []));
  /** Only the id and name are read. @param {any} e @returns {any} */
  const wrap = (e) => ({ id: e._id, name: e.name });
  return {
    documentName,
    deleted: false,
    get id() {
      return source._id;
    },
    get uuid() {
      return `${documentName}.${source._id}`;
    },
    get name() {
      return source.name;
    },
    get flags() {
      return source.flags ?? {};
    },
    source,
    toObject: () => structuredClone(source),
    /** @param {Record<string, any>} changes */
    update: async (changes) => merge(source, changes),
    /** @param {string} type */
    getEmbeddedCollection: (type) => list(type).map(wrap),
    /** @param {string} type @param {Record<string, any>[]} datas */
    createEmbeddedDocuments: async (type, datas) => {
      const made = datas.map((d) => ({ ...structuredClone(d), _id: `e${++ids}` }));
      list(type).push(...made);
      return made.map(wrap);
    },
    updateEmbeddedDocuments: async () => [],
    /** @param {string} type @param {string[]} gone */
    deleteEmbeddedDocuments: async (type, gone) => {
      source[FIELD[type]] = list(type).filter((e) => !gone.includes(e._id));
    },
    async delete() {
      this.deleted = true;
    },
  };
}

function world() {
  /** @type {ReturnType<typeof doc>[]} */
  const docs = [];
  /** @type {Record<string, boolean>} */
  let created = {};
  const deps = {
    findDocument: (/** @type {string} */ key) =>
      docs.find((d) => !d.deleted && d.flags[MODULE]?.document === key) ?? null,
    createDocument: async (/** @type {string} */ type, /** @type {Record<string, any>} */ data) => {
      const made = doc(type, data);
      docs.push(made);
      return made;
    },
    fromBase: async (
      /** @type {string} */ _type,
      /** @type {string} */ base,
      /** @type {Record<string, any>} */ data,
    ) => {
      const imported = { name: "Goblin Warrior", img: "goblin.webp", system: { level: -1 } };
      return { ...imported, ...data, flags: { core: { sourceId: base } } };
    },
    markdown: (/** @type {string} */ text) =>
      `<p>${text.replace(/\*\*(.*?)\*\*/g, "<b>$1</b>")}</p>`,
    expand,
    // A stand-in for Foundry's cleanHTML: scripts and event handlers go.
    clean: (/** @type {string} */ html) =>
      html.replace(/<script[\s\S]*?<\/script>/gi, "").replace(/\s+on\w+="[^"]*"/gi, ""),
    created: {
      load: () => created,
      save: async (/** @type {Record<string, boolean>} */ c) => {
        created = structuredClone(c);
      },
    },
  };
  return { docs, deps };
}

const handout = () => ({
  type: "JournalEntry",
  data: {
    name: "The ransom note",
    pages: [{ name: "Note", type: "text", text: { markdown: "Bring **100 gp**." } }],
  },
});

/** @param {ReturnType<typeof world>} w @param {any} desired @param {string} [key] */
async function realiseChecked(w, desired, key = "ransom") {
  const message = { type: "realise_document", id: "r1", document: key, desired, level: null };
  assert.ok(valid(message), JSON.stringify(valid.errors));
  const report = await realiseDocument(key, desired, w.deps);
  const reply = { type: "realised", id: "r1", ok: true, report };
  assert.ok(valid(reply), JSON.stringify(valid.errors));
  return report;
}

test("a journal is created for the GM only, its Markdown page as HTML, then left alone", async () => {
  const w = world();
  const report = await realiseChecked(w, handout());
  assert.deepEqual(report.summary, { create: 1 });
  const [journal] = w.docs;
  assert.equal(report.document, journal.id);
  assert.deepEqual(journal.source.ownership, { default: 0 });
  assert.deepEqual(journal.source.pages[0].text, {
    content: "<p>Bring <b>100 gp</b>.</p>",
    format: 1,
  });
  assert.equal(journal.source.flags[MODULE].document, "ransom");
  assert.deepEqual((await realiseChecked(w, handout())).summary, { noop: 1 });
});

test("publishing a journal in play is not a retouch", async () => {
  const w = world();
  await realiseChecked(w, handout());
  await w.docs[0].update({ ownership: { default: 2 } }); // publish_journal
  assert.deepEqual((await realiseChecked(w, handout())).summary, { noop: 1 });
});

test("a prep change updates the document and replaces its pages wholesale", async () => {
  const w = world();
  await realiseChecked(w, handout());
  const [journal] = w.docs;
  const changed = handout();
  changed.data.pages = [
    { name: "Note", type: "text", text: { markdown: "Bring 200 gp." } },
    { name: "Map", type: "text", text: { markdown: "The mill." } },
  ];
  const report = await realiseChecked(w, changed);
  assert.deepEqual(report.summary, { update: 1 });
  assert.deepEqual(
    journal.source.pages.map((/** @type {any} */ p) => p.text.content),
    ["<p>Bring 200 gp.</p>", "<p>The mill.</p>"],
  );
  assert.deepEqual((await realiseChecked(w, changed)).summary, { noop: 1 });
});

test("a GM retouch is kept, and a prep change to it waits for the GM's choice", async () => {
  const w = world();
  await realiseChecked(w, handout());
  const [journal] = w.docs;
  await journal.update({ name: "Ransom (GM)" });
  assert.equal((await realiseChecked(w, handout())).summary.retouched, 1);

  const changed = handout();
  changed.data.name = "The ransom letter";
  assert.equal((await realiseChecked(w, changed)).summary.conflict, 1);
  assert.equal(journal.source.name, "Ransom (GM)");
  await realiseChecked(w, { ...changed, choice: "overwrite" });
  assert.equal(journal.source.name, "The ransom letter");
});

test("a document deleted in Foundry is not recreated, unless the GM chooses so", async () => {
  const w = world();
  await realiseChecked(w, handout());
  await w.docs[0].delete();
  const report = await realiseChecked(w, handout());
  assert.equal(report.actions[0].action, "kept-deleted");
  assert.equal(report.document, null);
  assert.equal((await realiseChecked(w, { ...handout(), choice: "recreate" })).summary.create, 1);
});

test("an actor is made from its compendium base, the prep's fields on top", async () => {
  const w = world();
  const base = "Compendium.pf2e.pathfinder-bestiary.Actor.goblin";
  const npc = { type: "Actor", base, data: { name: "Grik" } };
  await realiseChecked(w, npc, "grik");
  const [actor] = w.docs;
  assert.deepEqual([actor.source.name, actor.source.system.level], ["Grik", -1]);
  assert.equal(actor.source.flags.core.sourceId, base);
  assert.equal(actor.source.flags[MODULE].base, base);
  assert.deepEqual((await realiseChecked(w, npc, "grik")).summary, { noop: 1 });
});

test("a playlist stopped or played in Foundry is not a retouch", async () => {
  const w = world();
  const music = {
    type: "Playlist",
    data: { name: "Mill", mode: 0, sounds: [{ name: "Rain", path: "rain.ogg", repeat: true }] },
  };
  await realiseChecked(w, music, "mill");
  const [playlist] = w.docs;
  playlist.source.playing = true;
  playlist.source.sounds[0].playing = true;
  assert.deepEqual((await realiseChecked(w, music, "mill")).summary, { noop: 1 });
});

test("a document that cannot be written is reported", async () => {
  const w = world();
  w.deps.createDocument = async () => {
    throw new Error("validation failed: name");
  };
  const report = await realiseChecked(w, handout());
  assert.deepEqual(report.errors, ["ransom: validation failed: name"]);
});

test("@prepared references resolve to ids, a token's actor to a UUID, a sound by name", async () => {
  const w = world();
  await realiseChecked(w, { type: "Actor", data: { name: "Grik" } }, "grik");
  const mill = { type: "Playlist", data: { name: "Mill", sounds: [{ name: "Rain" }] } };
  await realiseChecked(w, mill, "mill");
  const [grik, playlist] = w.docs;
  const find = finder((key) => w.deps.findDocument(key));
  /** @type {string[]} */
  const errors = [];
  const scene = resolve(
    {
      scene: { name: "Mill", playlist: "@prepared:mill", playlistSound: "@prepared:mill/Rain" },
      items: [{ key: "grik", type: "Token", actor: "@prepared:grik", data: { x: 1 } }],
    },
    find,
    errors,
  );
  assert.deepEqual(scene.scene, {
    name: "Mill",
    playlist: playlist.id,
    playlistSound: playlist.source.sounds[0]._id,
  });
  assert.equal(scene.items[0].actor, `Actor.${grik.id}`);
  assert.deepEqual(errors, []);

  const missing = resolve(
    { playlist: "@prepared:nowhere", sound: "@prepared:mill/Wind" },
    find,
    errors,
  );
  assert.deepEqual(missing, { playlist: null, sound: null });
  assert.equal(errors.length, 2);
});

test("generic reads: files, compendium entries and world documents, bounded", async () => {
  const files = Array.from({ length: LIMIT + 5 }, (_, i) => `maps/m${i}.webp`);
  /** @type {unknown[]} */
  const browsed = [];
  const reads = genericReads({
    browse: async (source, path, options) => {
      browsed.push(source, path, options);
      return { dirs: ["maps/old"], files };
    },
    packs: () => [
      {
        collection: "pf2e.pathfinder-bestiary",
        documentName: "Actor",
        getIndex: async () => [
          {
            _id: "a1",
            name: "Goblin Warrior",
            type: "npc",
            img: "g.webp",
            system: {
              details: { level: { value: -1 } },
              traits: { rarity: "common", value: ["goblin"] },
            },
          },
          { _id: "a2", name: "Ogre", type: "npc" },
        ],
      },
      {
        collection: "pf2e.equipment-srd",
        documentName: "Item",
        getIndex: async () => [{ _id: "i1", name: "Goblin pick", type: "weapon" }],
      },
    ],
    documents: (type) =>
      type === "Actor"
        ? [
            /** @type {any} */ ({
              uuid: "Actor.x",
              id: "x",
              name: "Grik",
              flags: { [MODULE]: { document: "grik" } },
            }),
            /** @type {any} */ ({ uuid: "Actor.y", id: "y", name: "Valeros", flags: {} }),
          ]
        : null,
    imageSize: async (path) => ({ width: path.length * 100, height: 1000 }),
  });

  const listing = /** @type {any} */ (
    await reads.browse_files({ path: "maps", extensions: [".webp"] })
  );
  assert.deepEqual(browsed, ["data", "maps", { extensions: [".webp"] }]);
  assert.equal(listing.files.length, LIMIT);
  assert.equal(listing.more, 5);

  const goblins = /** @type {any[]} */ (await reads.search_compendium({ query: "GOBLIN" }));
  assert.deepEqual(goblins, [
    {
      uuid: "Compendium.pf2e.pathfinder-bestiary.Actor.a1",
      name: "Goblin Warrior",
      type: "npc",
      pack: "pf2e.pathfinder-bestiary",
      img: "g.webp",
      level: -1,
      rarity: "common",
      traits: ["goblin"],
    },
    {
      uuid: "Compendium.pf2e.equipment-srd.Item.i1",
      name: "Goblin pick",
      type: "weapon",
      pack: "pf2e.equipment-srd",
      img: null,
      level: null,
      rarity: null,
      traits: null,
    },
  ]);
  const npcs = /** @type {any[]} */ (await reads.search_compendium({ query: "o", type: "npc" }));
  assert.deepEqual(
    npcs.map((e) => e.name),
    ["Goblin Warrior", "Ogre"],
  );
  assert.equal(
    /** @type {any[]} */ (await reads.search_compendium({ query: "", limit: 1 })).length,
    1,
  );

  assert.deepEqual(await reads.list_world_documents({ type: "Actor", query: "gri" }), [
    { uuid: "Actor.x", id: "x", name: "Grik", prepared_key: "grik" },
  ]);
  await assert.rejects(reads.list_world_documents({ type: "Wallpaper" }));
  assert.deepEqual(await reads.image_size({ path: "maps/a.webp" }), { width: 1100, height: 1000 });
  await assert.rejects(reads.image_size({}));
});

test("prep never sets who sees a document: ownership is forced to the GM's only", async () => {
  const w = world();
  const shared = handout();
  /** @type {any} */ (shared.data).ownership = { default: 2 };
  /** @type {any} */ (shared.data.pages[0]).ownership = { default: 2 };
  await realiseChecked(w, shared);
  const [journal] = w.docs;
  assert.deepEqual(journal.source.ownership, { default: 0 });
  assert.equal(journal.source.pages[0].ownership, undefined);

  /** @type {any} */ (shared.data).name = "Renamed";
  /** @type {any} */ (shared.data).ownership = { default: 3 };
  await realiseChecked(w, shared);
  assert.deepEqual(journal.source.ownership, { default: 0 }); // nor on update
  assert.equal(journal.source.name, "Renamed");

  w.deps.fromBase = async (type, base, data) => ({
    ...(await world().deps.fromBase(type, base, data)),
    ownership: { default: 2 },
  });
  const npc = { type: "Actor", base: "Actor.shared1", data: { name: "Grik" } };
  await realiseChecked(w, npc, "grik");
  assert.deepEqual(w.docs[1].source.ownership, { default: 0 });
});

test("a page's HTML is sanitized, from Markdown or given as HTML", async () => {
  const w = world();
  const payload = 'Hi<script>alert(1)</script><img src="x" onerror="alert(1)">';
  const page = (/** @type {object} */ text) => ({ name: "P", type: "text", text });
  const desired = {
    type: "JournalEntry",
    data: { name: "Trap", pages: [page({ markdown: payload }), page({ content: payload })] },
  };
  await realiseChecked(w, desired);
  for (const { text } of w.docs[0].source.pages) {
    assert.doesNotMatch(text.content, /script|onerror/);
    assert.match(text.content, /<img src="x">/);
  }
});

test("ownership is dropped however its key is spelled, at the top and in pages", async () => {
  for (const [key, value] of /** @type {[string, unknown][]} */ ([
    ["ownership.default", 2],
    ["-=ownership", null],
    ["==ownership", { default: 2 }],
    ["ownership", { default: 2 }],
  ])) {
    const w = world();
    const desired = handout();
    /** @type {any} */ (desired.data)[key] = value;
    /** @type {any} */ (desired.data.pages[0])[key] = value;
    await realiseChecked(w, desired);
    const [journal] = w.docs;
    assert.deepEqual(journal.source.ownership, { default: 0 }, key);
    assert.deepEqual(
      Object.keys(journal.source).filter((k) => k.includes("ownership")),
      ["ownership"],
    );
    assert.ok(!Object.keys(journal.source.pages[0]).some((k) => k.includes("ownership")), key);
  }
});

test("every HTML string is sanitized, whatever field it is in", async () => {
  const w = world();
  const payload = '<p>Notes</p><img src="x" onerror="alert(1)">';
  await realiseChecked(
    w,
    { type: "Actor", data: { name: "Grik", system: { details: { publicNotes: payload } } } },
    "grik",
  );
  const item = { name: "Idol", "system.description.value": payload };
  await realiseChecked(w, { type: "Item", data: item }, "idol");
  const [actor, idol] = w.docs;
  for (const html of [
    actor.source.system.details.publicNotes,
    idol.source.system.description.value,
  ])
    assert.equal(html, '<p>Notes</p><img src="x">');
});

test("ownership is dropped at any depth, and an embedded field must be a list", async () => {
  const w = world();
  const desired = handout();
  /** @type {any} */ (desired.data).flags = {
    [MODULE]: { "-=ownership": null, deep: { ownership: 2 } },
  };
  /** @type {any} */ (desired.data.pages[0]).text.ownership = { default: 2 };
  await realiseChecked(w, desired);
  const [journal] = w.docs;
  assert.doesNotMatch(JSON.stringify(journal.source.pages), /ownership/);
  assert.deepEqual(journal.source.flags[MODULE].deep, {});
  assert.deepEqual(journal.source.ownership, { default: 0 });

  const dotted = { type: "JournalEntry", data: { name: "Map", "pages.0.ownership.default": 2 } };
  const other = world();
  await assert.rejects(realiseDocument("map", dotted, other.deps), /`pages` must be a list/);
  assert.equal(other.docs.length, 0);
});

test("a desired scene gets a document's guards: no ownership, clean HTML, no script region", () => {
  const { deps } = world();
  const payload = '<p>Lair</p><img src="x" onerror="alert(1)">';
  const guarded = guardedScene(
    {
      scene: { name: "Cave", "ownership.default": 2, navName: payload },
      items: [
        { key: "note", type: "Note", data: { x: 1, y: 1, text: payload, "-=ownership": null } },
        { key: "sign", type: "Drawing", data: { text: payload, flags: { m: { ownership: 3 } } } },
      ],
    },
    deps,
  );
  assert.deepEqual(guarded.scene, { name: "Cave", navName: '<p>Lair</p><img src="x">' });
  assert.deepEqual(guarded.items[0].data, { x: 1, y: 1, text: '<p>Lair</p><img src="x">' });
  assert.deepEqual(guarded.items[1].data.flags, {}); // not the module's namespace

  const flagged = {
    key: "f",
    type: "Tile",
    data: { flags: { pf2e: { x: 1 }, [MODULE]: { y: 2 } } },
  };
  assert.deepEqual(
    guardedScene({ scene: { name: "Cave" }, items: [flagged] }, deps).items[0].data,
    {
      flags: { [MODULE]: { y: 2 } },
    },
  );
  const dotted = { key: "d", type: "Tile", data: { "flags.pf2e.x": 1 } };
  assert.deepEqual(guardedScene({ scene: { name: "Cave" }, items: [dotted] }, deps).items[0].data, {
    flags: {},
  });

  /** @param {any} data */
  const region = (data) => ({
    scene: { name: "Cave" },
    items: [{ key: "r", type: "Region", data }],
  });
  const allowed = region({ behaviors: [{ type: "pauseGame", system: { once: true } }] });
  assert.equal(guardedScene(allowed, deps).items[0].data.behaviors[0].type, "pauseGame");
  for (const [data, error] of /** @type {[any, RegExp][]} */ ([
    [{ behaviors: [{ type: "executeScript" }] }, /executeScript/],
    [{ behaviors: [{ type: "executeMacro" }] }, /executeMacro/],
    [{ behaviors: [{ type: "my-module.run" }] }, /my-module/],
    [{ "behaviors.0.type": "executeScript" }, /must be a list/],
    [{ behaviors: { 0: { type: "pauseGame" } } }, /must be a list/],
    [{ behaviors: ["pauseGame"] }, /must be a list/],
    [{ "==behaviors": [] }, /operator/],
  ]))
    assert.throws(() => guardedScene(region(data), deps), error);
  for (const scene of [
    { name: "Cave", tokens: [{ name: "x" }] },
    { name: "Cave", "walls.0.c": [0, 0, 1, 1] },
    { name: "Cave", levels: [{ background: { src: "x" } }] },
    { name: "Cave", "-=regions": null },
  ])
    assert.throws(() => guardedScene({ scene, items: [] }, deps), /as items|operator/);
});

test("a read path stays in Foundry's data: no URL, scheme, absolute path or ..", async () => {
  const origin = "https://foundry.example";
  for (const ok of [
    "",
    "maps",
    "modules/pf2e-beginner-box/assets/map.webp",
    "a..b/c.webp",
    "modules/x/Log%20Fume%20-%20Tower/map.webp", // Foundry lists paths encoded
  ])
    assert.equal(dataPath(ok, origin), ok);
  const reads = genericReads({
    browse: async () => ({ dirs: [], files: [] }),
    packs: () => [],
    documents: () => null,
    imageSize: async () => ({ width: 1, height: 1 }),
    origin,
  });
  for (const bad of [
    " //evil.example/x.png", // the URL parser drops the leading space: another origin
    "https://evil.example/x.png",
    "http:x.png",
    "data:image/png;base64,AAAA",
    "blob:abc",
    "file:///etc/passwd",
    "//evil.example/x.png",
    "/etc/passwd",
    "\\server\\x.png",
    "maps/../../x.png",
    "..",
    "maps\\..\\x.png",
    "maps/%2e%2e/x.png",
    "https%3A//evil.example/x.png",
    "%2Fetc/passwd",
    "maps/x.png%0a",
    "%E0%A4%A",
  ]) {
    await assert.rejects(reads.image_size({ path: bad }), /relative/, bad);
    await assert.rejects(reads.browse_files({ path: bad }), /relative/, bad);
  }
  await assert.rejects(reads.browse_files({ path: "maps", source: "s3" }), /data or public/);
});

test("prep keeps only the module's flags, never its identity ones, nor any update operator", async () => {
  const w = world();
  const desired = handout();
  /** @type {any} */ (desired.data).flags = {
    pf2e: { x: 1 },
    [MODULE]: { note: "mine", document: "other", spec: "s", shape: "{}", local: "l" },
  };
  /** @type {any} */ (desired.data.pages[0]).flags = { core: { x: 1 }, [MODULE]: { key: "k" } };
  await realiseChecked(w, desired);
  const [journal] = w.docs;
  assert.equal(journal.source.flags.pf2e, undefined);
  assert.equal(journal.source.flags[MODULE].note, "mine");
  assert.equal(journal.source.flags[MODULE].document, "ransom"); // reconciliation's, not prep's
  assert.deepEqual(journal.source.pages[0].flags, {});

  for (const data of [
    { name: "x", system: { "-=hp": null } },
    { name: "x", pages: [{ name: "p", text: { "==content": "" } }] },
  ]) {
    const other = world();
    await assert.rejects(
      realiseDocument("x", { type: "JournalEntry", data }, other.deps),
      /operator/,
    );
  }

  const { deps } = world();
  const scene = (/** @type {any} */ items, head = {}) => ({ scene: { name: "C", ...head }, items });
  const guarded = guardedScene(
    scene(
      [{ key: "t", type: "Tile", data: { flags: { [MODULE]: { key: "x", spec: "s", a: 1 } } } }],
      {
        flags: { core: {}, [MODULE]: { scene: "forged" } },
      },
    ),
    deps,
  );
  assert.deepEqual(guarded.scene.flags, {});
  assert.deepEqual(guarded.items[0].data.flags, { [MODULE]: { a: 1 } });
  assert.throws(
    () =>
      guardedScene(scene([{ key: "t", type: "Tile", data: { texture: { "-=src": null } } }]), deps),
    /operator/,
  );
  assert.throws(
    () => guardedScene(scene([{ key: "g", type: "Token", data: { delta: { name: "x" } } }]), deps),
    /delta/,
  );
  assert.throws(
    () => guardedScene(scene([{ key: "g", type: "Token", data: { actorData: { a: 1 } } }]), deps),
    /delta/,
  );
  for (const type of ["modifyMovementCost", "pauseGame"]) {
    const region = { key: "r", type: "Region", data: { behaviors: [{ type }] } };
    assert.equal(guardedScene(scene([region]), deps).items[0].data.behaviors[0].type, type);
  }
  const toggle = { key: "r", type: "Region", data: { behaviors: [{ type: "toggleBehavior" }] } };
  assert.throws(() => guardedScene(scene([toggle]), deps), /toggleBehavior/);
});
