# An optional AI GM mode: threat model and capability matrix

Research for [#198](https://github.com/Hugo-Grellier/SecondChair/issues/198) leaf G1, building on [ai-gm-mode.md](ai-gm-mode.md). Research only: it states what an AI GM would need and what the Core's model already stops, and ends with gates. It makes no build decision; that is G4, the owner's ([ADR 0019](../adr/0019-post-v4-live-assistance-and-world-horizon.md)). Everything here is hypothetical: v4 has no AI GM, and DEL-08 caps narrative direction at *propose*.

## Assets

| Asset | Why it matters | Held in |
|---|---|---|
| **Secrets** (hidden NPC identities, mystery conclusions, unrevealed treasure and world facts) | A spoiler is irreversible and ruins the GM's craft | Canon facts the party does not know; canaries mark them on the bench (BEN-07) |
| **Canon** (facts, decisions, played events, the calendar) | Authority ranks: played over GM decision over source over agent proposal (CAN-06) | The campaign workspace's Markdown and YAML; SQLite is derived |
| **Player data** (voices, chat, names, consent) | Players are not users of SecondChair and did not agree to an AI narrator | Sources outside the workspace; never in the repository |
| **GM authority** (the delegation table, the ceiling, the irreversible hold) | The only thing that makes agent acts the GM's | `delegation.yaml`, the action log |
| **Table trust and agency** | A player must be able to tell who is narrating and to stop it | Not stored; a property of the session |

## Actors and trust

| Actor | Trust | Notes |
|---|---|---|
| GM | Authoritative; authenticated Surface for irreversible approvals (DEL-29) | Chooses the mode; the only party who can lift a hold (DEL-09a) |
| Players | **Untrusted input.** Their speech and chat would become model input | Cannot consent through the GM; no player is authenticated today |
| The agent (model behind a runner) | Untrusted proposer; holds no rights (VIS-02) | Reads and proposes through the Core; the Core calls no model (ADR 0001) |
| Another agent or relay | Can tighten (override, restore a hold) but never loosen (DEL-09a, DEL-14) | A compromised relay can only restrict |
| Foundry module and loopback endpoint | Local, unauthenticated by design (PKG-06, ADR 0010) | The endpoint accepts reads; actions pass the level check |

## Threats

| # | Threat | Asset | What stops it today | Gap for an AI GM |
|---|---|---|---|---|
| T1 | **Prompt injection by a player** steers the narrator or extracts secrets | Secrets, canon | Nothing reads player speech during play (ADR 0008); every agent act goes through the Core | Live speech and chat become input: the largest new surface |
| T2 | **Verbatim leak** of a canary or an unheld entity name | Secrets | `knowledge.guard` (CAN-16) refuses cited-fact, canary and unheld-name leaks; bench invariant of 0 | None for exact strings |
| T3 | **Paraphrase leak** of a secret in new words | Secrets | Not blocked. The bench measures it, reported only (`bench.paraphrase`, G2) | A deterministic overlap detector has a known ceiling (synonym swaps pass); no floor yet |
| T4 | **Irreversible act at speed**: disclosure and public lines cannot be undone | Secrets, trust | Hold at *propose* in every base profile (DEL-09); lifting needs an authenticated Surface per cell | An AI-run scene lifts the hold for many cells at once and multiplies acts |
| T5 | **Silent escalation**: a human-GM session drifts into AI direction | GM authority | DEL-08 cap; a profile change cannot exceed it | A future lift must not be reachable by a profile, an agent or a timeout |
| T6 | **New canon from model output** | Canon | Agent proposals rank lowest (CAN-06); entering canon at GM-decision rank needs an authenticated Surface (DEL-29) | AI-narrated events would need a path to "played" that no agent can open |
| T7 | **Non-consenting players addressed by a narrator** | Player data, trust | Consent is per user and per session, filtered at the participant's client (ADR 0019 invariant 3); nothing player-facing is built | The GM cannot consent for a player; a per-player consent gesture does not exist |
| T8 | **Loss of override**: the GM cannot stop it fast enough | GM authority | Reject and undo exist for reversible acts; restoring a hold is immediate from any Surface | Needs a stop that acts at once on a running mode, not per call |
| T9 | **Continuity drift** over hours without a human holding the thread | Canon | Contradiction refusal, probes on the bench | Unmeasured at live pace; shadow replay (G3) |
| T10 | **Cost and latency** at table pace | Table trust | Calls carry deadlines and safe defaults (ADR 0005) | A stale line is wrong; a safe default of *expire* would silence the narrator |
| T11 | **Player data leaving the machine**: audio, transcripts sent to a provider | Player data | Raw audio and transcripts stay Sources outside the workspace (ADR 0008) | Provider terms and consent for a live path are undecided |

## Capability matrix

Each row is a capability an AI GM would exercise, set against what the delegation model gives today. "Ceiling" is the highest level the cell can reach; "Hold" is the irreversible hold (DEL-09).

| Capability (ladder level) | Responsibility cell | Ceiling today | Hold | Input trust | Irreversible | Needs beyond v4 | Must stay human-directed |
|---|---|---|---|---|---|---|---|
| Answer rules | Rules and combat | Autonomous | n/a | GM-asked | No | Nothing | No |
| Run a bounded encounter for GM creatures | Rules and combat | Autonomous | n/a (VTT state is undoable by log) | GM-set, then game state | Partly (damage applied) | Turn-driver silence of agents (ADR 0013) | The decision to start it |
| Voice an NPC with vetted knowledge | NPCs and disclosure | Autonomous with the hold lifted (DEL-09a) | Lifted per cell, GM gesture | Facts cited and audience-checked (CAN-16) | Yes, a public line | Paraphrase-leak measure (T3) | Which NPC speaks, and the first lift |
| Describe a permitted scene | Disclosure | Autonomous with the hold lifted | Lifted per cell | Cited, party-held facts | Yes | Same as above | What is permitted to be shown |
| React to player speech or chat | none today | none | n/a | **Untrusted** (T1) | Via the act it triggers | Live speech (ADR 0008 amendment), injection controls | Admission of any player input |
| Generate new narrative direction | Narrative direction | **Propose** (DEL-08) | n/a | Model output | Yes, once shown | Its own ADR lifting DEL-08 | Yes, by default: the GM's creative call |
| Write played events into canon | Canon capture | Propose to GM-decision rank (DEL-29) | n/a | Model output | No, but authoritative | A path no agent can open | Yes: the GM decides what was played |
| Enter, leave or stop the mode | none | n/a | n/a | GM only | n/a | An authenticated per-session gesture, a visible indicator, per-player consent | **Yes, always** |

Reading the matrix: the lower four ladder rows map onto existing cells and need no new rights model (VIS-01..03). The rows that do not are exactly input from players, new narrative and entry to the mode, which is why they carry the gates below.

## What must stay human-directed whatever is decided

- Entering the mode, per session, by an authenticated GM gesture (never a profile, an agent, a timeout or a setting change), with a visible indicator and each player's consent.
- The stop: a human override that halts the mode at once.
- What counts as played and what enters canon at the GM-decision rank (CAN-06, DEL-29).
- Lifting any irreversible hold, as today (DEL-09a).
- Admission of any player-originated text or audio to a model context.

## Gates and outcomes

Gates are conditions to check, not decisions. G4 chooses among them.

**Build** only when all hold:

1. The live director and live speech are accepted and measured ([live-director.md](live-director.md), [speech-fusion.md](speech-fusion.md)).
2. The paraphrase-leak metric exists and has history on the bench; a floor is a separate GM decision (MET-05a), not set here.
3. Shadow-mode replay on S4 shows continuity, spoiler and agency scores acceptable to the owner (G3).
4. Injection controls for player input (T1) are specified and tested with invented material.
5. Entry, consent, indicator and stop (T5, T7, T8) are specified as one separate mode.

**Defer** while any gate above is open: this is the recommendation in [ai-gm-mode.md](ai-gm-mode.md). DEL-08 stays at *propose*; no leaf work widens a cell toward AI direction.

**Reject** if any of these is found:

- No mitigation for T1 or T3 that a bench can measure without a model judge (MET-03).
- Consent for every player cannot be obtained and revoked at the participant's own client.
- The mode cannot be entered and stopped by a human alone, or can be reached by any non-human path.
- A leak or narrative-direction breach (the zero invariants) that shadow mode cannot hold at 0.

## Open questions for G4

- Whether the first measured level is NPC voicing only, short of any new narrative.
- Whether an indicator and consent can be done in Foundry without a per-player SecondChair client.
- Where player identity comes from, since no player is authenticated today.
