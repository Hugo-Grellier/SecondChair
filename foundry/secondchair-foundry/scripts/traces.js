// Behaviour traces (TRC-01, TRC-02, TRC-05; docs/contracts/foundry-bridge.md, "Behaviour traces").
// Every client records its own user's traces only once that user consented, in that client. Free
// of Foundry globals, so it runs under `node --test`.

/**
 * @typedef {{t: number, stream: string} & Record<string, unknown>} TraceRecord
 * @typedef {{key: string, ctrlKey: boolean, shiftKey: boolean, altKey: boolean, metaKey: boolean, target: EventTarget | {closest?(selector: string): unknown, isContentEditable?: boolean} | null}} KeyEventLike
 */

/** Where typing is fiction or private talk: only its rhythm is kept (ADR 0012). */
const TEXT_FIELD = "input, textarea, select, [contenteditable]";

/**
 * Collects a user's records and hands them over at each flush; drops everything without consent.
 * @param {object} args
 * @param {() => boolean} args.consented  read in this client, at capture and again at flush
 * @param {(records: TraceRecord[]) => void} args.flush  called at every flush, even with nothing
 * @param {() => number} [args.now]  the one clock both streams share
 */
export function createRecorder({ consented, flush, now = Date.now }) {
  /** @type {TraceRecord[]} */
  let queue = [];
  return {
    /** @param {"semantic" | "input"} stream @param {Record<string, unknown>} data */
    record(stream, data) {
      if (consented()) queue.push({ ...data, t: now(), stream });
    },
    flush() {
      const records = queue;
      queue = [];
      if (consented()) flush(records);
    },
  };
}

/**
 * Sends records when there is someone to send them to, and otherwise drops them, counting the
 * gap, which leaves first once sending works again (TRC-05: no buffer). A send that returns a
 * promise lost its records if it rejects; they are counted the same way.
 * @param {object} args
 * @param {() => boolean} args.ready
 * @param {(user: string, records: TraceRecord[]) => unknown} args.send
 */
export function createOutbox({ ready, send }) {
  /** @type {Map<string, {from: number, to: number, lost: number}>} */
  const gaps = new Map();
  /** @param {string} user @param {TraceRecord[]} records */
  const drop = (user, records) => {
    for (const r of records) {
      const gap = r.stream === "gap" ? /** @type {any} */ (r) : { from: r.t, to: r.t, lost: 1 };
      const held = gaps.get(user) ?? { from: gap.from, to: gap.to, lost: 0 };
      gaps.set(user, {
        from: Math.min(held.from, gap.from),
        to: Math.max(held.to, gap.to, r.t),
        lost: held.lost + gap.lost,
      });
    }
  };
  return {
    /** @param {string} user @param {TraceRecord[]} records */
    push(user, records) {
      // A player's client could send anything: keep only records the Core can read.
      const valid = records.filter(
        (/** @type {any} */ r) =>
          Number.isInteger(r?.t) &&
          (r.stream !== "gap" || [r.from, r.to, r.lost].every(Number.isInteger)),
      );
      if (!ready()) return drop(user, valid);
      const gap = gaps.get(user);
      gaps.delete(user);
      /** @type {TraceRecord[]} */
      const out = gap ? [{ t: gap.to, stream: "gap", ...gap }, ...valid] : valid;
      if (!out.length) return;
      const sent = send(user, out);
      if (sent instanceof Promise) sent.catch(() => drop(user, out));
    },
  };
}

/**
 * The input record of a key press: the key outside text fields, only that one was typed inside.
 * @param {KeyEventLike} event
 */
export function keyInput({ key, ctrlKey, shiftKey, altKey, metaKey, target }) {
  const el = /** @type {{closest?(s: string): unknown, isContentEditable?: boolean} | null} */ (
    target
  );
  if (el?.isContentEditable || el?.closest?.(TEXT_FIELD))
    return { input: "type", del: key === "Backspace" || key === "Delete" };
  return { input: "key", key, ctrl: ctrlKey, shift: shiftKey, alt: altKey, meta: metaKey };
}

/**
 * A short description of the element clicked, from its tag, id, classes and action: no text.
 * @param {{tagName?: string, id?: string, classList?: Iterable<string>, dataset?: Record<string, string | undefined>} | null} el
 */
export function describe(el) {
  if (!el?.tagName) return null;
  const classes = [...(el.classList ?? [])].slice(0, 3).map((c) => `.${c}`);
  const action = el.dataset?.action ? `[data-action=${el.dataset.action}]` : "";
  return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}${classes.join("")}${action}`;
}
