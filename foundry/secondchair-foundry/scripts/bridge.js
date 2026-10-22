// The bridge to the loopback Core (PKG-07, docs/contracts/foundry-bridge.md).
// Free of Foundry globals, so it runs under `node --test`.

/** The protocol version this module implements (ARC-17). */
export const PROTOCOL_VERSION = "0.1.0";

/**
 * @typedef {{type: "hello", protocol: string, token: string, world: string, campaign: string | null}} Hello
 * @typedef {{type: "welcome", protocol: string, campaign: string, campaign_language: string}} Welcome
 * @typedef {{type: "refused", reason: string, message: string}} Refusal
 * @typedef {{state: "dialing"} | {state: "connected"} | {state: "unreachable", url: string, error?: string} | {state: "refused", reason: string, message: string} | {state: "lost"}} LinkStatus
 */

/**
 * The URL of the Core's bridge on this machine's loopback; it throws on a port that is not one.
 * @param {number} port
 */
export function coreUrl(port) {
  if (!Number.isInteger(port) || port < 1 || port > 65535)
    throw new Error(
      `The Core port must be a whole number from 1 to 65535, not ${port}: fix it in this module's settings, then Retry.`,
    );
  return `ws://127.0.0.1:${port}/foundry`;
}

/**
 * The handshake's first message.
 * @param {{token: string, world: string, campaign?: string | null}} args
 * @returns {Hello}
 */
export function hello({ token, world, campaign }) {
  return { type: "hello", protocol: PROTOCOL_VERSION, token, world, campaign: campaign || null };
}

/**
 * Dial the Core and say hello. Exactly one of the callbacks is called once.
 * @param {object} args
 * @param {string} args.url
 * @param {Hello} args.hello
 * @param {(welcome: Welcome, socket: WebSocket) => void} args.onWelcome
 * @param {(refusal: Refusal) => void} args.onRefused
 * @param {() => void} args.onUnreachable  the socket closed before the Core answered
 * @param {() => void} [args.onPending]  the socket is still not open after `pendingMs`, as while
 *   the browser's local-network prompt waits for an answer (PKG-11); the dial goes on
 * @param {number} [args.pendingMs]
 * @param {number} [args.replyMs]  an open socket with no answer by then is closed, as unreachable:
 *   whatever accepted it is not a Core that answers
 * @param {typeof WebSocket} [args.WebSocketImpl]
 */
export function connect({
  url,
  hello,
  onWelcome,
  onRefused,
  onUnreachable,
  onPending = () => {},
  pendingMs = 5000,
  replyMs = 10000,
  WebSocketImpl = WebSocket,
}) {
  const socket = new WebSocketImpl(url);
  let answered = false;
  const pending = setTimeout(onPending, pendingMs);
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  let silent;
  socket.addEventListener("open", () => {
    clearTimeout(pending);
    socket.send(JSON.stringify(hello));
    silent = setTimeout(() => {
      if (answered) return;
      answered = true;
      onUnreachable();
      socket.close();
    }, replyMs);
  });
  socket.addEventListener("message", (event) => {
    if (answered) return;
    answered = true;
    clearTimeout(silent);
    /** @type {any} */
    let reply = null;
    try {
      reply = JSON.parse(String(event.data));
    } catch {}
    const object = typeof reply === "object" && reply !== null;
    if (object && reply.type === "welcome") return onWelcome(reply, socket);
    // A refusal the Core closes itself; anything else is not a Core this module understands.
    socket.close();
    if (object && reply.type === "refused" && typeof reply.reason === "string")
      onRefused({ type: "refused", reason: reply.reason, message: String(reply.message ?? "") });
    else
      onRefused({
        type: "refused",
        reason: "malformed",
        message:
          "The Core sent a reply this module does not understand: install matching versions of SecondChair and its module.",
      });
  });
  socket.addEventListener("close", () => {
    clearTimeout(pending);
    clearTimeout(silent);
    if (!answered) onUnreachable();
    answered = true;
  });
  return socket;
}

/**
 * The GM client's link to the Core: one dial at a time, and a new one only when asked (the
 * Desk's Retry), so a Core that is down or refuses is never dialed in a loop.
 * @param {object} args
 * @param {() => string} args.url  read at each dial, so a Retry follows a changed port
 * @param {() => Hello} args.hello  built at each dial, so it carries the campaign bound since
 *   and a changed token
 * @param {(welcome: Welcome, socket: WebSocket) => void} args.onWelcome
 * @param {(status: LinkStatus) => void} args.onStatus
 * @param {() => void} [args.onPending]
 * @param {typeof WebSocket} [args.WebSocketImpl]
 */
export function createLink({ url, hello, onWelcome, onStatus, onPending, WebSocketImpl }) {
  /** @type {LinkStatus | null} */
  let status = null;
  /** @type {WebSocket | null} */
  let socket = null;
  /** @param {LinkStatus} next */
  const set = (next) => {
    status = next;
    onStatus(next);
  };
  return {
    get status() {
      return status;
    },
    /** Dial the Core, unless a dial is in flight or connected; whether it dialed. */
    dial() {
      if (status?.state === "dialing" || status?.state === "connected") return false;
      set({ state: "dialing" });
      let dialed = "";
      try {
        dialed = url();
        dialOnce(dialed);
      } catch (error) {
        // A bad port, or a URL the browser refuses at once: no dial in flight, so Retry works.
        set({
          state: "unreachable",
          url: dialed,
          error: String(/** @type {Error} */ (error).message),
        });
      }
      return true;
    },
    /** Drop a welcomed connection this side cannot use, with why. @param {string} message */
    fail(message) {
      set({ state: "refused", reason: "module", message });
      socket?.close();
    },
  };

  /** One socket to `dialed`; it throws at once on a URL the browser refuses. @param {string} dialed */
  function dialOnce(dialed) {
    connect({
      url: dialed,
      hello: hello(),
      onPending,
      WebSocketImpl,
      onWelcome: (welcome, opened) => {
        socket = opened;
        opened.addEventListener("close", () => {
          socket = null;
          if (status?.state === "connected") set({ state: "lost" });
        });
        set({ state: "connected" });
        onWelcome(welcome, opened);
      },
      onRefused: (refusal) =>
        set({
          state: "refused",
          reason: String(refusal.reason),
          message: String(refusal.message),
        }),
      onUnreachable: () => set({ state: "unreachable", url: dialed }),
    });
  }
}
