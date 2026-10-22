// The Director's Desk (ARC-12, ARC-14, docs/contracts/foundry-bridge.md): the calls due now,
// approve or reject with a reason, the break pile, Start / End session, the situation card the GM
// pulls, the readiness and wrap-state cards, decisions to confirm and the ceiling, read-only. No tabs. It holds no state of its own (ARC-11): the Core sends what to
// show and takes the gestures. Free of Foundry globals, so it runs under `node --test`.

/**
 * @typedef {{id: number, kind: string, responsibility: string, deadline: string, status: string, entry: number | null, message: string | null, detail: string | null, reversible: boolean | null}} DeskCall
 * @typedef {{npc: string, name: string, goal: string, posture?: string, line: string | null, knows: {id: string, statement: string, mode: string}[], does_not_know: {id: string, statement: string}[], voiced: boolean, as_of?: CueAsOf}} ActingCue
 * @typedef {{moment: number, session: number | null, observation: string | null, scene: string | null, round: number | null, turn: number | null, at: string}} CueAsOf
 * @typedef {{id: string, statement: string, mode: string, party_mode?: string}} CardFact
 * @typedef {{as_of: CueAsOf, scene: string | null, acting: string | null, npcs: {id: string, name: string, shared: CardFact[], secret: CardFact[]}[], handoff: string[], calls: {id: number, kind: string, deadline: string, text: string}[]}} SituationCard
 * @typedef {{session: number, status: "queued" | "running" | "waiting", as_of: CueAsOf}} WrapCard
 * @typedef {{check: string, ok: boolean | null, says: string, fix: string | null}} ReadinessCheck
 * @typedef {{ready: boolean, checks: ReadinessCheck[], as_of: CueAsOf}} ReadinessCard
 * @typedef {{type: "desk", moment: string, session: number | null, calls: DeskCall[], decisions: {id: string, text: string, words: string}[], cue: ActingCue | null, situation?: SituationCard | null, wrap?: WrapCard | null, readiness?: ReadinessCard | null, turn_driver?: string | null}} DeskState
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
  // Whether the GM opened the situation card: a view preference of this window, not domain
  // state, kept across re-renders; collapsed by default (ARC-14) and again once withdrawn.
  let cardOpen = false;
  // Whether the GM opened or collapsed the readiness card; null until they do, the card then
  // open only when a check failed. Reset for each new card.
  /** @type {boolean | null} */
  let readinessOpen = null;
  /** @type {Map<string, (result: Result) => void>} */
  const waiting = new Map();
  return {
    get state() {
      return state;
    },
    get cardOpen() {
      return cardOpen;
    },
    /** The GM opened or collapsed the situation card. @param {boolean} open */
    setCardOpen(open) {
      cardOpen = open;
    },
    get readinessOpen() {
      return readinessOpen;
    },
    /** The GM opened or collapsed the readiness card. @param {boolean} open */
    setReadinessOpen(open) {
      readinessOpen = open;
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
      // The readiness card was this connection's: stale once it closed (#196 S3).
      if (state?.readiness) state = { ...state, readiness: null };
      readinessOpen = null;
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
        const shown = state?.situation?.as_of.at;
        const checked = state?.readiness?.as_of?.at;
        state = /** @type {DeskState} */ (message);
        // A withdrawn card, or a new one pulled since: collapsed again.
        if (state.situation?.as_of.at !== shown) cardOpen = false;
        if (state.readiness?.as_of?.at !== checked) readinessOpen = null;
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
 * When a cue was shown or a card pulled, and its round in combat; "" from a Core before as_of.
 * @param {CueAsOf | undefined} asOf
 */
function ageHtml(asOf) {
  if (!asOf?.at) return "";
  const time = new Date(asOf.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const round = asOf.round == null ? "" : `, round ${esc(asOf.round)}`;
  return `<time datetime="${esc(asOf.at)}">As of ${esc(time)}${round}</time>`;
}

/**
 * Facts as a list, a belief or a suspicion labelled as such.
 * @param {{statement: string, mode?: string}[]} facts @param {string} none
 */
const factsHtml = (facts, none) =>
  facts.length
    ? `<ul>${facts.map((f) => `<li>${esc(f.statement)}${f.mode && f.mode !== "knows" ? ` <em>(${esc(f.mode)})</em>` : ""}</li>`).join("")}</ul>`
    : `<p>${none}</p>`;

/**
 * The situation card the GM pulled (#188 D1): GM only, assembled by the Core with no model,
 * withdrawn by the Core once play moves on. Plain words and an empty-state line in each part.
 * Collapsed unless the GM opened it, with the scene and whose turn in its summary.
 * @param {SituationCard | null | undefined} card @param {boolean} open @param {string} hint (empty: none)
 */
function situationHtml(card, open, hint) {
  const pull = `<p><button type="button" data-action="gesture" data-gesture="situation">${card ? "Refresh" : "Show the situation"}</button>${hint ? ` ${hint}` : ""}</p>`;
  if (!card)
    return `<p>A read of the scene: who is here, what the party knows, what to keep secret.</p>\n${pull}`;
  // A fact the party only suspects or believes is not one it knows: listed apart, said so.
  /** @param {CardFact[]} facts */
  const doubted = (facts) =>
    facts.length
      ? `<p>The party only suspects or believes:</p>
<ul>${facts.map((f) => `<li>${esc(f.statement)} <em>(the party ${esc(f.party_mode)} it)</em></li>`).join("")}</ul>\n`
      : "";
  const npcs = card.npcs.length
    ? card.npcs
        .map(
          (n) => `<h4>${esc(n.name)}</h4>
<p>The party knows:</p>
${factsHtml(
  n.shared.filter((f) => f.party_mode === "knows"),
  "Nothing they know.",
)}
${doubted(n.shared.filter((f) => f.party_mode !== "knows"))}<p>Keep secret (the party does not know):</p>
${factsHtml(n.secret, "Nothing.")}`,
        )
        .join("\n")
    : "<p>No NPC seen here yet. An NPC shows up once it speaks in chat or takes a combat turn.</p>";
  const handoff = card.handoff.length
    ? `<ul>${card.handoff.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`
    : "<p>Nothing in your handoff about this scene.</p>";
  const calls = card.calls.length
    ? `<ul>${card.calls.map((c) => `<li>${esc(c.kind)}${c.deadline === "now" ? " · due now" : " · at the break"}: ${esc(c.text)}</li>`).join("")}</ul>`
    : "<p>Nothing waiting about them.</p>";
  return `<details class="secondchair-card"${open ? " open" : ""}>
<summary><strong>GM only</strong> · Scene: ${card.scene ? esc(card.scene) : "none seen yet"}${card.acting ? ` · Turn: <strong>${esc(card.acting)}</strong>` : ""} · ${ageHtml(card.as_of)}</summary>
<h4>Who is here</h4>
${npcs}
<h4>From your handoff</h4>
${handoff}
<h4>Waiting on you</h4>
${calls}
</details>
${pull}`;
}

const WRAP_SAYS = {
  queued: "wrap queued",
  running: "wrap running",
  waiting: "waiting for <code>secondchair wrap</code>",
};
const WRAP_WHY = {
  queued: "The wrap job is queued; no agent has finished it.",
  running: "An agent is working on the wrap job.",
  waiting:
    "The grouped round settles the session's open questions and its dates. It needs an interactive terminal: run <code>secondchair wrap</code> there.",
};

/**
 * The wrap-state card (#196 S1): after End session, until the session is wrapped. A read, with
 * no gesture: the grouped round runs in the CLI. Its summary is the status line.
 * @param {WrapCard | null | undefined} card
 */
function wrapHtml(card) {
  if (!card || !Object.hasOwn(WRAP_SAYS, card.status)) return "";
  return `<details class="secondchair-card secondchair-wrap">
<summary><strong>Session ${esc(card.session)}</strong>: ${WRAP_SAYS[card.status]}</summary>
<p>${WRAP_WHY[card.status]}</p>
</details>
`;
}

/**
 * The readiness card (#196 S3): the Core's checks of this connection. Open by itself only when a
 * check fails, each failure with its one fix; otherwise one collapsed "ready" line the GM can
 * open. A check that cannot be verified (ok null) says so with its fix and opens nothing. Once
 * the GM opens or collapses it, `open` keeps that choice across re-renders.
 * A read, with no gesture: a wrong binding is fixed where the fix says, never from here.
 * Not a `secondchair-card`, whose toggle the module keeps for the situation card.
 * @param {ReadinessCard | null | undefined} card @param {boolean | null} open
 */
function readinessHtml(card, open) {
  if (!card || !Array.isArray(card.checks)) return "";
  const failed = card.checks.filter((c) => c.ok !== true && c.ok !== null).length;
  const unverified = card.checks.filter((c) => c.ok === null).length;
  const ready = card.ready === true && failed === 0;
  const summary = ready
    ? `<strong>Ready</strong>: ${unverified ? `${unverified} check${unverified === 1 ? "" : "s"} could not be verified` : "every check passed at connect"}`
    : `<strong>Not ready</strong>: ${failed || "a"} check${failed === 1 ? "" : "s"} failed`;
  const word = (/** @type {boolean | null} */ ok) =>
    ok === true ? "ok" : ok === null ? "cannot verify" : "<strong>failed</strong>";
  const checks = card.checks
    .map(
      (c) =>
        `<li>${word(c.ok)}: ${esc(c.says)}${c.ok === true || !c.fix ? "" : `<br>Fix: ${esc(c.fix)}`}</li>`,
    )
    .join("");
  return `<details class="secondchair-readiness"${(open ?? !ready) ? " open" : ""}>
<summary>${summary} · ${ageHtml(card.as_of)}</summary>
<ul>${checks}</ul>
</details>
`;
}

/**
 * The active NPC's acting cue (DEL-15): shown at every level, manual included, since it is a read.
 * Its age is the time it was shown; the Core withdraws it once play moves on (ADR 0020 item 3).
 * @param {ActingCue | null} cue
 */
function cueHtml(cue) {
  if (!cue) return "<p>No acting cue.</p>";
  const age = ageHtml(cue.as_of);
  const list = (/** @type {{statement: string, mode?: string}[]} */ facts) =>
    factsHtml(facts, "None.");
  const [gesture, label] = cue.voiced ? ["hand_back", "Hand back"] : ["voice", "I voice this one"];
  return `<p><strong>${esc(cue.name)}</strong> · ${esc(cue.goal)}</p>
${age ? `<p>${age}</p>\n` : ""}${cue.posture ? `<p><em>${esc(cue.posture)}</em></p>\n` : ""}${cue.line === null ? "" : `<p><em>“${esc(cue.line)}”</em></p>\n`}<p>Knows:</p>
${list(cue.knows)}
<p>Does not know:</p>
${list(cue.does_not_know)}
<p><button type="button" data-action="gesture" data-gesture="${gesture}" data-entity="${esc(cue.npc)}">${label}</button></p>`;
}

/** @typedef {{key: string, modifiers?: string[]}} Binding */

/**
 * The keys bound to an action, as Foundry reports them (`game.keybindings.get`): the hint
 * text for the first binding, or a plain line when the GM has unbound it.
 * @param {Binding[] | undefined} bindings
 */
export function keyHint(bindings) {
  const first = bindings?.[0];
  if (!first) return "no key bound";
  const parts = [...(first.modifiers ?? []), first.key.replace(/^(Key|Digit)/, "")];
  return parts.map((k) => `<kbd>${esc(k)}</kbd>`).join("+");
}

/**
 * The Desk's content: nothing at all for a user who is not a GM.
 * `keys` holds the bindings Foundry reports per action; absent, no hint is shown.
 * `readinessOpen` is the GM's choice for the readiness card, null (absent) until they made one.
 * @param {{isGM: boolean, state: DeskState | null, pile: DeskCall[] | null, ceiling: unknown, cardOpen?: boolean, readinessOpen?: boolean | null, keys?: {desk: Binding[], situation: Binding[]}}} args
 */
export function deskHtml({
  isGM,
  state,
  pile,
  ceiling,
  cardOpen = false,
  readinessOpen = null,
  keys,
}) {
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
<p>Moment: ${esc(state.moment)}${live ? ` (session ${state.session})` : ""} · Ceiling: ${esc(ceiling)}${keys ? ` · Open the Desk: ${keyHint(keys.desk)}` : ""}</p>
<p>${session} <button type="button" data-action="gesture" data-gesture="break">Break</button></p>
${readinessHtml(state.readiness, readinessOpen)}${wrapHtml(state.wrap)}<h3>Due now</h3>
${callsHtml(state.calls, "Nothing due now.")}
<h3>Situation</h3>
${situationHtml(state.situation, cardOpen, keys ? keyHint(keys.situation) : "")}
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
