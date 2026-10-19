# 03 — Delegation model

Decisions: [ADR 0003](../adr/0003-core-is-the-only-gateway.md), [ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md); tickets [#6](https://github.com/Hugo-Grellier/SecondChair/issues/6), [#10](https://github.com/Hugo-Grellier/SecondChair/issues/10), [#19](https://github.com/Hugo-Grellier/SecondChair/issues/19). The ceiling's shape was settled by the GM while writing this spec ([README](README.md#amendments-settled-while-writing-this-spec-gm-2026-10-19)).

## Responsibilities

**DEL-01** Eight responsibilities, each delegable independently:

| Responsibility | Covers |
|---|---|
| Prep | Preparing sessions: encounters, scenes, treasure, desired states |
| Memory | Canon and continuity, including session capture and the wrap |
| VTT operations | Generic acts in the VTT (scenes, tokens, journals, doors, playlists) |
| Rules and combat | Acting for GM creatures in encounters; rules checks and discrepancies |
| Living world | The world-turn's rule effects and derived consequences |
| NPCs | NPC behaviour and acting cues |
| Narrative direction | New narrative: new fronts and situations, changed agendas, deaths and exits of named NPCs |
| Disclosure | Anything players get to see or hear: publishing an entry, revealing a token, whispering, an NPC speaking in public |

## Levels

**DEL-02** Four delegation levels, the same for every responsibility. A level belongs to the responsibility, never to an agent.

| Level | Agents… |
|---|---|
| Manual | take no action; they only answer when asked |
| Propose | draft; the GM approves each item before it takes effect |
| Act-then-review | act at once; each action is logged and undoable; the GM reviews afterwards |
| Autonomous | act and surface only exceptions: contradiction with canon, rules ambiguity, irreversible action, failed action. Everything else goes to the action log only |

## Moments

- **DEL-03** Three fixed moments: prep, live session, between sessions. Starting session capture opens *live session*; stopping it opens *between sessions*. The GM can force any moment.
- **DEL-04** Ending the live session queues the "wrap a session" job ([04](04-canon-memory-capture.md)).

## Delegation table

- **DEL-05** One **delegation table** per campaign, stored in its campaign workspace: 8 responsibilities × 3 moments. Each column is the **delegation profile** of one moment.
- **DEL-06** The tool ships three **base profiles**, *read*, *prep* and *play*, as starting points for a column. The GM then edits single cells. Values (settled in planning, 2026-10-19; living world from [#15](https://github.com/Hugo-Grellier/SecondChair/issues/15), memory between sessions from [#14](https://github.com/Hugo-Grellier/SecondChair/issues/14)):

  | Responsibility | read | prep | play |
  |---|---|---|---|
  | Prep | manual | act-then-review | propose |
  | Memory | manual | act-then-review | propose |
  | VTT operations | manual | act-then-review | act-then-review |
  | Rules and combat | manual | manual | act-then-review |
  | Living world | manual | act-then-review | act-then-review |
  | NPCs | manual | propose | propose |
  | Narrative direction | manual | propose | propose |
  | Disclosure | manual | propose | propose |

  Every cell of every base profile has deadline mode *auto*.
- **DEL-06a** A new campaign's delegation table is seeded with *prep* in the prep column, *play* in the live-session column and *prep* in the between-sessions column.
- **DEL-06b** *read* is every responsibility at manual: filling all three columns with it gives the test bench's **baseline** ([10](10-success-bench.md), MET-05).
- **DEL-07** Each cell also carries a **deadline mode**: auto (default), now or break ([ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md)).

### Tool caps

- **DEL-08** Narrative direction cannot go above *propose* in v4. This is a setting, not an architectural constraint. No other responsibility is capped by the tool.
- **DEL-09** An **irreversible action** (a disclosure, a public line) is held at *propose* unless the GM explicitly lifts that limit for the responsibility. Each irreversible action still needs an authenticated approval while held (DEL-29).

### Entity overrides ([#19](https://github.com/Hugo-Grellier/SecondChair/issues/19))

- **DEL-10** An **entity override** is keyed on the **acting entity** (the NPC who speaks, the creature that strikes), never on the entity an action is about. Actions with no acting entity (scene prep, a world-turn) are never affected.
- **DEL-11** Only NPCs, rules and combat, and disclosure accept overrides. Individual entities only; no faction inheritance.
- **DEL-12** Effective level = min(table cell for the moment, override). Caps, the irreversible hold and the ceiling still apply on top.
- **DEL-13** An override is stored in the delegation table, applies to every moment unless restricted to one, and holds until the GM removes it. No automatic expiry.
- **DEL-14** Tightening (adding an override) is accepted from any Surface, including an agent relay, and takes effect at once. Loosening (removing one) requires an authenticated Surface.
- **DEL-15** The Director's Desk acting cue offers "I voice this one" (NPCs and disclosure set to manual for that NPC) and "Hand back" (removes it). At manual the acting cue is still shown, since it is a read.
- **DEL-16** When an override lands, pending calls and queued jobs from that entity for the affected responsibilities are withdrawn with their safe default, logged, and not shown again at the break. Actions already taken at act-then-review stay individually undoable.
- **DEL-17** When entities merge at the wrap, the override follows the surviving entity and the most restrictive one wins.

## Enforcement

- **DEL-18** The **Core** is the single authority. Every delegated action goes through it and is checked against the effective level ([ADR 0003](../adr/0003-core-is-the-only-gateway.md)).
- **DEL-19** The VTT connector enforces an independent **ceiling**, defence in depth: one maximum delegation level, global (not per entity), set by the GM inside the VTT and applied regardless of the active profile.
- **DEL-20** A ceiling refusal is a failed action and a call on the GM.
- **DEL-21** Agents enforce nothing. What an agent believes it may do counts for nothing.
- **DEL-22** While a known turn driver is active, the system adapter refuses monster-turn actions for every GM creature; the delegation table still applies to everything else ([ADR 0013](../adr/0013-third-party-modules-are-evidence-turn-drivers-take-over.md)).

## Delegated actions and the action log

- **DEL-23** Each **delegated action** belongs to exactly one responsibility. A compound act is split into atomic actions, each checked on its own (a goblin strikes under rules and combat, then shouts an insult under disclosure). An act that truly cannot be split takes the most restrictive level.
- **DEL-24** There is a single **action log**. Each entry records the responsibility, the effective level and whether an override lowered it, the acting agent, the source, the before and after state, the runner configuration used for job work, and the approval channel.
- **DEL-25** Each action type is classed as reversible or irreversible at tool registration. A reversible action stays undoable one by one until its moment ends. The log of a moment is then frozen; afterwards only a correction or a retcon changes what it did ([ADR 0009](../adr/0009-world-turn-deterministic-three-effect-classes.md)).
- **DEL-26** Every rejection or undo carries a **rejection reason** from a closed list: contradiction, rules, tone, other.
- **DEL-27** Adding or removing an override, and every approval, rejection, edit, undo or answer, is a logged GM interaction (it counts in GM effort).

## Approvals

- **DEL-28** An approval at *propose* can come from any Surface. An approval relayed by an agent in conversation is accepted for **reversible actions only**, logged "via agent" with the GM's quoted words ([ADR 0003](../adr/0003-core-is-the-only-gateway.md)).
- **DEL-29** Irreversible actions, and decisions entering canon at the GM-decision rank, require an authenticated Surface (interactive CLI, Director's Desk). An agent may prepare such an approval; the GM confirms it in one gesture.

## Calls on the GM ([ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md))

A call is a pending proposal, a surfaced exception or a ceiling refusal.

- **DEL-30** The Core gives every call a **deadline**: *now* if it blocks the current turn or scene, otherwise the next **break** (a pause the GM signals, or the end of the moment). The cell's deadline mode can force now or break.
- **DEL-31** A blocking call forced to break takes its safe default at once and is shown at the break.
- **DEL-32** **Safe default** at the deadline: a proposal is rejected, an exception takes no action; it is logged and shown again at the break. An irreversible action never takes effect by default.
- **DEL-33** A call held until the break is not an **interruption**. Interruptions are counted at the Core, identically on the test bench and with any Surface.
