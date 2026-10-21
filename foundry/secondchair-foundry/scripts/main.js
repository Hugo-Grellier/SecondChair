// secondchair-foundry: the active GM's browser dials the loopback Core (ADR 0010).
import { aboveCeiling, CEILING, createActions, missingTranslation } from "./actions.js";
import { connect, coreUrl, hello } from "./bridge.js";
import { createCapture, visibilityOf } from "./capture.js";
import { createDesk, deskHtml, esc } from "./desk.js";
import {
  DOCUMENT_TYPES,
  finder,
  genericReads,
  guardedScene,
  realiseDocument,
  resolve,
} from "./documents.js";
import { MODULE, realise } from "./scenes.js";
import { createOutbox, createRecorder, describe, keyInput } from "./traces.js";

/** @typedef {import("./actions.js").Adapter} Adapter @typedef {import("./actions.js").Doc} Doc */

// Players reach the active GM's client through Foundry queries, which go to that one client only.
const TRACES = `${MODULE}.traces`;
const ERASE = `${MODULE}.erase`;

/** The Core's socket while this GM client is connected to it, else null. */
/** @type {WebSocket | null} */
let core = null;

/** This client's behaviour trace recorder (TRC-02), once the world is ready. */
/** @type {ReturnType<typeof createRecorder> | null} */
let recorder = null;

/** SecondChair's own VTT writes in flight in this client: what they trigger is not a manual act. */
let acting = 0;

/**
 * Run one of the Core's requests, tagging the semantic events it triggers `secondchair`, so a
 * Director's Desk gesture counts once in GM effort (TRC-03).
 * @template T @param {() => Promise<T>} run @returns {Promise<T>}
 */
async function asSecondChair(run) {
  acting++;
  try {
    return await run();
  } finally {
    acting--;
  }
}

/** Record a semantic event (TRC-02). @param {string} event @param {Record<string, unknown>} [data] */
function semantic(event, data = {}) {
  recorder?.record("semantic", { ...data, event, ...(acting > 0 && { secondchair: true }) });
}

/** The system adapter, once one registered (ARC-08); without it mechanical actions fail (ARC-09). */
/** @type {Adapter | null} */
let adapter = null;

/** Observations held in this browser until the Core acknowledges them, per world (CAP-03). */
const capture = createCapture({
  store: {
    load: () => {
      try {
        return JSON.parse(localStorage.getItem(`${MODULE}.observations.${game.world.id}`) ?? "[]");
      } catch {
        return [];
      }
    },
    save: (list) =>
      localStorage.setItem(`${MODULE}.observations.${game.world.id}`, JSON.stringify(list)),
  },
});

/** @param {string | null | undefined} id */
const sceneUuid = (id) => (id ? game.scenes.get(id) : game.scenes.active)?.uuid ?? null;
/** @param {string | null | undefined} id */
const actorUuid = (id) => (id ? (game.actors.get(id)?.uuid ?? null) : null);
/** @param {string} html */
const plain = (html) =>
  html
    .replace(/<[^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

/**
 * Post a line to the chat, its id returned. The line is text: neither HTML nor Foundry's
 * enrichers (@UUID[…], @Check[…], [[/r …]]), which would show or roll more.
 * @param {Record<string, unknown>} data  who speaks it, or to whom it is whispered
 * @param {string} line
 */
async function post(data, line) {
  const text = esc(line).replace(/[@[]/g, (c) => `&#${c.charCodeAt(0)};`);
  const message = await ChatMessage.create({ ...data, content: `<p>${text}</p>` });
  if (!message?.id) throw new Error("The line was not posted: nothing was said.");
  return String(message.id);
}

/** The generic events captured during a live session; a system adapter adds its own (ARC-16). */
function watch() {
  Hooks.on("createChatMessage", (/** @type {ChatMessageLike} */ msg) => {
    const whisper = msg.whisper.map((id) => game.users.get(id)).filter((u) => u !== undefined);
    capture.observe({
      scene: sceneUuid(msg.speaker?.scene),
      actor: actorUuid(msg.speaker?.actor),
      kind: "chat",
      visibility: visibilityOf({ blind: msg.blind, whisper }),
      payload: {
        author: msg.author?.name ?? null,
        speaker: msg.speaker?.alias ?? null,
        text: plain(msg.content ?? ""),
        flavor: plain(msg.flavor ?? ""),
        whisper: whisper.map((u) => u.name),
        rolls: (msg.rolls ?? []).map((r) => ({ formula: r.formula, total: r.total })),
      },
    });
  });
  // combatRound and combatTurn fire before the change, which their second argument holds.
  /** @param {string} action @returns {(combat: CombatLike, to?: {round?: number, turn?: number}) => void} */
  const combat = (action) => (c, to) => {
    const round = to?.round ?? c.round;
    const turn = to?.turn ?? c.turn;
    const combatant = action === "end" ? null : (c.turns[turn ?? -1] ?? c.combatant);
    capture.observe({
      scene: sceneUuid(c.scene?.id),
      actor: combatant?.actor?.uuid ?? null,
      kind: "combat",
      visibility: combatant?.hidden ? "gm" : "players",
      payload: {
        action,
        combat: c.id,
        round,
        turn,
        combatant: combatant?.name ?? null,
      },
    });
  };
  Hooks.on("combatStart", combat("start"));
  Hooks.on("combatRound", combat("round"));
  Hooks.on("combatTurn", combat("turn"));
  Hooks.on("deleteCombat", combat("end"));
  Hooks.on(
    "updateScene",
    (
      /** @type {{uuid: string, name: string}} */ scene,
      /** @type {{active?: boolean}} */ changes,
    ) => {
      if (changes.active)
        capture.observe({
          scene: scene.uuid,
          actor: null,
          kind: "scene",
          visibility: "players",
          payload: { action: "activate", name: scene.name },
        });
    },
  );
}

/** Whether this client is the one GM client that talks to the Core (PKG-08). */
const isActiveGM = () => game.user.isGM && game.users.activeGM?.id === game.user.id;

/** The ceiling as this client last saw it, to record each change's before. */
let ceiling = CEILING.default;

/** The Director's Desk's link to the Core, once connected (ARC-14). */
/** @type {ReturnType<typeof createDesk> | null} */
let desk = null;

/** The Director's Desk window, a minimal panel with no tabs, for the GM only (ARC-13, ARC-14). */
class DirectorsDesk extends foundry.applications.api.ApplicationV2 {
  static DEFAULT_OPTIONS = {
    id: "secondchair-desk",
    window: { title: "Director's Desk", resizable: true },
    position: { width: 440, height: /** @type {const} */ ("auto") },
    actions: {
      /** @param {Event} _event @param {HTMLElement} target */
      gesture: async (_event, target) => {
        const { gesture, entry, doc, entity } = target.dataset;
        /** @type {Record<string, unknown>} */
        const fields = {};
        if (entry) fields.entry = Number(entry);
        if (doc) fields.doc = doc;
        if (entity) fields.entity = entity;
        if (gesture === "reject") {
          const select = target.parentElement?.querySelector("select");
          fields.reason = select?.value;
        }
        try {
          const result = await desk?.gesture(String(gesture), fields);
          if (result && !result.ok) ui.notifications.error(`SecondChair: ${result.error}`);
          else if (result?.message) ui.notifications.info(`SecondChair: ${result.message}`);
        } catch (error) {
          ui.notifications.error(`SecondChair: ${/** @type {Error} */ (error).message}`);
        }
      },
      dismiss: () => desk?.dismissPile(),
    },
  };

  async _renderHTML() {
    if (desk?.closed && game.user.isGM)
      return "<p>Not connected to the Core: reload the world to connect again.</p>";
    return deskHtml({
      isGM: game.user.isGM,
      state: desk?.state ?? null,
      pile: desk?.pile ?? null,
      ceiling,
    });
  }

  /** @param {unknown} result @param {HTMLElement} content */
  _replaceHTML(result, content) {
    content.innerHTML = String(result);
  }
}

/** @type {DirectorsDesk | null} */
let deskWindow = null;

/** Show the Desk, or refresh it when open; only ever for a GM (ARC-13). */
function showDesk(force = false) {
  if (!game.user.isGM) return;
  deskWindow ??= new DirectorsDesk();
  if (force || deskWindow.rendered) deskWindow.render({ force: true });
}

Hooks.once("init", () => {
  const api = {
    /** @param {Adapter} systemAdapter */
    registerAdapter: (systemAdapter) => {
      adapter = systemAdapter;
    },
    /**
     * A system event for the behaviour traces, e.g. `pf2e.strike` (TRC-02).
     * @param {string} event @param {Record<string, unknown>} [data]
     */
    trace: (event, data = {}) => semantic(event, data),
  };
  /** @type {{api?: object}} */ (game.modules.get(MODULE)).api = api;
  // A system adapter registers through this hook (ARC-08, ADR 0004), whatever the load order.
  Hooks.callAll("secondchairFoundryInit", api);
  // Client settings live in this browser only: the token never reaches the Foundry server.
  game.settings.register(MODULE, "token", {
    name: "Core token",
    hint: "Printed by `secondchair token` on the computer running the Core. Kept in this browser only.",
    scope: "client",
    config: true,
    type: String,
    default: "",
    requiresReload: true,
  });
  game.settings.register(MODULE, "port", {
    name: "Core port",
    hint: "The port `secondchair serve` listens on, on this computer's loopback (127.0.0.1).",
    scope: "client",
    config: true,
    type: Number,
    default: 7240,
    requiresReload: true,
  });
  // Consent to behaviour traces (TRC-01) is kept per user in this browser, so nobody else can
  // give it. This setting is only its checkbox: `ready` aligns it with the user signed in here.
  game.settings.register(MODULE, "traces", {
    name: "Record my behaviour traces",
    hint: "Lets SecondChair record how you use Foundry (clicks, mouse, keys outside text fields, windows, rolls; never what you type) on the GM's computer, to measure where the VTT gets in the way. Off by default. Unticking stops it and offers to erase what was recorded.",
    scope: "client",
    config: true,
    type: Boolean,
    default: false,
    onChange: (value) => setConsent(Boolean(value)),
  });
  game.settings.register(MODULE, "moveHz", {
    name: "Behaviour traces: mouse samples per second",
    scope: "world",
    config: true,
    type: Number,
    default: 10,
  });
  // The campaign this world is bound to (ARC-18), set by the Core's first welcome.
  game.settings.register(MODULE, "campaign", {
    scope: "world",
    config: false,
    type: String,
    default: "",
  });
  // The keys of the prepared documents created once in this world: one deleted since is not
  // recreated silently (documents.js), as a scene keeps its own in its flags.
  game.settings.register(MODULE, "prepared", {
    scope: "world",
    config: false,
    type: Object,
    default: {},
  });
  // The ceiling (DEL-19a): each change is recorded as an observation by the active GM client,
  // which also puts back a change made by a user who is not a GM.
  game.settings.register(MODULE, "ceiling", {
    ...CEILING,
    onChange: (value, _options, userId) => {
      const before = ceiling;
      ceiling = String(value);
      showDesk();
      if (!isActiveGM()) return;
      // Recorded in every moment, tagged with the live session when one is open.
      capture.observe({
        kind: "ceiling",
        visibility: "gm",
        payload: { user: userId ?? null, before, after: ceiling },
        anytime: true,
      });
      if (userId && !game.users.get(userId)?.isGM) {
        ui.notifications.warn("SecondChair: only a GM may change the delegation ceiling.");
        // The revert is itself a change, recorded as one.
        game.settings
          .set(MODULE, "ceiling", before)
          .catch((/** @type {unknown} */ error) => console.error("SecondChair:", error));
      }
    },
  });
  // Only a GM changes the ceiling (DEL-19a), even where players were granted world settings.
  // ponytail: refused in the changing client; a tampered client is put back by the active GM.
  /** @param {{key: string}} setting */
  const guard = (setting) => {
    if (setting.key !== `${MODULE}.ceiling` || game.user.isGM) return true;
    ui.notifications.error("SecondChair: only a GM may change the delegation ceiling.");
    return false;
  };
  Hooks.on("preCreateSetting", guard);
  Hooks.on("preUpdateSetting", guard);
  game.keybindings.register(MODULE, "desk", {
    name: "Open the Director's Desk",
    editable: [{ key: "KeyD", modifiers: ["Shift"] }],
    restricted: true,
    onDown: () => {
      if (desk && !desk.closed) showDesk(true);
      else ui.notifications.warn("SecondChair: not connected to the Core.");
      return true;
    },
  });
});

Hooks.once("ready", () => {
  ceiling = String(game.settings.get(MODULE, "ceiling"));
  traces();
  // One GM connection at a time (PKG-08): only the active GM dials the Core.
  if (!isActiveGM()) return;
  const token = String(game.settings.get(MODULE, "token") ?? "");
  if (!token) {
    ui.notifications.warn(
      "SecondChair: run `secondchair token` on the computer running the Core and paste the token into this module's settings.",
    );
    return;
  }
  watch();
  adapter?.observe?.((event) => capture.observe(event));
  const url = coreUrl(Number(game.settings.get(MODULE, "port")));
  const campaign = String(game.settings.get(MODULE, "campaign") ?? "");
  // ponytail: no reconnection yet; reload the world to dial again.
  connect({
    url,
    hello: hello({ token, world: game.world.id, campaign }),
    onWelcome: async (welcome, socket) => {
      const language = welcome.campaign_language;
      const active = (/** @type {string} */ id) => game.modules.get(id)?.active === true;
      const missing = missingTranslation(adapter, language, active);
      if (missing) {
        socket.close();
        ui.notifications.error(`SecondChair: ${missing}`, { permanent: true });
        return;
      }
      const actions = createActions({
        language: () => language,
        resolve: async (uuid) => /** @type {Doc | null} */ (await fromUuid(uuid)),
        // Handled requests live on the GM user, so a reload still knows them (BVE-02).
        store: {
          load: () => /** @type {unknown[]} */ (game.user.getFlag(MODULE, "requests") ?? []),
          save: (list) => game.user.setFlag(MODULE, "requests", list),
        },
        adapter: () => adapter,
        // Read at each request, so a change applies at once (DEL-19).
        ceiling: () => game.settings.get(MODULE, "ceiling"),
        // In character, as the token, to the whole table.
        say: (token, line) => post({ speaker: ChatMessage.getSpeaker({ token }) }, line),
        // To one player only: a whisper, which capture observes as not seen by the table (CAP-08).
        tell: (user, line) => post({ whisper: [user.id] }, line),
        reads: genericReads({
          browse: async (source, path, options) => {
            const picker = foundry.applications.apps?.FilePicker?.implementation ?? FilePicker;
            return picker.browse(source, path, options);
          },
          packs: () => game.packs,
          origin: location.origin,
          system: () => {
            const translations = adapter?.translations ?? {};
            const id = translations[language] ?? translations[language.split("-")[0].toLowerCase()];
            return {
              id: game.system.id,
              version: game.system.version,
              translation: id ? (game.modules.get(id)?.title ?? id) : null,
            };
          },
          // Foundry's texture loader takes images and videos alike (a .webm map).
          imageSize: async (path) => {
            const texture = await foundry.canvas.loadTexture(path);
            if (!texture) throw new Error(`Cannot load ${path} in the GM's client.`);
            return { width: texture.width, height: texture.height };
          },
          documents: (type) => (type === "Scene" ? game.scenes : collection(type)),
          fromUuid: async (uuid) => /** @type {Doc | null} */ (await fromUuid(uuid)),
        }),
      });
      /** The calls due now the Desk already showed. @type {Set<number>} */
      let seen = new Set();
      desk = createDesk({
        send: (message) => socket.send(JSON.stringify(message)),
        isGM: () => game.user.isGM,
        // A new call due now opens the Desk: it is an interruption (DEL-33).
        onChange: () => {
          const due = (desk?.state?.calls ?? []).map((c) => c.id);
          const fresh = due.some((id) => !seen.has(id));
          seen = new Set(due);
          showDesk(fresh);
        },
      });
      socket.addEventListener("message", async (event) => {
        try {
          const message = JSON.parse(String(event.data));
          if (desk?.receive(message)) return;
          if (message.type === "request")
            socket.send(JSON.stringify(await asSecondChair(() => actions.handle(message))));
          else if (message.type === "read")
            socket.send(JSON.stringify(await actions.read(message)));
          else if (message.type === "session") capture.setSession(message.session);
          else if (message.type === "ack") {
            if (!message.ok) console.error("SecondChair: observation refused:", message.error);
            capture.ack(message.id);
          } else if (message.type === "realise" || message.type === "realise_document")
            socket.send(JSON.stringify(await asSecondChair(() => realiseOne(message))));
        } catch (error) {
          // A malformed frame or a closed socket: the Core times the request out as failed.
          console.error("SecondChair:", error);
        }
      });
      socket.addEventListener("close", () => {
        capture.disconnect();
        core = null;
        desk?.close();
        showDesk();
      });
      core = socket;
      capture.connect((message) => socket.send(JSON.stringify(message)));
      if (campaign !== welcome.campaign) {
        await game.settings.set(MODULE, "campaign", welcome.campaign);
      }
      ui.notifications.info("SecondChair: connected to the Core.");
      showDesk(true);
    },
    onRefused: (refusal) =>
      ui.notifications.error(`SecondChair: ${refusal.message}`, { permanent: true }),
    // Chromium holds the socket while its local-network prompt is open (PKG-11).
    onPending: () =>
      ui.notifications.warn(
        "SecondChair: still waiting for the Core. If the browser asks whether this site may access apps and services on this device, allow it; if you missed the prompt, allow the site in the browser's site permissions and reload.",
      ),
    onUnreachable: () =>
      ui.notifications.error(
        `SecondChair: cannot reach the Core at ${url}. Is \`secondchair serve\` running on this computer? If the browser asked whether this site may access local devices, allow it and reload.`,
        { permanent: true },
      ),
  });
});

/** Scenes and documents are realised one at a time. */
/** @type {Promise<unknown>} */
let realising = Promise.resolve();

/** The Foundry calls a realisation makes (scenes.js stays free of Foundry globals). */
/** @type {import("./scenes.js").World} */
const world = {
  findScene: (key) => game.scenes.find((s) => s.flags?.[MODULE]?.scene === key) ?? null,
  createScene: (data) => Scene.create({ navigation: false, ...data }),
  tokenData: async (item) => {
    const actor = await worldActor(/** @type {string} */ (item.actor));
    return (await actor.getTokenDocument(item.data)).toObject();
  },
  // Foundry 14 keeps a scene's map in its levels (scenes.js).
  get levels() {
    return game.release.generation >= 14;
  },
};

/** The world collection of a prepared document type, or null. @param {string} type */
function collection(type) {
  if (!DOCUMENT_TYPES.includes(type)) return null;
  return /** @type {any} */ (game).collections.get(type);
}

/** The prepared document of a key, of whatever type, or null. @param {string} key */
function preparedDocument(key) {
  for (const type of DOCUMENT_TYPES) {
    const found = collection(type)?.find(
      (/** @type {FoundryDoc} */ d) => d.flags?.[MODULE]?.document === key,
    );
    if (found) return found;
  }
  return null;
}

/** The Foundry calls a document realisation makes (documents.js stays free of Foundry globals). */
/** @type {import("./documents.js").World} */
const documentWorld = {
  findDocument: preparedDocument,
  createDocument: (type, data) => collection(type).documentClass.create(data),
  fromBase: async (type, base, data) => {
    const source = await fromUuid(base);
    if (!source) throw new Error(`No ${type} ${base} in this world or its compendiums.`);
    const imported = collection(type).fromCompendium(source);
    return foundry.utils.mergeObject(imported, data, { inplace: false });
  },
  // Foundry's client ships showdown, which its own Markdown pages render with.
  markdown: (text) => new showdown.Converter(CONST.SHOWDOWN_OPTIONS).makeHtml(text),
  // Foundry's own sanitizer: showdown passes raw HTML through, and has no option to refuse it.
  clean: (html) => {
    const clean =
      foundry.utils.cleanHTML ?? foundry.applications.ux?.TextEditor?.implementation?.cleanHTML;
    if (!clean) throw new Error("No HTML sanitizer in this Foundry: the page was not written.");
    return clean(html);
  },
  // Dotted keys (`ownership.default`) expanded as Foundry's update would, before any is dropped.
  expand: (data) => foundry.utils.expandObject(data),
  created: {
    load: () =>
      /** @type {Record<string, boolean>} */ (game.settings.get(MODULE, "prepared") ?? {}),
    save: (created) => game.settings.set(MODULE, "prepared", created),
  },
};

/** A world Actor for a UUID, importing a compendium one once. @param {string} uuid */
async function worldActor(uuid) {
  const source = /** @type {any} */ (await fromUuid(uuid));
  if (!source) throw new Error(`No Actor ${uuid} in this world or its compendiums.`);
  if (!source.pack) return source;
  const imported = game.actors.find((a) => a.flags?.[MODULE]?.source === uuid);
  if (imported) return imported;
  const data = game.actors.fromCompendium(source);
  data.flags = { ...data.flags, [MODULE]: { source: uuid } };
  return Actor.create(data);
}

/**
 * Realise a desired scene or world document the Core sent, and report back
 * (docs/contracts/foundry-bridge.md). Its `@prepared:` references are resolved first, so a scene
 * uses the documents realised before it. Reconciliation is idempotent, so a replayed request only
 * finds nothing to do. The world's ceiling bounds it at the level of whoever last wrote it
 * (DEL-19a).
 * @param {{id: string, scene?: string, document?: string, desired: any, level: string | null}} request
 */
function realiseOne({ id, scene, document, desired, level }) {
  const what = document ? `document "${document}"` : `scene "${scene}"`;
  const run = realising.then(async () => {
    const refusal = aboveCeiling(game.settings.get(MODULE, "ceiling"), level);
    if (refusal) {
      ui.notifications.warn(`SecondChair: ${what} not realised. ${refusal}`);
      return { type: "realised", id, ok: false, error: refusal, reason: "ceiling" };
    }
    try {
      /** @type {string[]} */
      const unresolved = [];
      const resolved = resolve(desired, finder(preparedDocument), unresolved);
      const report = document
        ? await realiseDocument(document, resolved, documentWorld)
        : await realise(
            /** @type {string} */ (scene),
            guardedScene(resolved, documentWorld),
            world,
          );
      report.errors.push(...unresolved);
      const { conflict = 0 } = report.summary;
      if (conflict || report.errors.length) {
        ui.notifications.warn(
          `SecondChair: ${what} realised with ${conflict} conflict(s) and ${report.errors.length} error(s); ask your agent for the report.`,
        );
      }
      return { type: "realised", id, ok: true, report };
    } catch (err) {
      return {
        type: "realised",
        id,
        ok: false,
        error: String(/** @type {Error} */ (err)?.message ?? err),
      };
    }
  });
  realising = run;
  return run;
}

const consentKey = () => `${MODULE}.traces.${game.world.id}.${game.user.id}`;

/** Whether the user signed in here consented, in this browser (TRC-01). */
function consented() {
  try {
    return localStorage.getItem(consentKey()) === "1";
  } catch {
    return false;
  }
}

/** Show the table whether this user consents, through a flag only their own client writes. */
async function showConsent() {
  const on = consented();
  if (Boolean(game.user.getFlag(MODULE, "traces")) !== on)
    await game.user.setFlag(MODULE, "traces", on);
}

/** @param {boolean} on */
async function setConsent(on) {
  if (consented() === on) return;
  try {
    localStorage.setItem(consentKey(), on ? "1" : "0");
  } catch {
    ui.notifications.error("SecondChair: this browser cannot keep your consent.");
    return;
  }
  await showConsent();
  if (!on) await offerErase();
}

/** After a revocation, let the user erase all their past traces (TRC-01). */
async function offerErase() {
  const erase = await foundry.applications.api.DialogV2.confirm({
    window: { title: "SecondChair: behaviour traces" },
    content:
      "<p>Recording stopped. Also erase all the behaviour traces already recorded for you?</p>",
  });
  if (!erase) return;
  const gm = game.users.activeGM;
  if (isActiveGM()) erasedNotice(eraseFor(game.user.id));
  else if (gm)
    gm.query(ERASE, {}).then(
      (ok) => erasedNotice(ok === true),
      () => erasedNotice(false),
    );
  else erasedNotice(false);
}

/** @param {string} user @returns {boolean} whether the request reached the Core */
function eraseFor(user) {
  core?.send(JSON.stringify({ type: "erase_traces", user }));
  return core !== null;
}

/** @param {boolean} ok */
function erasedNotice(ok) {
  if (ok) ui.notifications.info("SecondChair: your behaviour traces are erased.");
  else
    ui.notifications.warn(
      "SecondChair: the GM's client is not connected to SecondChair, so your traces cannot be erased now. Tick and untick the setting again once it is.",
    );
}

/** Record this user's behaviour traces once they consent; the active GM also relays the table's. */
function traces() {
  // Players' traces reach the Core only through the active GM's client (TRC-05), as a Foundry
  // query that no other client receives. Who is the active GM can change, so it is asked at each
  // send; a GM client that never dialed, or a query that fails, counts gaps.
  const outbox = createOutbox({
    ready: () => (isActiveGM() ? core !== null : game.users.activeGM !== null),
    send: (user, records) =>
      isActiveGM()
        ? core?.send(
            JSON.stringify({
              type: "traces",
              user,
              name: game.users.get(user)?.name ?? user,
              gm: Boolean(game.users.get(user)?.isGM),
              records,
            }),
          )
        : (game.users.activeGM?.query(TRACES, { records }, { timeout: 5000 }) ?? Promise.reject()),
  });
  const rec = createRecorder({ consented, flush: (records) => outbox.push(game.user.id, records) });
  recorder = rec;
  setInterval(() => rec.flush(), 1000);

  // Foundry passes the querying user, so a player cannot send or erase traces as someone else.
  // A client that is no longer the active GM refuses, and the player counts a gap.
  CONFIG.queries[TRACES] = (/** @type {any} */ data, { user }) => {
    if (!isActiveGM()) throw new Error("not the active GM");
    if (Array.isArray(data?.records)) outbox.push(user.id, data.records);
    return true;
  };
  CONFIG.queries[ERASE] = (_data, { user }) => {
    if (!isActiveGM()) throw new Error("not the active GM");
    return eraseFor(user.id);
  };

  // The checkbox follows the user signed in here; their flag follows their own consent.
  if (game.settings.get(MODULE, "traces") !== consented())
    game.settings.set(MODULE, "traces", consented());
  showConsent();
  Hooks.on("updateUser", (/** @type {{id: string}} */ user, /** @type {any} */ changes) => {
    if (!changes.flags?.[MODULE]) return;
    if (user.id === game.user.id) showConsent(); // a GM cannot consent for a player
    ui.players?.render();
  });
  // The GM sees who consents in the players list.
  Hooks.on("renderPlayers", (/** @type {unknown} */ _app, /** @type {any} */ html) => {
    /** @type {HTMLElement | undefined} */
    const root = html instanceof HTMLElement ? html : html?.[0];
    for (const li of root?.querySelectorAll("[data-user-id]") ?? []) {
      const id = /** @type {HTMLElement} */ (li).dataset.userId ?? "";
      if (game.users.get(id)?.getFlag(MODULE, "traces"))
        li.insertAdjacentHTML(
          "beforeend",
          ' <i class="fa-solid fa-circle-dot" title="Records behaviour traces (SecondChair)"></i>',
        );
    }
  });

  // Raw input (TRC-02), on the recorder's clock.
  /** @param {Record<string, unknown>} data */
  const input = (data) => rec.record("input", data);
  const onCanvas = () => {
    const p = canvas?.ready ? canvas.mousePosition : null;
    return p ? { x: Math.round(p.x), y: Math.round(p.y) } : null;
  };
  /** @param {MouseEvent} e */
  const at = (e) => ({ x: e.clientX, y: e.clientY, canvas: onCanvas() });
  /** @param {Event} e */
  const target = (e) => describe(/** @type {any} */ (e.target));
  const opts = { capture: true, passive: true };
  document.addEventListener(
    "pointerdown",
    (e) => input({ input: "click", button: e.button, ...at(e), target: target(e) }),
    opts,
  );
  let lastMove = 0;
  document.addEventListener(
    "pointermove",
    (e) => {
      const hz = Number(game.settings.get(MODULE, "moveHz")) || 10;
      if (!document.hasFocus() || e.timeStamp - lastMove < 1000 / hz) return;
      lastMove = e.timeStamp;
      input({ input: "move", ...at(e) });
    },
    opts,
  );
  document.addEventListener(
    "wheel",
    (e) => input({ input: "wheel", dy: Math.round(e.deltaY), ...at(e) }),
    opts,
  );
  document.addEventListener(
    "dragstart",
    (e) => input({ input: "drag", ...at(e), target: target(e) }),
    opts,
  );
  document.addEventListener(
    "drop",
    (e) => input({ input: "drop", ...at(e), target: target(e) }),
    opts,
  );
  document.addEventListener("keydown", (e) => input(keyInput(e)), opts);

  // Semantic events (TRC-02); a system adapter adds its own through the module's `api.trace`.
  // ponytail: no idle, undo, cancelled move or cancelled roll dialog event here; the friction
  // detectors read idle and Ctrl+Z from the input stream, and the adapter reports the rest
  // (`<system>.move.cancel`, `<system>.roll.cancel`, `<system>.strike`…).
  window.addEventListener("focus", () => semantic("focus"));
  window.addEventListener("blur", () => semantic("blur"));
  /** @param {any} app */
  const windowOf = (app) => ({
    window: app.id,
    app: app.constructor.name,
    document: app.document?.uuid ?? null,
  });
  Hooks.on("renderApplicationV2", (app, _el, _ctx, options) => {
    if (options?.isFirstRender) semantic("window.open", windowOf(app));
  });
  Hooks.on("closeApplicationV2", (app) => semantic("window.close", windowOf(app)));
  Hooks.on("createChatMessage", (/** @type {ChatMessageLike} */ msg, _options, userId) => {
    if (userId === game.user.id && msg.rolls?.length)
      semantic("roll", { formulas: msg.rolls.map((r) => r.formula) });
  });
  Hooks.on("targetToken", (/** @type {{id: string}} */ user, token, on) => {
    if (user.id === game.user.id) semantic("target", { token: token.document.uuid, on });
  });
  Hooks.on("updateToken", (doc, changes, _options, userId) => {
    if (userId === game.user.id && ("x" in changes || "y" in changes))
      semantic("move", { token: doc.uuid });
  });
  // `own`: this user's turn; for a GM, a GM creature's (TRC-03: long turns, dead time).
  Hooks.on("combatTurnChange", (/** @type {CombatLike} */ combat, _prior, current) => {
    const c = combat.combatant;
    const own = Boolean(c?.isOwner && !(game.user.isGM && c.hasPlayerOwner));
    semantic("turn", { combat: combat.id, round: current.round, turn: current.turn, own });
  });
}
