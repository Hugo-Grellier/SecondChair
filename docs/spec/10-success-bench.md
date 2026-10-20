# 10 — Success criteria and test bench

Decisions: [ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md), [ADR 0012](../adr/0012-behaviour-traces-capture-raw-input-with-consent.md); tickets [#9](https://github.com/Hugo-Grellier/SecondChair/issues/9) (amended by [#11](https://github.com/Hugo-Grellier/SecondChair/issues/11)), [#12](https://github.com/Hugo-Grellier/SecondChair/issues/12), [#17](https://github.com/Hugo-Grellier/SecondChair/issues/17), [#22](https://github.com/Hugo-Grellier/SecondChair/issues/22), [#34](https://github.com/Hugo-Grellier/SecondChair/issues/34), [#86](https://github.com/Hugo-Grellier/SecondChair/issues/86).

## What "automatically measurable" means

- **MET-01** Every metric is computed from the action log, plus VTT observations and behaviour traces where stated.
- **MET-02** **Gold sets** are written by hand **once**. After that every run is scored without a human.
- **MET-03** No LLM judge in reference metrics. One may be added later only as a clearly labelled secondary metric.
- **MET-04** The same definitions apply on the **test bench** and in **dogfooding**, where metrics come out at the wrap. A metric that cannot be computed from a real session's action log is not a v4 metric.

## Metrics

| Metric | Computation | Criterion |
|---|---|---|
| **GM effort** (prep, live, post-session validation) | Count and active duration of GM interactions with SecondChair (approve, reject, edit, undo, answer an exception, set or remove an override) plus the GM's manual VTT acts read from behaviour traces. A Director's Desk interaction counts once. Wall-clock kept as secondary data | Gain vs baseline |
| **Interruptions** | Calls on the GM shown during a live session without the GM asking (pending proposals, surfaced exceptions, ceiling refusals), per hour of play and per responsibility. Calls held for the break and answers to GM questions excluded | Gain vs baseline |
| **Continuity errors** | Core-detected contradictions with canon + rejections and undos with reason `contradiction` + failed probes | Floor |
| **Leaks** | `CANARY` strings from secret zones reaching NPC or party knowledge | 0 on every run |
| **Narrative direction** | Invariant: no narrative-direction action above propose, no narrative disclosure without GM approval | 0 on every run |
| **Drift ratio** | Agent-initiated vs GM-initiated narrative decisions; proposed living-world consequences count | Watched for a rise, no target |
| **Acceptance rate**, **failed actions** | Per responsibility; failed actions per hour | Tracked |
| **Capture coverage** | Recall and precision of candidate facts against the gold set | Floor |
| **Agreement rate** (S4) | Share of agent actions matching what the GM actually did | Floor |
| **Language drift** | Share of generated output not in the campaign language, by a deterministic language detector | Tracked |
| **Table friction** | Player frictions from consenting players' traces | Watched over time, no target, never part of GM effort |
| **Cost, latency** | Tokens, cost, p50 / p95 latency per job and per moment; live latency capped by the call's deadline | Cheapest runner configuration meeting every floor |

- **MET-05** Relative criteria (GM effort, interruptions) are stated against a **baseline**: the same scenario with every responsibility at manual. Invariants are absolute zeros. Floors and numeric targets are set after the first baseline measurement, not in this spec.
- **MET-05a** Floors are set in planning (settled 2026-10-19):
  - until they exist, the bench gates only on the invariants and the v3 contracts carried as unit tests; every other metric is reported, not gated;
  - a dedicated "Set floors" planning ticket follows the first delegated run of S0, S1 and S3 on the reference runner configuration (N = 3). The GM sets each floor from the median and min–max; the starting rule is the minimum of the three runs, rounded down. The agreement-rate floor waits for S4;
  - the numbers are recorded in this file and in the bench configuration the harness gates on;
  - floors may rise freely; lowering one is a GM decision written here with its reason;
  - "gain vs baseline" means the delegated median is strictly below the baseline median.
- **MET-06** Interruptions are counted at the Core, so the count does not depend on the Surface ([ADR 0005](../adr/0005-core-schedules-calls-on-the-gm.md)).

## Test bench

- **BEN-01** A **scenario** is one replayable run: a starting state, the Sources fed in, a moment, and a gold set.
- **BEN-02** A **scripted GM** answers proposals and exceptions from the gold set. It produces counts of GM interactions, not durations, and no behaviour traces.
- **BEN-03** Bench baseline: the number of operations the GM would do by hand (each delegated action in the scenario counts as one). Duration baseline: the first dogfooded Beginner Box sessions with SecondChair at read-only. In S4 the recorded session supplies the baseline GM effort.
- **BEN-04** Non-determinism: the regression run uses one reference runner configuration with N = 3, reported as median and min–max. Invariants MUST hold on **every** run. The full host × model × effort matrix runs on demand, per scenario, to choose configurations, and the bench writes the cheapest passing mapping ([02](02-architecture.md), ARC-30).
- **BEN-05** Foundry on the bench: a local instance with a bench world restored from a snapshot on every run, never the players' world. The Foundry licence, the PF2e system and the Beginner Box module stay user-supplied. (A containerised Foundry is bench infrastructure only; SecondChair itself ships no Docker image, [09](09-packaging.md).)
- **BEN-06** The harness, scenario definitions and metrics are public. Private Sources and the gold sets that contain them live in `secondchair-bench-private`, referenced by a configured path. Only S0 runs in public CI, and CI holds no model credentials, neither API keys nor a subscription token (GM decision, 2026-10-20, [#34](https://github.com/Hugo-Grellier/SecondChair/issues/34)): CI runs the S0 harness end to end against a scripted fake runner (report generation, canary failure, recomputation from stored action logs, no LLM judge). The real S0 run (delegated and baseline, N = 3, reference runner configuration) is started locally by the GM through the bench CLI with the GM's own agent host; its report and action logs are kept so the report can be recomputed without re-running agents.

### Scenarios

| | Scenario | Sources | Moment | Measures | Where |
|---|---|---|---|---|---|
| **S0** | Sample rebuild | The sample campaign (bible, 2–3 text session notes) | Prep, between sessions (wrap over the notes) | Probes, canaries, living-world probes, GM effort, the declarative calendar | Public CI on a scripted fake runner, real runs local (BEN-06); public gold set next to the sample |
| **S1** | Westerhold rebuild | Westerhold v3 bible (private Source) | Prep | Probes, canaries, GM effort | Private |
| **S2** | Beginner Box prep | Fresh import of the Beginner Box module in a bench world | Prep | Prep GM effort, failed actions, acceptance rate | Private |
| **S3** | Craig wrap | The two Craig recordings (2026-09-29, ~3 h 20; 2026-10-13, ~3 h 05; 5 speakers, one track each) and the `pf2e-beginner-box` world's chat log | Between sessions | Capture coverage, post-session GM effort, cheapest capture mapping, rules checks replayed from traces | Private |
| **S4** | Live replay, shadow mode | A new Beginner Box session recorded with the SecondChair module (behaviour traces, observations, transcript) | Live session | Interruptions, per-event latency, agreement rate, GM effort vs the recorded baseline | Private |

- **BEN-07** S0 and S1 gold sets contain probes on factions, NPCs (including a secret name), a mystery (2 conclusions, 4 nodes, 7 clues), canaries `CANARY-<zone>-<n>` in every secret zone, and living-world probes (clock state after N weeks, who knows what). The S0 harness asks the fact probes in the GM view through an `answer-probes` job, after the rebuild at both tables, and scores the structured answers of its reply, in workspace entity ids; the probes passed and the continuity errors are reported, not gated (MET-05a, [#86](https://github.com/Hugo-Grellier/SecondChair/issues/86)).
- **BEN-08** S3 gold set: the GM annotates facts on the first hour of each recording, using a WhisperX transcript independent of SecondChair. Versioned once, then frozen.
- **BEN-09** S4 feeds the timestamped traces and transcript in order while agents act at the live profile on a shadow copy of the world. The real GM acts are the implicit gold set. The replay is accelerated; each agent response is judged against a deadline equal to the real gap to the next event, and a late response counts as "too late". S4 needs a session recorded with the module, since the Craig sessions have no behaviour traces ([ADR 0012](../adr/0012-behaviour-traces-capture-raw-input-with-consent.md)).

### The sample campaign ([#22](https://github.com/Hugo-Grellier/SecondChair/issues/22))

- **BEN-10** Size floor: 3 factions; 6 NPCs, one with a secret name and no public name; 4 PCs; 2 fronts, one with `unless`; 3 situations, one active with a deadline and one available with a deadline; 1 mystery (2 conclusions, 4 nodes, 7 clues); canaries in every secret zone; planned treasure; a small hex map; 2–3 synthetic text session notes, no audio. Nothing beyond this until a metric needs it.
- **BEN-11** Its calendar is deliberately different from Absalom: 10 months, a 6-day week, a one-day festival month, a leap interval other than 4 ([ADR 0014](../adr/0014-declarative-campaign-calendar-core-follows-paizo.md)).
- **BEN-12** An agent drafts the bible and notes and the GM reviews them. The GM writes the gold set by hand, once.

## Acceptance of v4

- **BEN-13** v4 is accepted when, on the reference runner configuration:
  - every invariant (leaks, narrative direction) holds on every run of every scenario;
  - continuity, capture coverage and agreement rate meet the floors set after the first baseline;
  - GM effort and interruptions show a gain against the manual baseline;
  - the v3 contracts carried as unit tests pass (world-turn T1–T8, calendar, reconciliation, reliability mechanisms);
  - and one dogfooded real session passes (BEN-14).
- **BEN-14** Dogfooding gate (settled in planning, 2026-10-19): one real Beginner Box session played with the live-session column at *play*, from Start session through the wrap's grouped round. It passes when the invariants hold, the GM never abandons SecondChair mid-session (sets every responsibility to manual or stops `serve` to keep playing, which is logged), and the wrap completes. Its metrics are reported, not held to floors (N = 1). The read-only recorded session that feeds S4 and the duration baseline (BEN-03) comes first.
