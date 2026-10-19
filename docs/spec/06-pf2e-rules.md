# 06 — PF2e rules coverage

Decisions: [ADR 0011](../adr/0011-foundry-automates-secondchair-checks.md), [ADR 0013](../adr/0013-third-party-modules-are-evidence-turn-drivers-take-over.md); tickets [#20](https://github.com/Hugo-Grellier/SecondChair/issues/20), [#21](https://github.com/Hugo-Grellier/SecondChair/issues/21), [#24](https://github.com/Hugo-Grellier/SecondChair/issues/24), [#25](https://github.com/Hugo-Grellier/SecondChair/issues/25).

## Principle

**Foundry automates, SecondChair understands.** The PF2e system and the automation modules the GM installs do the rules inside Foundry. SecondChair implements no PF2e engine.

- **RUL-01** The PF2e system is a required runtime dependency. Its pack data is never redistributed ([08](08-licensing-repos.md)).
- **RUL-02** The adapter targets one Foundry and system major pair at a time: **Foundry v14 + pf2e 8.x**. The system publishes no API contract, and its major follows Foundry's.

## Acting

- **RUL-03** Agents act only for the GM's creatures (monsters, NPCs, GM-controlled allies), in **encounters** only, under rules and combat. In exploration and downtime SecondChair only checks, and computes for prep.
- **RUL-04** Agents read PC state but never act or roll for a PC. A PC's save is requested from its player. Agents apply damage to PCs as a consequence of a GM creature's action.
- **RUL-05** What agents drive, through system document methods and never through chat-card buttons (those act on the clicking user's selection):
  - strikes and system actions (`game.pf2e.actions`);
  - spells, with resource consumption (prepared and spontaneous slots, focus, innate uses), heightening and variants;
  - saves of GM-controlled targets;
  - damage and its application;
  - conditions.
- **RUL-06** The adapter creates self-effects itself, and creates area Regions from an agent-chosen origin, undoable through the action log.
- **RUL-07** The adapter tracks one reaction per round for each GM creature. Agents fire Reactive Strike-style reactions on a closed trigger list: leaving reach, manipulate or move within reach, ranged attack within reach. A reaction counts as used when the adapter's counter or any known reaction tracker says so.
- **RUL-08** Manual: spells with a variable cost and no overlay (an agent proposes the cost; the GM resolves), every other reaction (shown in the acting cue), and every PC choice and reaction.
- **RUL-09** Monster turns run on SecondChair's own executor in the adapter.
- **RUL-10** An agent action is one system call. Its follow-ups (conditions, effects) are applied only if the GM's modules have not already applied them once the call settles. Whatever stays ambiguous becomes a discrepancy, never a second application.

### Turn drivers

- **RUL-11** Turn drivers are detected by module id on a closed list (PF2e Combater in v4).
- **RUL-12** While a known turn driver is active, the executor and agent reactions are off for every GM creature. The GM runs turns through the driver, agents stay silent, and SecondChair observes, runs rules checks and logs those acts as the GM's. The delegation table still applies to everything else.

## Understanding: rules checks

- **RUL-13** In every mode of play (encounter, exploration, downtime) the adapter enriches observations with each outcome's trace: roll breakdown, DC, degree and its adjustments (`dosAdjustments`), damage instances and IWR applied, resource before and after, conditions before and after.
- **RUL-14** A **rules check**, in the Python System extension, tests one observed outcome for consistency with its own trace:
  - modifiers sum to the total;
  - the degree is consistent with the DC, natural 20 / 1 and the recorded adjustments (the degree is never recomputed from total vs DC alone);
  - HP lost equals damage minus the IWR shown;
  - the resource is decremented;
  - the condition lifecycle holds;
  - an activity's result matches its degree.
- **RUL-15** A check never recomputes inputs from a character sheet or from the full rules. A real calculation is added only when a specific check needs it.
- **RUL-16** Checks run in Python on observations, so the test bench replays them from recorded traces without Foundry.
- **RUL-17** A failed check is a **discrepancy**: a call on the GM under rules and combat, deadline break by default (can be forced to now). Fixing it is a proposal, never automatic. A discrepancy is not attributed to a module; the observation keeps the user and any module flags.

## Third-party modules

- **RUL-18** No hard dependency on any third-party automation module in v4. The only required module is the official translation module for the campaign language ([04](04-canon-memory-capture.md), CAN-21).
- **RUL-19** Third-party flags are optional evidence, read through a closed list of **trace readers**, each written against a known format and silent when the module is absent or its format unknown:
  - PF2e Toolbelt Target Helper chat flags (targets, DC, each save with its degree before and after adjustment, applied damage);
  - PF2e Visioner visibility and cover token flags;
  - reaction trackers: Reaction Checker's combatant flags, Combater's `reactionUsed`, Sundry's `effect-reaction-used`;
  - pf2e's own `dosAdjustments`.
- **RUL-20** When a module changes its flags, its reader falls silent and the check falls back to the pf2e trace alone; the bench catches the drift.
- **RUL-21** A module becomes a hard dependency only by ADR, when it is maintained on the targeted Foundry/system pair and a real check or action cannot work without it.

## House rules and the rules context

- **RUL-22** The **rules context** (active automation modules, their versions, the rules settings known to the adapter) is recorded as an observation at the start of each moment and whenever it changes. Rules checks read it.
- **RUL-23** House rules become visible in three ways:
  - those that write into the trace (`dosAdjustments`, modifiers in the breakdown) are already consistent, since checks never recompute the degree;
  - those held in settings are read from the rules context;
  - those that stay invisible (compendium patches, method wrappers) raise a discrepancy, which the GM can mark as intended.
- **RUL-24** Marking a discrepancy as intended records a named **house rule** in the campaign that silences that kind of rules check. House rules are listed and removable.
