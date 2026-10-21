# After v4, live assistance stays pull-first and below propose; live speech, faction proposals and an AI GM each amend one decision

Status: accepted 2026-10-21. Nothing here changes v4 by itself: [11-out-of-scope.md](../spec/11-out-of-scope.md), ADR 0005, ADR 0008 and ADR 0009 hold as written until each amendment below lands in its own ADR.

Epic [#187](https://github.com/Hugo-Grellier/SecondChair/issues/187) asks for a live director, speech fusion, faction agency, tactical help and a researched AI GM. v4 excludes live capture, faction simulation by agents, a world-turn during play and the AI GM as a goal, each "from v4 only". This ADR draws the post-v4 horizon so none of them enters through a playbook: it says which issue amends which decision, under which invariants, in which order. Each amendment is then its own accepted ADR, written when its leaf work starts.

| Issue | Amends | What changes | Stays |
|---|---|---|---|
| [#188](https://github.com/Hugo-Grellier/SecondChair/issues/188) pull-first director, [#193](https://github.com/Hugo-Grellier/SecondChair/issues/193) tactical card, [#196](https://github.com/Hugo-Grellier/SecondChair/issues/196) session flow | Nothing for the pull path; ARC-14 (Desk contents) at spec level | The Desk gains read-only cards the GM pulls (situation, NPC turn, readiness). A card is a read like the acting cue: no delegated action, no call | No tabs; Surfaces hold no state; the PF2e system owns mechanics (ADR 0011); a turn driver silences agent suggestions (ADR 0013) |
| #188 proactive cues | ADR 0005 | A new call kind, `cue`: deadline now, a time-to-live, safe default **expire** (dropped, never shown at the break, since a stale cue is wrong), budget and cooldown per hour of play held by the Core. It counts as an interruption | The Core alone decides what reaches the GM and when |
| [#189](https://github.com/Hugo-Grellier/SecondChair/issues/189) live speech | ADR 0008; spec 11 row "Live capture and consolidation during play" | Consented live transcript segments may feed a short-lived, GM-only context window during play | No candidate fact, no canon write and no call from capture during play; consolidation at the wrap; raw audio and transcripts stay Sources outside the workspace; single-track diarization stays out |
| [#192](https://github.com/Hugo-Grellier/SecondChair/issues/192) faction intentions | ADR 0009 ("simulating factions as agents"); LW-02 | The world-turn may queue one ephemeral job per faction that picks from a GM-written action catalogue; a deterministic validator checks cost, prerequisites and conflicts; effects keep the three classes | Never live (LW-05); deterministic and replayable; new narrative at narrative direction; the living world never discloses |
| [#198](https://github.com/Hugo-Grellier/SecondChair/issues/198) AI GM | Nothing now. Lifting DEL-08 needs its own ADR after shadow-mode research | Research only | VIS-01..03; narrative direction capped at propose |

Invariants every amendment must keep, checked on the bench as today:

1. **GM authority.** Narrative direction at most *propose* (DEL-08); anything players see or hear goes through disclosure with its irreversible hold (DEL-09); played outranks every agent output (CAN-06). A suggestion never writes canon or advances the plot.
2. **The Core schedules.** Anything shown to the GM unasked during play is a call with a deadline and a safe default (ADR 0005). A GM-asked answer is not an interruption; an unasked one is.
3. **Consent.** Off by default, in ADR 0012's shape (per user) plus per session, revocable, filtered at the participant's own client before anything is emitted. The GM cannot consent for a player.
4. **Determinism.** Fictional time, resources and world effects move only through deterministic Core steps with keys used once; model output is a proposal a deterministic step validates. The Core calls no model (ADR 0001).
5. **Degradation.** With speech, a runner, the network or SecondChair off, Foundry play and canon are unaffected, and the Desk says what is degraded.
6. **Zero invariants.** Leaks 0 and narrative direction 0 on every run; once the paraphrase-leak metric exists (ai-gm-mode.md G2), no regression on it, and the amendments that widen voicing wait for that metric.

Recommended sequencing, each step gated on the previous one's bench result:

1. **Pull-first director and NPC turn card** (#188 pull, #193, #196 readiness). No ADR amendment. Measured on S4 and dogfooding.
2. **Proactive cues** (ADR 0005 amendment), only once pull shows a GM-effort gain without an interruption rise.
3. **Faction intentions** (ADR 0009 amendment), after recoverable transactions (#169) and temporal semantics (#170); between sessions only, so it adds no live interruption.
4. **Live speech** (ADR 0008 amendment), only once the director is useful without a microphone; it is an input to steps 1–2, not a prerequisite.
5. **AI GM research** in shadow mode only, after 1–4 are measured. A build decision is a separate ADR.

## Considered Options

- **One omnibus ADR enacting everything now**: rejected. It would loosen four decisions at once, with nothing measured, and make one bench regression unattributable.
- **Ship these as playbooks under existing responsibilities**: rejected. A playbook that listens live or simulates factions bypasses ADR 0008 and ADR 0009; that is the backdoor #187 forbids.
- **Defer everything until v4 ships**: rejected for the pull path, which needs no amendment and supplies the baseline every later step is measured against.
- **Proactive cues as a Surface choice** (the Desk pops a cue when it thinks fit): rejected, as in ADR 0005: the interruption count would depend on the Surface.

## Consequences

- Accepting this ADR changes no requirement by itself; it commits each later amendment to name the invariants above and its bench evidence.
- Spec 11 gets a "post-v4 horizon" note pointing here once accepted; its rows change only when the matching amendment is accepted.
- The `cue` call kind adds a safe default (expire) that never applies to proposals or exceptions: a cue is not an approval and has no state to default.
- Live speech brings player audio into the GM's machine during play, so its amendment carries the strictest review (R2: privacy, Sources).
