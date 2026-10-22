// The Director's Desk, module side (ARC-12, ARC-14, docs/contracts/foundry-bridge.md).
import assert from "node:assert/strict";
import { test } from "node:test";
import { createDesk, deskHtml, REASONS } from "../secondchair-foundry/scripts/desk.js";
import { validMessage as valid } from "./schema.js";

/** @typedef {import("../secondchair-foundry/scripts/desk.js").DeskState} DeskState */

/** @type {DeskState} */
const STATE = {
  type: "desk",
  moment: "live-session",
  session: 3,
  calls: [
    {
      id: 1,
      kind: "proposal",
      responsibility: "disclosure",
      deadline: "now",
      status: "open",
      entry: 7,
      message: null,
      detail: "speak by claude-live on lines/1.md: <b>The bell rings.</b>",
      reversible: false,
    },
  ],
  decisions: [{ id: "f-1", text: "The tower fell.", words: "The bell tower fell in 4710." }],
  cue: {
    npc: "e-1",
    name: "Tovan Reed",
    goal: "Keep the party away from the tower.",
    line: "It only rings when the <i>nights</i> are dry.",
    knows: [{ id: "f-2", statement: "The bell rings on dry nights.", mode: "knows" }],
    does_not_know: [{ id: "f-3", statement: "A cracked relay rings the bell." }],
    voiced: false,
    as_of: {
      moment: 7,
      session: 3,
      observation: "o-17",
      scene: "Scene.s1",
      round: null,
      turn: null,
      at: "2026-10-21T20:15:00+00:00",
    },
  },
};

/** A desk wired to a fake Core, which answers each gesture as `answer` says. */
function desk({ isGM = true, answer = (/** @type {object} */ _g) => ({ ok: true }) } = {}) {
  /** @type {object[]} */
  const sent = [];
  let changes = 0;
  const d = createDesk({
    isGM: () => isGM,
    send: (message) => {
      assert.ok(valid(message), JSON.stringify(valid.errors));
      sent.push(message);
      const id = /** @type {{id: string}} */ (message).id;
      const result = { type: "result", id, ...answer(message) };
      assert.ok(valid(result), JSON.stringify(valid.errors));
      queueMicrotask(() => d.receive(result));
    },
    onChange: () => {
      changes += 1;
    },
  });
  return { d, sent, changes: () => changes };
}

test("the state the Core sends is the contract's and is kept for rendering", () => {
  assert.ok(valid(STATE), JSON.stringify(valid.errors));
  const { d, changes } = desk();
  assert.equal(d.receive(STATE), true);
  assert.equal(d.state, STATE);
  assert.equal(changes(), 1);
  assert.equal(d.receive({ type: "session", session: 3 }), false);
});

test("calls due now are shown with approve and a reject reason from the closed list", () => {
  const html = deskHtml({ isGM: true, state: STATE, pile: null, ceiling: "propose" });
  assert.match(html, /data-gesture="approve" data-entry="7"/);
  assert.match(html, /data-gesture="reject" data-entry="7"/);
  for (const reason of REASONS) assert.match(html, new RegExp(`<option value="${reason}">`));
  assert.deepEqual(REASONS, ["contradiction", "rules", "tone", "other"]);
  assert.match(html, /irreversible/);
  assert.doesNotMatch(html, /<b>The bell/, "agent text is escaped");
  assert.match(html, /&lt;b&gt;The bell rings/);
});

test("approve and reject relay the gesture with its reason", async () => {
  const { d, sent } = desk();
  assert.deepEqual(await d.gesture("approve", { entry: 7 }), {
    type: "result",
    id: "g1",
    ok: true,
  });
  await d.gesture("reject", { entry: 7, reason: "tone" });
  assert.deepEqual(sent[1], {
    type: "gesture",
    id: "g2",
    gesture: "reject",
    entry: 7,
    reason: "tone",
  });
});

test("a break the GM signals shows the break pile until the GM goes back to play", async () => {
  const held = { ...STATE.calls[0], deadline: "break" };
  const { d } = desk({ answer: () => ({ ok: true, pile: [held] }) });
  await d.gesture("break");
  assert.deepEqual(d.pile, [held]);
  const html = deskHtml({ isGM: true, state: STATE, pile: d.pile, ceiling: "propose" });
  assert.match(html, /Held for the break/);
  d.dismissPile();
  assert.equal(d.pile, null);
});

test("start and end session follow the moment; a GM decision is confirmed in one gesture", () => {
  const live = deskHtml({ isGM: true, state: STATE, pile: null, ceiling: "propose" });
  assert.match(live, /data-gesture="end_session"/);
  assert.doesNotMatch(live, /data-gesture="start_session"/);
  assert.match(live, /data-gesture="confirm" data-doc="f-1"/);
  const prep = deskHtml({
    isGM: true,
    state: { ...STATE, moment: "prep", session: null },
    pile: null,
    ceiling: "propose",
  });
  assert.match(prep, /data-gesture="start_session"/);
});

test("the active NPC's acting cue offers I voice this one, then Hand back", () => {
  const html = deskHtml({ isGM: true, state: STATE, pile: null, ceiling: "propose" });
  for (const shown of ["Tovan Reed", "Keep the party away", "dry nights", "cracked relay"])
    assert.match(html, new RegExp(shown));
  assert.match(html, /&lt;i&gt;nights/, "the line is escaped");
  assert.match(html, /data-gesture="voice" data-entity="e-1"/);
  assert.doesNotMatch(html, /hand_back/);

  // At manual the cue is still shown, since it is a read.
  const cue = /** @type {NonNullable<DeskState["cue"]>} */ (STATE.cue);
  const voiced = { ...STATE, cue: { ...cue, voiced: true } };
  const manual = deskHtml({ isGM: true, state: voiced, pile: null, ceiling: "propose" });
  assert.ok(valid(voiced), JSON.stringify(valid.errors));
  assert.match(manual, /dry nights/);
  assert.match(manual, /data-gesture="hand_back" data-entity="e-1"/);
  assert.doesNotMatch(manual, /data-gesture="voice"/);

  const none = deskHtml({ isGM: true, state: { ...STATE, cue: null }, pile: null, ceiling: "x" });
  assert.match(none, /No acting cue/);
});

test("the acting cue shows its posture under the goal only when given", () => {
  const cue = /** @type {NonNullable<DeskState["cue"]>} */ (STATE.cue);
  const without = deskHtml({ isGM: true, state: STATE, pile: null, ceiling: "propose" });
  assert.doesNotMatch(without, /Wary/);
  const withPosture = { ...STATE, cue: { ...cue, posture: "Wary <b>and</b> tired" } };
  assert.ok(valid(withPosture), JSON.stringify(valid.errors));
  const html = deskHtml({ isGM: true, state: withPosture, pile: null, ceiling: "propose" });
  assert.match(
    html,
    /Keep the party away[\s\S]*<em>Wary &lt;b&gt;and&lt;\/b&gt; tired<\/em>[\s\S]*dry nights/,
  );
});

test("the acting cue shows its age, and its round in combat", () => {
  const cue = /** @type {NonNullable<DeskState["cue"]>} */ (STATE.cue);
  const html = deskHtml({ isGM: true, state: STATE, pile: null, ceiling: "propose" });
  assert.match(html, /<time datetime="2026-10-21T20:15:00\+00:00">As of [^<,]+<\/time>/);
  const asOf = /** @type {NonNullable<typeof cue.as_of>} */ (cue.as_of);
  const fighting = { ...STATE, cue: { ...cue, as_of: { ...asOf, round: 2, turn: 1 } } };
  assert.ok(valid(fighting), JSON.stringify(valid.errors));
  const combat = deskHtml({ isGM: true, state: fighting, pile: null, ceiling: "propose" });
  assert.match(combat, /As of [^<]+, round 2<\/time>/);
  // A Core from before as_of: the cue renders, with no age line.
  const { as_of: _, ...older } = cue;
  const old = deskHtml({ isGM: true, state: { ...STATE, cue: older }, pile: null, ceiling: "x" });
  assert.match(old, /Tovan Reed/);
  assert.doesNotMatch(old, /As of/);
});

test("while a turn driver is active the acting cue shows no agent's line", () => {
  const cue = /** @type {NonNullable<DeskState["cue"]>} */ (STATE.cue);
  const driven = { ...STATE, turn_driver: "pf2e-combater", cue: { ...cue, line: null } };
  assert.ok(valid(driven), JSON.stringify(valid.errors));
  const html = deskHtml({ isGM: true, state: driven, pile: null, ceiling: "propose" });
  assert.doesNotMatch(html, /only rings/);
  assert.match(html, /pf2e-combater runs the GM creatures' turns: agents stay silent/);
  assert.match(html, /data-gesture="voice" data-entity="e-1"/);
});

test("I voice this one relays the NPC it is for", async () => {
  const { d, sent } = desk();
  await d.gesture("voice", { entity: "e-1" });
  assert.deepEqual(sent, [{ type: "gesture", id: "g1", gesture: "voice", entity: "e-1" }]);
});

test("the ceiling is shown read-only", () => {
  const html = deskHtml({ isGM: true, state: STATE, pile: null, ceiling: "propose" });
  assert.match(html, /Ceiling: propose/);
  assert.doesNotMatch(html, /<select[^>]*ceiling/);
});

test("the Desk has no tabs and never renders for a player", () => {
  const html = deskHtml({ isGM: true, state: STATE, pile: null, ceiling: "propose" });
  assert.doesNotMatch(html, /tab/i);
  assert.equal(deskHtml({ isGM: false, state: STATE, pile: null, ceiling: "propose" }), "");
});

test("a user who is not a GM cannot send a gesture", async () => {
  const { d, sent } = desk({ isGM: false });
  await assert.rejects(d.gesture("start_session"), /GM/);
  assert.deepEqual(sent, []);
});

test("an answered call leaves the break pile", async () => {
  const held = { ...STATE.calls[0], deadline: "break" };
  const { d } = desk({ answer: () => ({ ok: true, pile: [held] }) });
  await d.gesture("break");
  await d.gesture("approve", { entry: 7 });
  assert.deepEqual(d.pile, []);
});

test("once the bridge closes, waiting gestures fail and no new one is sent", async () => {
  /** @type {object[]} */
  const sent = [];
  const d = createDesk({ isGM: () => true, send: (m) => sent.push(m), onChange: () => {} });
  const waiting = d.gesture("break");
  d.close();
  assert.equal((await waiting).ok, false);
  await assert.rejects(d.gesture("break"), /Not connected/);
  assert.equal(sent.length, 1);
});

/** @type {NonNullable<DeskState["situation"]>} */
const CARD = {
  as_of: {
    moment: 7,
    session: 3,
    observation: "o-18",
    scene: "Scene.s1",
    round: 2,
    turn: 1,
    at: "2026-10-21T20:20:00+00:00",
  },
  scene: "Tower",
  acting: "Tovan Reed",
  npcs: [
    {
      id: "e-1",
      name: "Tovan Reed",
      shared: [
        {
          id: "f-2",
          statement: "The bell rings on dry nights.",
          mode: "knows",
          party_mode: "knows",
        },
        { id: "f-5", statement: "Tovan hid the relay.", mode: "knows", party_mode: "suspects" },
      ],
      secret: [
        { id: "f-4", statement: "The vault key hides under the <b>altar</b>.", mode: "knows" },
      ],
    },
  ],
  handoff: ["Tovan Reed lies about the relay."],
  calls: [{ id: 4, kind: "proposal", deadline: "now", text: "speak on lines/1.md" }],
};

test("the situation card reads in plain words: scene, turn, who is here, secrets, handoff", () => {
  const state = { ...STATE, situation: CARD };
  assert.ok(valid(state), JSON.stringify(valid.errors));
  const html = deskHtml({ isGM: true, state, pile: null, ceiling: "propose", cardOpen: true });
  assert.match(
    html,
    /<details class="secondchair-card" open>\n<summary><strong>GM only<\/strong> · Scene: Tower · Turn: <strong>Tovan Reed<\/strong> · <time [^>]+>As of [^<]+, round 2<\/time><\/summary>/,
  );
  assert.match(
    html,
    /<h4>Tovan Reed<\/h4>\n<p>The party knows:<\/p>\n<ul><li>The bell rings on dry nights.<\/li><\/ul>\n/,
  );
  // What the party only suspects is never listed as known.
  assert.match(
    html,
    /<p>The party only suspects or believes:<\/p>\n<ul><li>Tovan hid the relay. <em>\(the party suspects it\)<\/em><\/li><\/ul>/,
  );
  assert.match(
    html,
    /Keep secret \(the party does not know\):<\/p>\n<ul><li>The vault key hides under the &lt;b&gt;altar/,
  );
  assert.match(html, /<li>Tovan Reed lies about the relay.<\/li>/);
  assert.match(html, /<li>proposal · due now: speak on lines\/1.md<\/li>/);
  assert.match(html, /data-gesture="situation">Refresh<\/button>/);
});

test("an empty situation card says so in each part, and none offers to show one", () => {
  const empty = { ...CARD, scene: null, acting: null, npcs: [], handoff: [], calls: [] };
  const state = { ...STATE, situation: empty };
  assert.ok(valid(state), JSON.stringify(valid.errors));
  const html = deskHtml({ isGM: true, state, pile: null, ceiling: "x" });
  assert.match(html, /Scene: none seen yet · <time/);
  assert.doesNotMatch(html, /Turn:/);
  assert.match(html, /No NPC seen here yet/);
  assert.match(html, /Nothing in your handoff about this scene/);
  assert.match(html, /Nothing waiting about them/);
  // Withdrawn or never pulled (and from a Core before it): a button to pull it.
  for (const situation of [null, undefined]) {
    const none = deskHtml({ isGM: true, state: { ...STATE, situation }, pile: null, ceiling: "x" });
    assert.match(none, /data-gesture="situation">Show the situation<\/button><\/p>/);
    assert.doesNotMatch(none, /<kbd>|no key bound/);
    assert.doesNotMatch(none, /GM only/);
  }
});

test("the situation card is collapsed by default and stays as the GM left it across re-renders", () => {
  const { d } = desk();
  const state = { ...STATE, situation: CARD };
  const render = () =>
    deskHtml({ isGM: true, state: d.state, pile: null, ceiling: "x", cardOpen: d.cardOpen });
  d.receive(state);
  assert.match(render(), /<details class="secondchair-card">\n<summary>/);
  d.setCardOpen(true);
  d.receive({ ...state });
  assert.match(render(), /<details class="secondchair-card" open>/);
  d.setCardOpen(false); // the GM collapses it
  d.receive({ ...state }); // the Core sends the Desk again
  assert.match(render(), /<details class="secondchair-card">\n/);
  // Withdrawn, then pulled again: collapsed again.
  d.setCardOpen(true);
  d.receive({ ...STATE, situation: null });
  d.receive(state);
  assert.equal(d.cardOpen, false);
  // A new card pulled within one refresh, never withdrawn in between: collapsed again too.
  d.setCardOpen(true);
  d.receive({ ...state });
  assert.equal(d.cardOpen, true);
  const newer = { ...CARD, as_of: { ...CARD.as_of, at: "2026-10-21T20:21:00+00:00" } };
  d.receive({ ...STATE, situation: newer });
  assert.equal(d.cardOpen, false);
});

test("a player never sees the situation card nor pulls one", async () => {
  const state = { ...STATE, situation: CARD };
  assert.equal(deskHtml({ isGM: false, state, pile: null, ceiling: "propose" }), "");
  const { d, sent } = desk({ isGM: false });
  await assert.rejects(d.gesture("situation"), /GM/);
  assert.deepEqual(sent, []);
});

test("pulling the situation sends the gesture; the card comes with the Core's next state", async () => {
  const { d, sent } = desk();
  const result = await d.gesture("situation");
  assert.deepEqual(sent, [{ type: "gesture", id: "g1", gesture: "situation" }]);
  assert.deepEqual(result, { type: "result", id: "g1", ok: true });
});

test("the shortcut hints show the keys bound: default, rebound, unbound (#196 S4)", () => {
  /** @param {{key: string, modifiers?: string[]}[]} desk @param {{key: string, modifiers?: string[]}[]} situation */
  const render = (desk, situation) =>
    deskHtml({
      isGM: true,
      state: { ...STATE, situation: null },
      pile: null,
      ceiling: "x",
      keys: { desk, situation },
    });
  const defaults = render(
    [{ key: "KeyD", modifiers: ["Shift"] }],
    [{ key: "KeyS", modifiers: ["Shift"] }],
  );
  assert.match(defaults, /Open the Desk: <kbd>Shift<\/kbd>\+<kbd>D<\/kbd>/);
  assert.match(defaults, /Show the situation<\/button> <kbd>Shift<\/kbd>\+<kbd>S<\/kbd>/);
  const rebound = render(
    [{ key: "KeyD", modifiers: ["Shift"] }],
    [{ key: "Digit4", modifiers: ["Control", "Alt"] }],
  );
  assert.match(rebound, /<kbd>Control<\/kbd>\+<kbd>Alt<\/kbd>\+<kbd>4<\/kbd>/);
  assert.doesNotMatch(rebound, /<kbd>Shift<\/kbd>\+<kbd>S<\/kbd>/);
  const unbound = render([], []);
  assert.match(unbound, /Open the Desk: no key bound/);
  assert.match(unbound, /Show the situation<\/button> no key bound/);
});

test("a hint escapes the binding, shows only the first, and passes other codes through", () => {
  const html = deskHtml({
    isGM: true,
    state: { ...STATE, situation: null },
    pile: null,
    ceiling: "x",
    keys: {
      desk: [{ key: 'Key<script>"', modifiers: ['"><b>'] }, { key: "KeyZ" }],
      situation: [{ key: "Numpad4" }],
    },
  });
  assert.doesNotMatch(html, /<script>|<b>/);
  assert.match(html, /&lt;script&gt;&quot;/);
  assert.doesNotMatch(html, /<kbd>Z<\/kbd>/);
  assert.match(html, /Show the situation<\/button> <kbd>Numpad4<\/kbd>/);
});
