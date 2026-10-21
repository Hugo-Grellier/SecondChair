// The Director's Desk (ARC-12, ARC-14, docs/contracts/foundry-bridge.md): the calls due now,
// approve or reject with a reason, the break pile, Start / End session, decisions to confirm and
// the ceiling, read-only. No tabs. It holds no state of its own (ARC-11): the Core sends what to
// show and takes the gestures. Free of Foundry globals, so it runs under `node --test`.

/**
 * @typedef {{id: number, kind: string, responsibility: string, deadline: string, status: string, entry: number | null, message: string | null, detail: string | null, reversible: boolean | null}} DeskCall
 * @typedef {{npc: string, name: string, goal: string, posture?: string, line: string | null, knows: {id: string, statement: string, mode: string}[], does_not_know: {id: string, statement: string}[], voiced: boolean}} ActingCue
 * @typedef {{type: "desk", moment: string, session: number | null, calls: DeskCall[], decisions: {id: string, text: string, words: string}[], cue: ActingCue | null, turn_driver?: string | null}} DeskState
 * @typedef {{type: "result", id: string, ok: boolean, error?: string, pile?: DeskCall[], message?: string}} Result
 */

/** The rejection reasons, a closed list (DEL-26). */
export const REASONS = ["contradiction", "rules", "tone", "other"];

/** @param {unknown} text */
export const esc = (text) =>
  String(text ?? "").replace(
    /[&<>"']/g,
    (c) =>
      /** @type {Record<string, string>} */ ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[c],
  );

/**
 * The Desk's link to the Core: the last state it sent, the break pile, and gestures.
 * @param {object} args
 * @param {(message: object) => void} args.send  to the Core, over the bridge
 * @param {() => boolean} args.isGM  whether this client's user is a GM
 * @param {() => void} args.onChange  the Desk has something new to show
 */
export function createDesk({ send, isGM, onChange }) {
  /** @type {DeskState | null} */
  let state = null;
  /** @type {DeskCall[] | null} */
  let pile = null;
  let count = 0;
  let closed = false;
  /** @type {Map<string, (result: Result) => void>} */
  const waiting = new Map();
  return {
    get state() {
      return state;
    },
    get pile() {
      return pile;
    },
    dismissPile() {
      pile = null;
      onChange();
    },
    /**
     * Relay one GM gesture; the Core's result.
     * @param {string} gesture @param {Record<string, unknown>} [fields] @returns {Promise<Result>}
     */
    async gesture(gesture, fields = {}) {
      // The Desk is an authenticated Surface only as the GM user (ARC-13, DEL-03a).
      if (!isGM()) throw new Error("Only a GM uses the Director's Desk.");
      if (closed) throw new Error("Not connected to the Core: reload the world to connect again.");
      const id = `g${++count}`;
      /** @type {Promise<Result>} */
      const answered = new Promise((resolve) => waiting.set(id, resolve));
      send({ type: "gesture", id, gesture, ...fields });
      const result = await answered;
      if (gesture === "break" && result.ok) pile = result.pile ?? [];
      // An answered call leaves the pile, which is otherwise as the Core sent it at the break.
      if (pile && result.ok && fields.entry !== undefined)
        pile = pile.filter((c) => c.entry !== fields.entry);
      onChange();
      return result;
    },
    /** The bridge closed: gestures still waiting fail, and no new one is sent. */
    close() {
      closed = true;
      for (const [id, resolve] of waiting)
        resolve({ type: "result", id, ok: false, error: "The connection to the Core closed." });
      waiting.clear();
    },
    get closed() {
      return closed;
    },
    /**
     * A message from the Core; whether it was the Desk's.
     * @param {{type: string, id?: string} & Record<string, unknown>} message
     */
    receive(message) {
      if (message.type === "desk") {
        state = /** @type {DeskState} */ (message);
        onChange();
        return true;
      }
      const resolve = message.type === "result" && waiting.get(String(message.id));
      if (!resolve) return false;
      waiting.delete(String(message.id));
      resolve(/** @type {Result} */ (message));
      return true;
    },
  };
}

/** @param {DeskCall} call */
function callHtml(call) {
  const what = call.detail ?? call.message ?? "";
  const answerable = call.kind === "proposal" && call.status === "open" && call.entry !== null;
  const reasons = REASONS.map((r) => `<option value="${r}">${r}</option>`).join("");
  return `<li class="secondchair-call">
  <p><strong>${esc(call.kind)}</strong> · ${esc(call.responsibility)}${call.reversible === false ? " · <em>irreversible</em>" : ""}${call.status === "defaulted" ? " · safe default applied" : ""}</p>
  <p>${esc(what)}</p>${
    answerable
      ? `
  <p><button type="button" data-action="gesture" data-gesture="approve" data-entry="${call.entry}">Approve</button>
  <select name="reason-${call.entry}" aria-label="Rejection reason">${reasons}</select>
  <button type="button" data-action="gesture" data-gesture="reject" data-entry="${call.entry}">Reject</button></p>`
      : ""
  }
</li>`;
}

/** @param {DeskCall[]} calls @param {string} none */
const callsHtml = (calls, none) =>
  calls.length ? `<ul>${calls.map(callHtml).join("")}</ul>` : `<p>${none}</p>`;

/**
 * The active NPC's acting cue (DEL-15): shown at every level, manual included, since it is a read.
 * @param {ActingCue | null} cue
 */
function cueHtml(cue) {
  if (!cue) return "<p>No acting cue.</p>";
  /** @param {{statement: string, mode?: string}[]} facts */
  const list = (facts) =>
    facts.length
      ? `<ul>${facts.map((f) => `<li>${esc(f.statement)}${f.mode && f.mode !== "knows" ? ` <em>(${esc(f.mode)})</em>` : ""}</li>`).join("")}</ul>`
      : "<p>None.</p>";
  const [gesture, label] = cue.voiced ? ["hand_back", "Hand back"] : ["voice", "I voice this one"];
  return `<p><strong>${esc(cue.name)}</strong> · ${esc(cue.goal)}</p>
${cue.posture ? `<p><em>${esc(cue.posture)}</em></p>\n` : ""}${cue.line === null ? "" : `<p><em>“${esc(cue.line)}”</em></p>\n`}<p>Knows:</p>
${list(cue.knows)}
<p>Does not know:</p>
${list(cue.does_not_know)}
<p><button type="button" data-action="gesture" data-gesture="${gesture}" data-entity="${esc(cue.npc)}">${label}</button></p>`;
}

/**
 * The Desk's content: nothing at all for a user who is not a GM.
 * @param {{isGM: boolean, state: DeskState | null, pile: DeskCall[] | null, ceiling: unknown}} args
 */
export function deskHtml({ isGM, state, pile, ceiling }) {
  if (!isGM) return "";
  if (!state) return "<p>Waiting for the Core…</p>";
  const live = state.moment === "live-session";
  const session = live
    ? `<button type="button" data-action="gesture" data-gesture="end_session">End session ${state.session}</button>`
    : `<button type="button" data-action="gesture" data-gesture="start_session">Start session</button>`;
  const decisions = state.decisions.length
    ? `<ul>${state.decisions
        .map(
          (d) => `<li><p>${esc(d.text)}</p><p><em>“${esc(d.words)}”</em></p>
  <p><button type="button" data-action="gesture" data-gesture="confirm" data-doc="${esc(d.id)}">Confirm as a GM decision</button></p></li>`,
        )
        .join("")}</ul>`
    : "<p>None.</p>";
  return `<section class="secondchair-desk">
<p>Moment: ${esc(state.moment)}${live ? ` (session ${state.session})` : ""} · Ceiling: ${esc(ceiling)}</p>
<p>${session} <button type="button" data-action="gesture" data-gesture="break">Break</button></p>
<h3>Due now</h3>
${callsHtml(state.calls, "Nothing due now.")}
<h3>Acting cue</h3>
${state.turn_driver ? `<p><em>${esc(state.turn_driver)} runs the GM creatures' turns: agents stay silent.</em></p>\n` : ""}${cueHtml(state.cue)}
${
  pile
    ? `<h3>Held for the break</h3>
${callsHtml(pile, "Nothing held for the break.")}
<p><button type="button" data-action="dismiss">Back to play</button></p>`
    : ""
}
<h3>Decisions to confirm</h3>
${decisions}
</section>`;
}
