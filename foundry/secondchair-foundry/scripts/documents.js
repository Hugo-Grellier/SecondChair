// Realising a prepared world document (a journal, an actor, an item, a playlist, a roll table) by
// the reconciliation scenes.js runs on a scene's objects (ARC-10, docs/contracts/foundry-bridge.md),
// resolving the `@prepared:` references of a desired state, and the library's generic reads, which
// find what the GM's install holds (ARC-07). Free of Foundry globals: the Foundry calls are passed
// in, so it runs under `node --test`.

import {
  canonical,
  local,
  MODULE,
  ours,
  reconcile,
  sha,
  summary,
  withoutPlayed,
} from "./scenes.js";

/** The world document types prep may prepare. */
export const DOCUMENT_TYPES = ["JournalEntry", "Actor", "Item", "Playlist", "RollTable"];

/** Each type's embedded collection prep may give: its field, its document type. */
/** @type {Record<string, [string, string]>} */
export const EMBEDDED = {
  JournalEntry: ["pages", "JournalEntryPage"],
  Playlist: ["sounds", "PlaylistSound"],
  Actor: ["items", "Item"],
  RollTable: ["results", "TableResult"],
};

/** Foundry's HTML page format (CONST.JOURNAL_ENTRY_PAGE_FORMATS.HTML). */
const HTML = 1;

/** A string value standing for a prepared document: `@prepared:<key>`, `@prepared:<key>/<sound>`. */
export const PREPARED = "@prepared:";

/**
 * @typedef {import("./scenes.js").Data} Data
 * @typedef {import("./scenes.js").Choice} Choice
 * @typedef {import("./scenes.js").SceneDoc & {documentName: string, uuid: string, name?: string, delete(): Promise<unknown>}} WorldDoc
 * @typedef {{type: string, base?: string, data: Data, choice?: Choice}} Desired
 * @typedef {{document: string | null, summary: Record<string, number>, actions: {action: string, key: string, reason?: string}[], errors: string[]}} Report
 * @typedef {{
 *   findDocument(key: string): WorldDoc | null | Promise<WorldDoc | null>,
 *   createDocument(type: string, data: Data): Promise<WorldDoc>,
 *   fromBase(type: string, base: string, data: Data): Promise<Data>,
 *   markdown(text: string): string,
 *   clean(html: string): string,
 *   expand(data: Data): Data,
 *   created: {load(): Record<string, boolean>, save(created: Record<string, boolean>): Promise<unknown>},
 * }} World
 */

/**
 * `value` with each `@prepared:` string replaced by what `find` gives for it: an `actor` field
 * (a Token's) by the document's UUID, any other by its id. One `find` knows nothing of is null,
 * and an error says so.
 * @param {any} value
 * @param {(ref: string, uuid: boolean) => string | null} find
 * @param {string[]} errors  where unresolved references are reported
 * @returns {any}
 */
export function resolve(value, find, errors, uuid = false) {
  if (typeof value === "string" && value.startsWith(PREPARED)) {
    const found = find(value.slice(PREPARED.length), uuid);
    if (found === null) errors.push(`${value}: no such prepared document realised in this world`);
    return found;
  }
  if (Array.isArray(value)) return value.map((v) => resolve(v, find, errors));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, resolve(v, find, errors, k === "actor")]),
    );
  }
  return value;
}

/**
 * The `find` of `resolve` over the realised documents: `<key>` a document, `<key>/<name>` the
 * sound of that name in a playlist.
 * @param {(key: string) => WorldDoc | null} findDocument
 * @returns {(ref: string, uuid: boolean) => string | null}
 */
export function finder(findDocument) {
  return (ref, uuid) => {
    const [key, sound] = ref.split(/\/(.*)/s);
    const doc = findDocument(key);
    if (!doc) return null;
    if (sound === undefined) return uuid ? doc.uuid : doc.id;
    const found = [...doc.getEmbeddedCollection("PlaylistSound")].find(
      (s) => /** @type {any} */ (s).name === sound,
    );
    return found?.id ?? null;
  };
}

/** A key setting who sees a document, as Foundry reads it: `ownership`, `-=ownership`, `==ownership`. */
const OWNERSHIP = /^(-=|==)?ownership$/;

/** `value` with every string holding HTML sanitized: any may land in an HTMLField.
 * @param {any} value @param {(html: string) => string} clean @returns {any} */
function cleaned(value, clean) {
  if (typeof value === "string") return value.includes("<") ? clean(value) : value;
  if (Array.isArray(value)) return value.map((v) => cleaned(v, clean));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, cleaned(v, clean)]));
  }
  return value;
}

/** `value` with dotted keys expanded as Foundry would, then its ownership keys dropped at every
 * depth, embedded documents included (`pages.0.ownership` too).
 * @param {any} value @param {(data: Data) => Data} expand @returns {any} */
function unowned(value, expand) {
  if (Array.isArray(value)) return value.map((v) => unowned(v, expand));
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(expand(value))
      .filter(([k]) => !OWNERSHIP.test(k))
      .map(([k, v]) => [k, unowned(v, expand)]),
  );
}

/**
 * `data` as Foundry stores it: no `ownership` anywhere, since who sees a document is a disclosure
 * only `publish_journal` makes (DEL-09); every string holding HTML sanitized, so a prepared
 * document runs no script in the GM's or a player's client; a journal's Markdown pages turned
 * into HTML ones.
 * @param {string} type @param {Data} data
 * @param {{markdown(text: string): string, clean(html: string): string, expand(data: Data): Data}} html
 */
export function written(type, data, { markdown, clean, expand }) {
  const rest = cleaned(unowned(data, expand), clean);
  const [field] = EMBEDDED[type] ?? [];
  if (field && field in rest && !Array.isArray(rest[field])) {
    throw new Error(`\`${field}\` must be a list of ${EMBEDDED[type][1]} documents.`);
  }
  if (!field || !rest[field]) return rest;
  rest[field] = rest[field].map((/** @type {Data} */ e) => {
    const md = e.text?.markdown;
    if (type !== "JournalEntry" || typeof md !== "string") return e;
    const { markdown: _, ...text } = e.text;
    return { type: "text", ...e, text: { ...text, content: clean(markdown(md)), format: HTML } };
  });
  return rest;
}

/** The Region behaviour types prep may place; any other (executeScript, executeMacro, a
 * module's) could run code in every client. */
export const BEHAVIORS = [
  "adjustDarknessLevel",
  "displayScrollingText",
  "pauseGame",
  "suppressWeather",
  "teleportToken",
  "toggleBehavior",
];

/** A Scene's embedded collections: what it places only arrives as an item. */
export const SCENE_EMBEDDED = [
  "drawings",
  "levels",
  "lights",
  "notes",
  "regions",
  "sounds",
  "templates",
  "tiles",
  "tokens",
  "walls",
];

/** Foundry's update operators: `-=key` deletes, `==key` replaces. Never prep's in a scene. */
const OPERATOR = /^(-=|==)/;

/**
 * A desired scene under a prepared document's guards: no ownership at any depth, every HTML
 * string sanitized (a Note's text, a Tile's or Drawing's text); no update operator, and no
 * embedded collection in the scene itself; only the module's own flags on an item; a Region's
 * behaviours a list of the allowed types only. Refused as a whole: prep never writes one.
 * @param {import("./scenes.js").Desired} desired
 * @param {{clean(html: string): string, expand(data: Data): Data}} html
 * @returns {import("./scenes.js").Desired}
 */
export function guardedScene(desired, { clean, expand }) {
  /** @param {string} what @param {Data} data */
  const guard = (what, data) => {
    const safe = cleaned(unowned(data, expand), clean);
    const operator = Object.keys(safe).find((k) => OPERATOR.test(k));
    if (operator) throw new Error(`${what}: no update operator (${operator}) in prep.`);
    return safe;
  };
  const scene = guard("_scene", desired.scene);
  const placed = Object.keys(scene).filter((k) => SCENE_EMBEDDED.includes(k));
  if (placed.length)
    throw new Error(`_scene: place ${placed.join(", ")} as items, not in the scene.`);
  const items = desired.items.map((item) => {
    const data = guard(item.key, item.data);
    if (data.flags) data.flags = data.flags[MODULE] ? { [MODULE]: data.flags[MODULE] } : {};
    if ("behaviors" in data) {
      const list = data.behaviors;
      const plain = (/** @type {any} */ b) => b && typeof b === "object" && !Array.isArray(b);
      if (!Array.isArray(list) || !list.every(plain)) {
        throw new Error(`${item.key}: \`behaviors\` must be a list of behaviours.`);
      }
      const refused = list.find((b) => !BEHAVIORS.includes(b.type));
      if (refused) {
        throw new Error(`${item.key}: a Region behaviour of type "${refused.type}" is not prep's.`);
      }
    }
    return { ...item, data };
  });
  return { ...desired, scene, items };
}

/**
 * Realise one desired world document: create it, or reconcile it with what the VTT holds now.
 * It is found by its key in its `secondchair-foundry` flags, as a scene's objects are.
 * @param {string} key  the document's key in the workspace
 * @param {Desired} desired  its `@prepared:` references already resolved
 * @param {World} world
 * @returns {Promise<Report>}
 */
export async function realiseDocument(key, desired, world) {
  const { type, base } = desired;
  const data = written(type, desired.data, world);
  const spec = await sha(canonical({ base: base ?? null, data: desired.data }));
  const doc = await world.findDocument(key);
  /** @type {import("./scenes.js").Existing[]} */
  const existing = [];
  if (doc) {
    const f = doc.flags[MODULE];
    const current = await local(doc.documentName, doc, JSON.parse(f.shape ?? "{}"));
    const { documentName, id } = doc;
    existing.push({ key, type: documentName, id, spec: f.spec, local: f.local ?? null, current });
  }
  const created = { ...world.created.load() };
  const choices = desired.choice ? { [key]: desired.choice } : {};
  const actions = reconcile([{ key, type, spec }], existing, created, choices);
  /** @type {string[]} */
  const errors = [];
  /** @type {WorldDoc | null} */
  let realised = doc;
  for (const action of actions) {
    try {
      /** @type {WorldDoc | null} */
      let target = null;
      if (action.action === "create") {
        const made = base ? await world.fromBase(type, base, data) : data;
        const { flags } = ours({
          document: key,
          spec,
          shape: JSON.stringify(data),
          ...(base && { base }),
        });
        target = await world.createDocument(type, {
          ...made,
          ownership: { default: 0 }, // the GM's only, whatever its base, until publish_journal
          flags: { ...made.flags, ...flags },
        });
        realised = target;
        created[key] = true;
      } else if (action.action === "update" && doc) {
        const changes = withoutPlayed(type, data); // play state stays
        const [field, embedded] = EMBEDDED[type] ?? [];
        const replaced = field ? changes[field] : undefined;
        if (field) delete changes[field];
        await doc.update({ ...changes, ...ours({ spec, shape: JSON.stringify(data) }) });
        if (Array.isArray(replaced)) {
          // ponytail: pages, sounds, items and results are replaced wholesale, so their ids
          // change (links to a page break); diff them by name if the GM links to them.
          const ids = [...doc.getEmbeddedCollection(embedded)].map((d) => d.id);
          await doc.deleteEmbeddedDocuments(embedded, ids);
          await doc.createEmbeddedDocuments(embedded, replaced);
        }
        target = doc;
      } else if (action.action === "delete" && doc) {
        await doc.delete(); // prep changed its type: the new one replaces it
      }
      if (target) await target.update(ours({ local: await local(type, target, data) }));
    } catch (err) {
      errors.push(`${key}: ${/** @type {Error} */ (err)?.message ?? err}`);
    }
  }
  await world.created.save(created);
  return {
    document: realised?.id ?? null,
    summary: summary(actions),
    actions: actions.map(({ action, reason }) => ({ action, key, ...(reason && { reason }) })),
    errors,
  };
}

/** The index fields search_compendium reads: pf2e's level (an actor's, an item's), rarity, traits. */
const INDEXED = [
  "type",
  "img",
  "system.details.level.value",
  "system.level.value",
  "system.traits.rarity",
  "system.traits.value",
];

/** The most entries one generic read returns, so an MCP reply stays small. */
export const LIMIT = 100;

/** @param {unknown} name @param {string} query */
const matches = (name, query) =>
  String(name ?? "")
    .toLowerCase()
    .includes(query.toLowerCase());

/**
 * The library's generic reads (ARC-07), answered before the system adapter's.
 * @param {object} env
 * @param {(source: string, path: string, options: {extensions?: string[]}) => Promise<{dirs?: string[], files?: string[]}>} env.browse
 *   Foundry's file picker browse
 * @param {() => Iterable<{collection: string, documentName: string, getIndex(options: {fields: string[]}): Promise<Iterable<Data>>}>} env.packs
 * @param {(type: string) => Iterable<WorldDoc> | null} env.documents  a world collection
 * @param {(path: string) => Promise<{width: number, height: number}>} env.imageSize
 *   an image's or video's size in pixels, loaded in the GM's client
 * @returns {Record<string, (params: Data) => Promise<unknown>>}
 */
export function genericReads({ browse, packs, documents, imageSize }) {
  /** @param {string[]} list */
  const cut = (list) => list.slice(0, LIMIT);
  return {
    async browse_files({ path = "", source = "data", extensions = null }) {
      const options = Array.isArray(extensions) ? { extensions } : {};
      const { dirs = [], files = [] } = await browse(String(source), String(path), options);
      const more = Math.max(0, dirs.length - LIMIT) + Math.max(0, files.length - LIMIT);
      return { dirs: cut(dirs), files: cut(files), ...(more && { more }) };
    },
    // ponytail: reads every pack's index on each call; cache it if searches become frequent.
    async search_compendium({ query = "", type = null, limit = 20 }) {
      const max = Math.min(Math.max(1, Number(limit) || 20), LIMIT);
      /** @type {Data[]} */
      const found = [];
      for (const pack of packs()) {
        const index = await pack.getIndex({ fields: [...INDEXED] });
        for (const entry of index) {
          if (!matches(entry.name, String(query))) continue;
          if (type && type !== pack.documentName && type !== entry.type) continue;
          found.push({
            uuid: entry.uuid ?? `Compendium.${pack.collection}.${pack.documentName}.${entry._id}`,
            name: entry.name,
            type: entry.type ?? pack.documentName,
            pack: pack.collection,
            img: entry.img ?? null,
            // pf2e's, null in a system without them: prep calibrates encounters from levels.
            level: entry.system?.details?.level?.value ?? entry.system?.level?.value ?? null,
            rarity: entry.system?.traits?.rarity ?? null,
            traits: entry.system?.traits?.value ?? null,
          });
          if (found.length >= max) return found;
        }
      }
      return found;
    },
    async image_size({ path }) {
      if (typeof path !== "string" || !path) throw new Error("image_size needs a `path`.");
      const { width, height } = await imageSize(path);
      return { width, height };
    },
    async list_world_documents({ type, query = "" }) {
      const collection = documents(String(type));
      if (!collection) throw new Error(`No world documents of type "${type}".`);
      return [...collection]
        .filter((doc) => matches(doc.name, String(query)))
        .slice(0, LIMIT)
        .map((doc) => {
          const f = doc.flags?.[MODULE];
          return {
            uuid: doc.uuid,
            id: doc.id,
            name: doc.name,
            prepared_key: f?.document ?? f?.scene ?? null,
          };
        });
    },
  };
}
