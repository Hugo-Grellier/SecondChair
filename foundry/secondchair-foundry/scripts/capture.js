// Durable observation capture (CAP-03, ARC-16; docs/contracts/foundry-bridge.md, "Observations").
// Transplanted from v3's write-ahead capture (BVE-02): every observation is first kept in this
// browser's storage and dropped only once the Core acknowledges it, so a reload, a closed tab or
// an unreachable Core loses nothing; whatever is held is resent on the next connection. Free of
// Foundry globals, so it runs under `node --test`.

/**
 * @typedef {"players" | "gm" | "blind"} Visibility
 * @typedef {{id: string, session: number | null, at: string, scene: string | null, actor: string | null, kind: string, visibility: Visibility, payload: Record<string, unknown>}} Envelope
 * @typedef {{scene?: string | null, actor?: string | null, kind: string, visibility: Visibility, payload: Record<string, unknown>, anytime?: boolean}} Event
 */

/**
 * @param {object} args
 * @param {{load(): unknown[], save(list: Envelope[]): unknown}} args.store  survives a reload
 * @param {() => string} [args.newId]
 * @param {() => Date} [args.now]
 */
export function createCapture({
  store,
  newId = () => crypto.randomUUID(),
  now = () => new Date(),
}) {
  /** @type {number | null} */
  let session = null;
  /** @type {((message: object) => void) | null} */
  let send = null;
  const pending = () => /** @type {Envelope[]} */ (store.load() ?? []);

  return {
    pending,
    /** The live session the Core announced, or null outside one. @param {number | null} id */
    setSession(id) {
      session = id;
    },
    /** Send through `fn` from now on, starting with every observation still held. @param {(message: object) => void} fn */
    connect(fn) {
      send = fn;
      for (const envelope of pending()) fn({ type: "observation", envelope });
    },
    disconnect() {
      send = null;
    },
    /**
     * Capture one event; null outside a live session, unless `anytime` (a kind recorded in every
     * moment, such as a ceiling change), which is then tagged with session null.
     * @param {Event} event @returns {Envelope | null}
     */
    observe({ scene = null, actor = null, kind, visibility, payload, anytime = false }) {
      if (session === null && !anytime) return null;
      /** @type {Envelope} */
      const envelope = {
        id: newId(),
        session,
        at: now().toISOString(),
        scene,
        actor,
        kind,
        visibility,
        payload,
      };
      store.save([...pending(), envelope]);
      send?.({ type: "observation", envelope });
      return envelope;
    },
    /** The Core recorded (or refused for good) `id`: drop it. @param {string} id */
    ack(id) {
      store.save(pending().filter((e) => e.id !== id));
    },
  };
}

/**
 * Who saw a chat message: the whole table, or not (a whisper, even to a player, or GM-only), or
 * nobody but the GM (blind). Only `players` attests what the party knows (ARC-16).
 * @param {{blind: boolean, whisper: unknown[]}} message  `whisper`: the recipients
 * @returns {Visibility}
 */
export function visibilityOf({ blind, whisper }) {
  if (blind) return "blind";
  return whisper.length ? "gm" : "players";
}
