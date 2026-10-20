// The bridge to the loopback Core (PKG-07, docs/contracts/foundry-bridge.md).
// Free of Foundry globals, so it runs under `node --test`.

/** The protocol version this module implements (ARC-17). */
export const PROTOCOL_VERSION = "0.1.0";

/**
 * @typedef {{type: "hello", protocol: string, token: string, world: string, campaign: string | null}} Hello
 * @typedef {{type: "welcome", protocol: string, campaign: string, campaign_language: string}} Welcome
 * @typedef {{type: "refused", reason: string, message: string}} Refusal
 */

/**
 * The URL of the Core's bridge on this machine's loopback.
 * @param {number} port
 */
export function coreUrl(port) {
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
  WebSocketImpl = WebSocket,
}) {
  const socket = new WebSocketImpl(url);
  let answered = false;
  const pending = setTimeout(onPending, pendingMs);
  socket.addEventListener("open", () => {
    clearTimeout(pending);
    socket.send(JSON.stringify(hello));
  });
  socket.addEventListener("message", (event) => {
    if (answered) return;
    answered = true;
    const reply = JSON.parse(String(event.data));
    if (reply.type === "welcome") onWelcome(reply, socket);
    else onRefused(reply);
  });
  socket.addEventListener("close", () => {
    clearTimeout(pending);
    if (!answered) onUnreachable();
    answered = true;
  });
  return socket;
}
