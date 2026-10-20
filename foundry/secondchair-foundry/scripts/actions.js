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
 * @typedef {{ops: Record<string, (doc: Doc, params: Fields, expect: Fields | null) => Promise<{before: Fields, after: Fields}>>}} Adapter
 */

/** The library's generic actions: one document type, the fields they may set (ARC-07). */
const GENERIC = {
  move_token: { documentName: "Token", fields: ["x", "y"] },
  set_door: { documentName: "Wall", fields: ["ds"] },
};

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
 */
export function createActions({ resolve, store, adapter, ceiling }) {
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
    // level null: the GM's own undo, which the ceiling does not bound. Anything unknown is refused.
    const max = LEVELS.indexOf(String(ceiling()));
    const rank = level === null ? -1 : LEVELS.indexOf(level);
    if (level !== null && (max < 0 || rank < 0 || rank > max)) {
      throw new CeilingRefusal(
        `Refused by this world's delegation ceiling (${ceiling()}): the action was asked at ${level}.`,
      );
    }
    const doc = await resolve(target);
    if (!doc) throw new Error(`No document ${target} in this world.`);
    if (!Object.hasOwn(GENERIC, op)) {
      const ops = adapter()?.ops;
      if (!ops) {
        throw new Error(
          `No system adapter is installed: "${op}" is a mechanical action, which needs one.`,
        );
      }
      if (!Object.hasOwn(ops, op)) throw new Error(`Unknown action "${op}".`);
      return ops[op](doc, params, expect);
    }
    const { documentName, fields } = GENERIC[/** @type {keyof typeof GENERIC} */ (op)];
    if (doc.documentName !== documentName) {
      throw new Error(`${target} is a ${doc.documentName}, not a ${documentName}.`);
    }
    const keys = Object.keys(params);
    if (!keys.length || keys.some((k) => !fields.includes(k))) {
      throw new Error(`${op} sets ${fields.join(", ")} only.`);
    }
    const pick = () => Object.fromEntries(fields.map((k) => [k, doc[k]]));
    const before = pick();
    if (expect && Object.entries(expect).some(([k, v]) => before[k] !== v)) {
      throw new Error(`${target} changed since: nothing was done.`);
    }
    await doc.update(params);
    return { before, after: pick() };
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

  return { handle };
}
