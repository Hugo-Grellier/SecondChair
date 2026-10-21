# An optional AI GM mode: what stays open, risks, gates

Research for [#198](https://github.com/Hugo-Grellier/SecondChair/issues/198), parent [#187](https://github.com/Hugo-Grellier/SecondChair/issues/187). Research only; no build decision. Horizon in [ADR 0019](../adr/0019-post-v4-live-assistance-and-world-horizon.md) (proposed).

## What v4 already keeps open

- **VIS-01** Narrative direction is capped at propose by a setting (DEL-08), not by architecture.
- **VIS-02** Agents hold no rights; levels belong to responsibilities, so a wider share needs no new rights model.
- **VIS-03** Model work is a job with a contract; another executor can run the same jobs.

So the autonomy ladder maps onto cells of the delegation table, not new machinery:

| Level of autonomy | Delegation today | Possible in v4? |
|---|---|---|
| Answer rules | Rules and combat; quick-help | Yes |
| Run bounded encounters for GM creatures | Rules and combat up to autonomous, under the ceiling | Yes |
| Voice an NPC with vetted knowledge | NPCs and disclosure, irreversible hold lifted for that cell (DEL-09a), audience-checked (CAN-16) | Yes, per GM gesture |
| Describe a permitted scene to players | Disclosure, hold lifted | Yes, per GM gesture |
| Generate new narrative direction | Narrative direction above propose | No: DEL-08 |
| A fully AI-run adventure | All of the above, live, plus speech input | No: DEL-08, ADR 0008, live director |

## Risks

- **Prompt injection from players.** Player speech and chat become model input; a player can steer an AI GM. Players are untrusted input.
- **Paraphrased spoilers.** CAN-16 blocks cited-fact and canary leaks, not paraphrase; the bench only measures it.
- **Irreversibility.** Disclosure cannot be undone; an AI-run scene multiplies irreversible acts.
- **Agency and consent.** Players did not agree to an AI narrator; a non-consenting participant cannot be addressed by one.
- **Silent escalation.** A human-GM session drifting into AI direction without a deliberate gesture.
- **Latency and cost** at live pace, across hours.
- **Continuity** over a long campaign without a human holding the thread.

## Gating conditions before any build ADR

1. Live director ([live-director.md](live-director.md)) and live speech ([speech-fusion.md](speech-fusion.md)) accepted and measured.
2. A paraphrase-leak metric on the bench, with a floor.
3. **Shadow mode**: on S4-style replays, the AI's narrative decisions are logged and scored (continuity, spoilers, latency, disagreement with the real GM, player-agency probes) but never applied.
4. A separate **mode** entered only by an authenticated GM gesture each session, with the ceiling at autonomous, a visible indicator to every player and each player's consent; never entered by a profile change, an agent or a timeout.
5. A human override that stops it at once, and every act in the action log with the existing undo where reversible.
6. A threat model and a capability matrix per ladder level.

## Recommendation

**Defer.** Keep VIS-01..03 intact and DEL-08 at propose. Revisit after gates 1–3 have data; the outcome is a build / defer / reject ADR.

## Proposed leaf issues

| # | Title | Scope | Risk | Deps |
|---|---|---|---|---|
| G1 | Threat model and capability matrix | Per ladder level: inputs, authority, irreversible acts, mitigations | R0 | — |
| G2 | Paraphrase-leak bench metric | Deterministic detector against secret facts; reported, then a floor | R1 | — |
| G3 | Shadow-mode narrative replay | Logged, unapplied narrative decisions on S4; scores above | R1 | G2, live director D9 |
| G4 | Build / defer / reject ADR | From G1–G3 results | R2 | G1–G3 |
