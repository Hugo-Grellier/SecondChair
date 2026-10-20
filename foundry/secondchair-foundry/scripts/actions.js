// VTT actions the Core requests (ARC-07, ARC-09, docs/contracts/foundry-bridge.md).
// The idempotent write queue is transplanted from v3 (BVE-02): every request id is recorded before
// and after it runs, so a replayed id gets its first reply back instead of acting twice, even
// after a reload; writes run one at a time. Free of Foundry globals, so it runs under `node --test`.

/**
 * @typedef {Record<string, unknown>} Fields
 * @typedef {{type: "request", id: string, op: string, target: string, params: Fields, expect: Fields | null, level: string | null}} Request
 * @typedef {{type: "reply", id: string, ok: true, before: Fields, after: Fields} | {type: "reply", id: string, ok: false, error: string, reason?: "ceiling"}} Reply
 * @typedef {{documentName: string, update(changes: Fields): Promise<unknown>} & Record<string, unknown>} Doc
 * @typedef {{id: string, status: "running" | "done", reply?: Reply}} Handled
 * @typedef {{type: "read", id: string, op: string, params: Fields}} Read
 * @typedef {{type: "reply", id: string, ok: true, result: unknown} | {type: "reply", id: string, ok: false, error: string}} ReadReply
 * @typedef {import("./capture.js").Event} Event
 */

/**
 * A system adapter (ARC-08), registered through the `secondchairFoundryInit` hook.
 * @typedef {object} Adapter
 * @property {Record<string, (target: string, params: Fields, expect: Fields | null) => Promise<{before: Fields, after: Fields}>>} ops
 *   mechanical actions; each resolves its own target, a UUID or what the op documents
 * @property {Record<string, (params: Fields, context: {language: string}) => Promise<unknown>>} [reads]
 *   what only the VTT knows (rules_context, official_name)
 * @property {Record<string, string>} [translations]  campaign language -> the translation module it requires (CAN-21)
 * @property {(emit: (event: Event) => void) => void} [observe]  start capturing its observations
 */

/**
 * Why the connector must not start for this campaign language, or null (CAN-21): the adapter
 * declares the official translation module the language needs, and it is not active.
 * @param {Adapter | null} adapter
 * @param {string} language  the campaign language, a BCP 47 tag
 * @param {(id: string) => boolean} active  whether a module is active in this world
 */
export function missingTranslation(adapter, language, active) {
  const translations = adapter?.translations ?? {};
  const required = translations[language] ?? translations[language.split("-")[0].toLowerCase()];
  if (!required || active(required)) return null;
  return (
    `This campaign is in "${language}": install and enable the module "${required}", the ` +
    "official translation its game system needs, then reload. SecondChair stays disconnected " +
    "until then."
  );
}

/** The library's generic actions: one document type, the fields they may set, a dotted path for
 * a nested one (ARC-07). reveal_token and publish_journal are disclosures (DEL-09). */
const GENERIC = {
  move_token: { documentName: "Token", fields: ["x", "y"] },
  set_door: { documentName: "Wall", fields: ["ds"] },
  reveal_token: { documentName: "Token", fields: ["hidden"] },
  publish_journal: { documentName: "JournalEntry", fields: ["ownership.default"] },
};

/** @param {Record<string, unknown>} doc @param {string} path */
const field = (doc, path) => path.split(".").reduce((/** @type {any} */ o, k) => o?.[k], doc);

/** Delegation levels, loosest last (DEL-02). */
export const LEVELS = ["manual", "propose", "act-then-review", "autonomous"];

/** The ceiling (DEL-19, DEL-19a): a world setting only a GM changes, act-then-review on a fresh world. */
export const CEILING = {
  name: "Delegation ceiling",
  hint: "The most any SecondChair agent may do in this world, whatever the campaign's delegation table says. Actions above it are refused and become a call on the GM.",
  scope: /** @type {const} */ ("world"),
  config: true,
  type: String,
  choices: {
    manual: "Manual: agents take no action in the VTT",
    propose: "Propose: only actions the GM approved",
    "act-then-review": "Act then review",
    autonomous: "Autonomous",
  },
  default: "act-then-review",
};

/**
 * Why the ceiling refuses what the Core asks at `level` (DEL-19, DEL-19a), or null.
 * level null: the GM's own undo or edit, which the ceiling does not bound. Anything unknown is refused.
 * @param {unknown} ceiling  the world's ceiling setting
 * @param {string | null} level
 */
export function aboveCeiling(ceiling, level) {
  if (level === null) return null;
  const max = LEVELS.indexOf(String(ceiling));
  const rank = LEVELS.indexOf(level);
  if (max >= 0 && rank >= 0 && rank <= max) return null;
  return `Refused by this world's delegation ceiling (${ceiling}): it was asked at ${level}.`;
}

/** Refused by the ceiling: a failed action and a call on the GM (DEL-20). */
class CeilingRefusal extends Error {}

/** Handled request ids kept (v3 kept 60). */
const KEPT = 200;

/**
 * @param {object} args
 * @param {(uuid: string) => Promise<Doc | null>} args.resolve  the document a UUID names
 * @param {{load(): unknown[], save(list: Handled[]): Promise<unknown>}} args.store  handled requests, kept across reloads
 * @param {() => Adapter | null} args.adapter  the system adapter, if one registered
 * @param {() => unknown} args.ceiling  the world's ceiling setting
 * @param {() => string} args.language  the campaign language
 * @param {(token: Doc, line: string) => Promise<string>} args.say  have a token say a line aloud
 *   to the table: a public chat message spoken by it, whose id it returns
 * @param {(user: Doc, line: string) => Promise<string>} args.tell  whisper a line to one user:
 *   a chat message only that user (and the GM) sees, whose id it returns
 */
export function createActions({ resolve, store, adapter, ceiling, language, say, tell }) {
  /** @type {Map<string, Promise<Reply>>} */
  const inflight = new Map();
  /** @type {Promise<unknown>} */
  let queue = Promise.resolve();

  const handled = () => /** @type {Handled[]} */ (store.load() ?? []);
  /** @param {Handled} entry */
  const record = (entry) =>
    store.save(
      handled()
        .filter((e) => e.id !== entry.id)
        .concat(entry)
        .slice(-KEPT),
    );

  /** @param {Request} request @returns {Promise<{before: Fields, after: Fields}>} */
  async function act({ op, target, params, expect, level }) {
    const refusal = aboveCeiling(ceiling(), level);
    if (refusal) throw new CeilingRefusal(refusal);
    if (op === "speak" || op === "whisper") {
      // A disclosure (DEL-09): irreversible, so there is no undo to take.
      if (expect) throw new Error("A line once said cannot be taken back.");
      const to = op === "speak" ? "Token" : "User";
      const doc = await resolve(target);
      if (doc?.documentName !== to) throw new Error(`${target} is not a ${to}.`);
      const line = params.content;
      if (typeof line !== "string" || !line.trim()) throw new Error(`${op} says a \`content\`.`);
      const message = await (op === "speak" ? say : tell)(doc, line);
      return { before: { message: null }, after: { message } };
    }
    if (!Object.hasOwn(GENERIC, op)) {
      const ops = adapter()?.ops;
      if (!ops) {
        throw new Error(
          `No system adapter is installed: "${op}" is a mechanical action, which needs one.`,
        );
      }
      if (!Object.hasOwn(ops, op)) throw new Error(`Unknown action "${op}".`);
      return ops[op](target, params, expect);
    }
    const doc = await resolve(target);
    if (!doc) throw new Error(`No document ${target} in this world.`);
    const { documentName, fields } = GENERIC[/** @type {keyof typeof GENERIC} */ (op)];
    if (doc.documentName !== documentName) {
      throw new Error(`${target} is a ${doc.documentName}, not a ${documentName}.`);
    }
    const keys = Object.keys(params);
    if (!keys.length || keys.some((k) => !fields.includes(k))) {
      throw new Error(`${op} sets ${fields.join(", ")} only.`);
    }
    const pick = () => Object.fromEntries(fields.map((k) => [k, field(doc, k)]));
    const before = pick();
    if (expect && Object.entries(expect).some(([k, v]) => before[k] !== v)) {
      throw new Error(`${target} changed since: nothing was done.`);
    }
    await doc.update(params);
    return { before, after: pick() };
  }

  /**
   * Answer a read. It changes nothing: neither queued nor recorded, so a replay reads again.
   * @param {Read} request @returns {Promise<ReadReply>}
   */
  async function read({ id, op, params }) {
    try {
      const reads = adapter()?.reads;
      if (!reads) throw new Error(`No system adapter is installed to read "${op}".`);
      if (!Object.hasOwn(reads, op)) throw new Error(`Unknown read "${op}".`);
      const result = await reads[op](params, { language: language() });
      return { type: "reply", id, ok: true, result };
    } catch (err) {
      const error = String(/** @type {Error} */ (err)?.message ?? err);
      return { type: "reply", id, ok: false, error };
    }
  }

  /** @param {Request} request @returns {Promise<Reply>} */
  function handle(request) {
    const { id } = request;
    const running = inflight.get(id);
    if (running) return running;
    const known = handled().find((e) => e.id === id);
    if (known) {
      return Promise.resolve(
        known.reply ?? {
          type: "reply",
          id,
          ok: false,
          error: `Request ${id} was interrupted by a reload of the GM client: check the VTT before retrying.`,
        },
      );
    }
    const run = queue
      .then(async () => {
        await record({ id, status: "running" });
        /** @type {Reply} */
        let reply;
        try {
          reply = { type: "reply", id, ok: true, ...(await act(request)) };
        } catch (err) {
          reply = {
            type: "reply",
            id,
            ok: false,
            error: String(/** @type {Error} */ (err)?.message ?? err),
            ...(err instanceof CeilingRefusal && { reason: /** @type {const} */ ("ceiling") }),
          };
        }
        await record({ id, status: "done", reply });
        return reply;
      })
      .finally(() => inflight.delete(id));
    inflight.set(id, run);
    queue = run.catch(() => {});
    return run;
  }

  return { handle, read };
}
