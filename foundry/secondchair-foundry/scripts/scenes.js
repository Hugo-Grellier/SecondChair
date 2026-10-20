// Realising a prepared scene by reconciliation (ARC-10, docs/contracts/foundry-bridge.md).
// The reconciliation is transplanted from v3 (BVE-02): every object prep places carries a stable
// key and two fingerprints, `spec` (what prep asked for) and `local` (what was written, read back
// from Foundry, play state left out). An object the GM retouched since is kept; one deleted in
// Foundry (killed, picked up, removed by the GM) is never silently recreated. Free of Foundry
// globals: the Foundry calls are passed in, so it runs under `node --test`.

export const MODULE = "secondchair-foundry";

/** The embedded documents a desired scene may place. */
export const TYPES = [
  "Token",
  "Wall",
  "AmbientLight",
  "AmbientSound",
  "Note",
  "Tile",
  "Drawing",
  "Region",
];

/** Play state, left out of the local fingerprint and never rewritten: changing it in play is not
 * a retouch of the prep. `a.b` names field `b` of `a`, or of each element when `a` is a list. */
/** @type {Record<string, string[]>} */
export const PLAYED = {
  Wall: ["ds"],
  AmbientLight: ["hidden"],
  AmbientSound: ["hidden"],
  Tile: ["hidden"],
  Drawing: ["hidden"],
  Region: ["behaviors.disabled"],
  Token: ["x", "y", "elevation", "hidden", "rotation", "delta", "sort"],
  // World documents (documents.js): who sees one is a disclosure in play (publish_journal).
  JournalEntry: ["ownership"],
  Actor: ["ownership"],
  Item: ["ownership"],
  Playlist: ["ownership", "playing", "sounds.playing", "sounds.pausedTime"],
  RollTable: ["ownership", "results.drawn"],
};

/**
 * @typedef {Record<string, any>} Data
 * @typedef {{key: string, type: string, spec: string}} Wanted
 * @typedef {{key: string, type: string, id: string, spec: string, local: string | null, current: string}} Existing
 * @typedef {"keep" | "overwrite" | "recreate"} Choice
 * @typedef {{action: string, key: string, type: string, id?: string, spec?: string, reason?: string}} Action
 * @typedef {{key: string, type: string, actor?: string, data: Data}} Item
 * @typedef {{scene: Data, items: Item[], choices?: Record<string, Choice>}} Desired
 * @typedef {{scene: string, summary: Record<string, number>, actions: {action: string, key: string, reason?: string}[], errors: string[]}} Report
 * @typedef {{id: string, flags: Data, toObject(): Data, update(changes: Data): Promise<unknown>}} Doc
 * @typedef {Doc & {
 *   getEmbeddedCollection(type: string): Iterable<Doc>,
 *   createEmbeddedDocuments(type: string, data: Data[]): Promise<Doc[]>,
 *   updateEmbeddedDocuments(type: string, updates: Data[]): Promise<unknown>,
 *   deleteEmbeddedDocuments(type: string, ids: string[]): Promise<unknown>,
 * }} SceneDoc
 * @typedef {{
 *   findScene(key: string): SceneDoc | null | Promise<SceneDoc | null>,
 *   createScene(data: Data): Promise<SceneDoc>,
 *   tokenData(item: Item): Promise<Data>,
 *   levels?: boolean,
 * }} World
 */

/** A stable text for a value, whatever its key order. @param {unknown} value @returns {string} */
export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const obj = /** @type {Data} */ (value);
    return `{${Object.keys(obj)
      .sort()
      .filter((k) => obj[k] !== undefined)
      .map((k) => `${JSON.stringify(k)}:${canonical(obj[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

/** A copy without the play state fields. @param {string} type @param {Data} data */
export function withoutPlayed(type, data) {
  const copy = structuredClone(data);
  for (const path of PLAYED[type] ?? []) {
    const [head, tail] = path.split(".");
    if (!tail) delete copy[head];
    else for (const el of [copy[head]].flat()) if (el && typeof el === "object") delete el[tail];
  }
  return copy;
}

/**
 * What to do with each object. v3's contract, unchanged.
 * @param {Wanted[]} desired  what prep wants
 * @param {Existing[]} existing  the scene's objects carrying a key
 * @param {Record<string, boolean>} created  keys already created once in this scene
 * @param {Record<string, Choice>} choices  the GM's calls on conflicts and deletions
 * @returns {Action[]}
 */
export function reconcile(desired, existing, created = {}, choices = {}) {
  const byKey = new Map(existing.map((e) => [e.key, e]));
  /** @type {Action[]} */
  const actions = [];
  /** @type {Existing[]} */
  const replaced = []; // prep changed the object's type: the old one goes, a new one is made
  for (const { key, type, spec } of desired) {
    const have = byKey.get(key);
    byKey.delete(key);
    if (have && have.type !== type) {
      replaced.push(have);
      actions.push({ action: "create", key, type, spec });
      continue;
    }
    if (!have) {
      if (created[key] && choices[key] !== "recreate") {
        const reason = "deleted in the VTT since it was prepared (played or removed by the GM)";
        actions.push({ action: "kept-deleted", key, type, reason: `${reason}: not recreated` });
      } else {
        actions.push({ action: "create", key, type, spec });
      }
      continue;
    }
    const { id } = have;
    const retouched = Boolean(have.local) && have.current !== have.local;
    const changed = have.spec !== spec;
    if (!changed && !retouched) actions.push({ action: "noop", key, type, id });
    else if (!changed) {
      const reason = "retouched in the VTT, prep unchanged: kept";
      actions.push({ action: "retouched", key, type, id, reason });
    } else if (!retouched || choices[key] === "overwrite") {
      actions.push({ action: "update", key, type, id, spec });
    } else if (choices[key] === "keep") {
      const reason = "conflict settled by the GM: the VTT's version kept";
      actions.push({ action: "retouched", key, type, id, reason });
    } else {
      const reason = "retouched in the VTT and changed in prep";
      actions.push({ action: "conflict", key, type, id, spec, reason });
    }
  }
  for (const { key, type, id, local, current } of [...replaced, ...byKey.values()]) {
    if (!local || current === local || choices[key] === "overwrite") {
      actions.push({ action: "delete", key, type, id });
    } else {
      const reason = "removed from prep but retouched in the VTT";
      actions.push({ action: "conflict", key, type, id, reason });
    }
  }
  return actions;
}

/** @param {{action: string}[]} actions */
export function summary(actions) {
  /** @type {Record<string, number>} */
  const counts = {};
  for (const { action } of actions) counts[action] = (counts[action] ?? 0) + 1;
  return counts;
}

/** @param {string} text */
export async function sha(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 16);
}

/** `value` cut to the fields `shape` sets: only what prep wrote is compared.
 * @param {any} value @param {any} shape @returns {any} */
function project(value, shape) {
  if (Array.isArray(shape))
    return Array.isArray(value) ? shape.map((s, i) => project(value[i], s)) : value;
  if (shape && typeof shape === "object") {
    if (!value || typeof value !== "object") return value;
    return Object.fromEntries(Object.keys(shape).map((k) => [k, project(value[k], shape[k])]));
  }
  return value;
}

/** The local fingerprint: the fields prep wrote, as the VTT holds them now, play state left out.
 * @param {string} type @param {Doc} doc @param {Data} shape */
export const local = (type, doc, shape) =>
  sha(canonical(withoutPlayed(type, project(doc.toObject(), shape))));

/** The id of the level Foundry 14 gives a new scene. */
const DEFAULT_LEVEL = "defaultLevel0000";

/** The fields of a scene's map, which Foundry 14 keeps in the scene's default level. */
const MAP = ["background", "foreground"];

/** A desired scene head, as Foundry writes it: with levels, the map goes to the default level,
 * `levels[0]`, and `background` on the Scene is ignored.
 * @param {Data} head @param {Data | null} scene  the scene as it is now, null to create it
 * @param {boolean} levels */
export function headWritten(head, scene, levels) {
  if (!levels || !MAP.some((k) => k in head)) return { ...head };
  const rest = Object.fromEntries(Object.entries(head).filter(([k]) => !MAP.includes(k)));
  const _id = scene?.levels?.[0]?._id ?? DEFAULT_LEVEL;
  const map = Object.fromEntries(MAP.filter((k) => k in head).map((k) => [k, head[k]]));
  // ponytail: a parent update with an embedded entry's _id updates that level only.
  return { ...rest, levels: [{ _id, ...map }] };
}

/** A scene as prep reads it back: with levels, its map is its default level's.
 * @param {Data} scene @param {boolean} levels */
export function headRead(scene, levels) {
  if (!levels) return scene;
  const level = scene.levels?.[0] ?? {};
  return { ...scene, background: level.background, foreground: level.foreground };
}

/** @param {SceneDoc} scene @param {string} type @param {string} id */
const embedded = (scene, type, id) =>
  /** @type {Doc} */ ([...scene.getEmbeddedCollection(type)].find((d) => d.id === id));

/** Our flags: the shape is kept as text, so an update replaces it instead of merging it.
 * @param {Data} fields */
export const ours = (fields) => ({ flags: { [MODULE]: fields } });

/** `data`'s flags with ours added, its own flags in our namespace kept, ours winning.
 * @param {Data} data @param {Data} fields */
export const withOurs = (data, fields) => ({
  ...data.flags,
  [MODULE]: { ...data.flags?.[MODULE], ...fields },
});

/**
 * Realise one desired scene: create it, or reconcile it with what the VTT holds now.
 * @param {string} key  the scene's key in the workspace
 * @param {Desired} desired
 * @param {World} world
 * @returns {Promise<Report>}
 */
export async function realise(key, desired, { findScene, createScene, tokenData, levels = false }) {
  const choices = desired.choices ?? {};
  const head = desired.scene;
  const headSpec = await sha(canonical(head));
  /** @type {Action[]} */
  const actions = [];
  /** @type {string[]} */
  const errors = [];
  let scene = await findScene(key);
  /** @param {SceneDoc} s @returns {Doc} the scene as prep reads it back */
  const asRead = (s) => ({ ...s, toObject: () => headRead(s.toObject(), levels) });
  if (!scene) {
    // With levels, the map goes into the default level the new scene comes with.
    const { levels: _, ...fields } = headWritten(head, null, levels);
    scene = await createScene({ ...fields, flags: withOurs(fields, { scene: key, created: {} }) });
    if (levels) await scene.update(headWritten(head, scene.toObject(), levels));
    actions.push({ action: "create", key: "_scene", type: "Scene" });
  } else {
    const f = scene.flags[MODULE];
    const current = await local("Scene", asRead(scene), JSON.parse(f.shape ?? "{}"));
    const have = {
      key: "_scene",
      type: "Scene",
      id: scene.id,
      spec: f.spec,
      local: f.local,
      current,
    };
    actions.push(
      ...reconcile([{ key: "_scene", type: "Scene", spec: headSpec }], [have], {}, choices),
    );
    if (actions[0].action === "update")
      await scene.update(headWritten(head, scene.toObject(), levels));
  }
  if (["create", "update"].includes(actions[0].action)) {
    await scene.update(ours({ spec: headSpec, shape: JSON.stringify(head) }));
    await scene.update(ours({ local: await local("Scene", asRead(scene), head) }));
  }

  const items = new Map(desired.items.map((item) => [item.key, item]));
  /** @type {Wanted[]} */
  const wanted = [];
  for (const { key: k, type, actor, data } of desired.items) {
    wanted.push({ key: k, type, spec: await sha(canonical({ actor: actor ?? null, data })) });
  }
  /** @type {Existing[]} */
  const existing = [];
  for (const type of TYPES) {
    for (const doc of scene.getEmbeddedCollection(type)) {
      const f = doc.flags?.[MODULE];
      if (!f?.key) continue;
      const current = await local(type, doc, JSON.parse(f.shape));
      existing.push({
        key: f.key,
        type,
        id: doc.id,
        spec: f.spec,
        local: f.local ?? null,
        current,
      });
    }
  }
  /** @type {Record<string, boolean>} */
  const created = { ...scene.flags[MODULE]?.created };
  for (const action of reconcile(wanted, existing, created, choices)) {
    actions.push(action);
    const { key: k, type, id, spec } = action;
    const item = /** @type {Item} */ (items.get(k));
    try {
      let doc;
      if (action.action === "create") {
        const data = type === "Token" && item.actor ? await tokenData(item) : item.data;
        const flags = withOurs(data, { key: k, spec, shape: JSON.stringify(item.data) });
        [doc] = await scene.createEmbeddedDocuments(type, [{ ...data, flags }]);
        created[k] = true;
      } else if (action.action === "update") {
        /** @type {Data} */
        const changes = { _id: id, ...withoutPlayed(type, item.data) }; // play state stays
        if (type === "Token" && item.actor) changes.actorId = (await tokenData(item)).actorId;
        await scene.updateEmbeddedDocuments(type, [
          { ...changes, ...ours({ spec, shape: JSON.stringify(item.data) }) },
        ]);
        doc = embedded(scene, type, /** @type {string} */ (id));
      } else if (action.action === "delete") {
        await scene.deleteEmbeddedDocuments(type, [/** @type {string} */ (id)]);
        // Dropped from prep, not played: added back later, it is created again. False, not
        // deleted, since Foundry merges flag updates.
        if (!items.has(k)) created[k] = false;
      }
      if (doc) await doc.update(ours({ local: await local(type, doc, item.data) }));
    } catch (err) {
      errors.push(`${k}: ${/** @type {Error} */ (err)?.message ?? err}`);
    }
  }
  await scene.update(ours({ created }));
  return {
    scene: scene.id,
    summary: summary(actions),
    actions: actions.map(({ action, key: k, reason }) => ({
      action,
      key: k,
      ...(reason && { reason }),
    })),
    errors,
  };
}
