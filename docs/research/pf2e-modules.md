# PF2e automation, house-rule and monster-control modules

Answers [#24](https://github.com/Hugo-Grellier/SecondChair/issues/24). Checked on **2026-10-19** against each
module's GitHub repo (default branch, shallow clone), its `module.json`, its latest GitHub release and its
foundryvtt.com package page. Context: [ADR 0011](../adr/0011-foundry-automates-secondchair-checks.md) (Foundry
automates, SecondChair checks; target pair Foundry v14 + pf2e 8.x) and
[ADR 0004](../adr/0004-foundry-connector-library-plus-system-adapters.md) (connector library plus PF2e adapter).
Paths written `repo:path` are relative to that repo's default branch on the date above.

**Addendum (same day, second pass).** The first pass missed **PF2e Combater**, a live PF2e turn planner and executor
for GM creatures, which overturns its "no usable base" conclusion. It also missed mookAI PF2e, Sundry's reaction
tracker, PF2e Incapacitation Variants and PF2e Utility Buttons. They are added below and marked *(addendum)*.

## Answer in one table

| Module (id) | What it does | Licence | Public surface | Last release | v14 + pf2e 8.x | Readable trace |
|---|---|---|---|---|---|---|
| **PF2e Toolbelt** (`pf2e-toolbelt`, reonZ) | Bundle of ~25 tools; the one that matters is **Target Helper**: per-target saves, damage application and area targeting on chat cards | **None** (no licence file: all rights reserved) | `game.modules.get("pf2e-toolbelt").api.<tool>`; hooks `pf2e-toolbelt.rollSave`, `pf2e-toolbelt.rerollSave` | 3.59.1, 2026-10-14 | Yes: Foundry `14.361`-`14`, pf2e `>=8.4.0` | **Best**: `ChatMessage.flags["pf2e-toolbelt"].targetHelper` holds targets, DC, each target's save roll, degree, modifiers, applied damage |
| **PF2e Visioner** (`pf2e-visioner`, roi007leaf) | Per-observer visibility (observed/concealed/hidden/undetected), cover, Seek/Hide/Sneak/Point Out/Create a Diversion automation, auto-cover | GPL-3.0 | Large `api` (`getVisibility`, `getCover`, `getRollOptions`, `explainVisibility`, setters); hooks `pf2e-visioner.visibilityChanged`, batch hooks | 8.14.6, 2026-10-19 | Yes, loosely: Foundry `>=13.341` verified 14; pf2e `>=7.0.0` **verified 8.2.0** | Token flags `flags["pf2e-visioner"].visibilityV2`, `cover`, `autoCoverMap`, `stateSource`; chat flags for Seek/Sneak |
| **PF2e Workbench** (`xdy-pf2e-workbench`, xdy) | QoL + automation: auto damage roll, persistent damage, dying/wounded/unconscious, frightened/stunned decrement, NPC scaling, mystification, hero point house rules, "house patcher" | Apache-2.0 (code); OGL/Paizo CUP for content | `game.PF2eWorkbench.*` (macro API); hook `xdy-pf2e-workbench.moduleReady` | 7.7.5, 2026-09-04 | Yes: Foundry `14.361`-`14`, pf2e `>=8.4.1` | Few flags (`dyingLastApplied`, `stunReduction`); its effect is mostly ordinary condition updates |
| **PF2e Automations** (`pf2e-automations`, Reyzor) | Applies effects/conditions on failed saves, crit specialisations, ~200 actions/feats/spells, from a declarative rule table | MIT | Settings-stored JSON rule groups; listens to `pf2e-toolbelt.rollSave` | 1.4.9, 2026-09-29 | Yes: Foundry `14.360`-`14.999`, pf2e verified 8.0.2 | Small flags (`roll`, `rollMap`, `dc`); rule table readable in world settings |
| **PF2e Assistant** (`pf2e-assistant`, 7H3LaughingMan) | Same niche as Reyzor's: Demoralize, Trip, Grapple, crit specialisations, Frightened, class features | MIT | Hooks it listens to only; no exported API | v8.1.2, 2026-05-21 | Yes: Foundry `14.360`-`14`, pf2e `>=8.1.2` | `flags["pf2e-assistant"]` process marker |
| **PF2e Reaction Checker** (`pf2e-reaction`, Reyzor) | Detects when a combatant can react (AoO, Shield Block, Nimble Dodge, ~100 reactions), tracks per-round reaction use | Apache-2.0 | None exported; GM whisper prompts | 1.4.3, 2026-06-03 | Yes: Foundry `14.360`-`14.999`, pf2e verified 8.0.2 | **Combatant flags** `flags["pf2e-reaction"].state` (+ counters like `combat-reflexes`) reset on `pf2e.startTurn` |
| **PF2e Modifiers Matter** (`pf2e-modifiers-matter`, shemetz) | Flags which modifiers changed a degree of success | MIT | Hook `modifiersMatter` with `{rollingActor, actorWithDc, targetedToken, significantModifiers, ...}` | 1.16.9, 2026-06-23 | Yes: Foundry `>=13` verified 14; pf2e `>=7.0.0` | Hook only; adds HTML to chat |
| **Isaac's PF2e Automation** (zarex97) | Area targeting as Regions, enforced frequencies, "riders" by degree of success, staged wrappers | MIT | `api` + hooks `<id>.init`, `<id>.counteracted` | v1.7.0, 2026-10-08 | Yes: Foundry `14.361`-`14`, pf2e `>=8.3.0` | Repo 2 weeks old, single author |
| **PF2e Resolution Core** family (Theholycole): Core, Automatic Spell/Ability/Item Resolution, **Combat Simulator** | Compiles PF2e items into "plans" and resolves them; the simulator plays encounters in memory with an expected-value beam-search planner | MIT | `api` (`patches.status()`, `open()`, `oddsCheck()`), hook `pf2eResolutionCoreReady` | Core 0.7.1, 2026-10-17 | Yes: Foundry 14, pf2e `>=8.5.0` | Repos created 2026-10-07/09, single author, "milestone" status |
| **PF2e AI Combat Assistant** (`pf2e-ai-combat-assistant`, AI-DM-Foundry) | LLM suggests the next action for any creature; on GM confirm it rolls the strike / casts the spell | **None** (no licence file) | None | 1.07, ~2025-04 | **No**: Foundry `>=12` verified 12.331, pf2e `>=6.0.0` | Actor flags `turnState` (actions left, MAP), combat flag `designations` |
| **PF2e Combater** (`pf2e-combater`, roileaf) *(addendum)* | Turn planner **and executor** for the acting creature: Auto-fill builds a whole 3-action turn (move, strikes with MAP, spells, skill actions); Run next / Run all executes it through the system, with per-step revert; tracks actions spent, Delay, Ready, reaction used | GPL-3.0 | No usable API: `module.api` holds only `runLiveEngineMatrix` (a self-test); hooks `pf2e-combater.reactionMarkerChanged`, `.turnNavigationChanged` and others are UI events | 2.5.5, 2026-10-19 (33 releases since 2026-10-12) | **Yes**: Foundry `14.361`+ verified `14.364`, pf2e `>=8.3.0` verified 8.3.0; requires `socketlib` | Combatant `flags["pf2e-combater"].reactionUsed`; chat flags `actionSpend`, `actionTurn`; actor flags `intelLedger`, tactic overrides; Region/effect flags `areaRegion`, `areaTimer` |
| **mookAI PF2e** (`mookAI-pf2e`, CircusGM) *(addendum)* | PF2e add-on to mookAI-12: hotkey (or auto below a level) makes the current combatant find a visible target, path, Stride and Strike, then end turn | No licence file (`NOASSERTION`); base mookAI-12 is MIT | None | 1.0.3, last push 2025-02 | **No**: Foundry 12-13, pf2e verified 6.8.1; requires `mookAI-12`, `lib-find-the-path-12` | n/a |
| **mookAI** (dwonderley) | Automates "mook" NPC turns (move + attack) | MIT | None | 0.2.1, 2022 | **No**: dnd5e, Foundry 9 | n/a |
| **Sundry** (`sundry`, ChasarooniZ) *(addendum)* | Grab bag; its **Reaction Tracker** adds a "Reaction Used" effect (with a use counter) when a reaction is used and at combat start until the creature's turn | MIT | `globalThis.sundry.api.reactionUsed(actors)` (used by Combater) | 1.11.2, 2026-10-19 | Foundry `>=12` verified 14; no system pin | Actor effect with slug `effect-reaction-used` |
| **PF2e Incapacitation Variants** (`fvtt-pf2e-incapacitation-variants`, tyrielv) *(addendum)* | House rule: several variants of *when* and *how* the incapacitation trait changes the degree of success | Apache-2.0 | None; libWrapper on `game.pf2e.Check.roll` | 1.4.1, 2026-09-15 | Yes: Foundry verified `14.367`, pf2e verified **8.5.0** | Pushes a `dosAdjustments` entry labelled `IncapacitationVariant` into the check context, which pf2e copies to `flags.pf2e.context.dosAdjustments` |
| **PF2e Utility Buttons** (`pf2e-flatcheck-helper`, oWave) *(addendum)* | Flat-check prompts (concealed, hidden, dim light), Delay button, Spirit/Life Link, emanation apply | MIT | Custom rule elements for flat-check DCs | 0.22.0, 2026-07-15 | Yes: Foundry `14.361`-`14`, pf2e `>=8.1.0` | Not inspected |
| **Smart Combat NPC** (AtranonStudios) | Full NPC turn automation: target choice, pathfinding, flanking, spells | Premium (Patreon), source not public | Unknown | package updated 2026-10 | Foundry 13-14, **dnd5e only** | n/a |
| **Familiar** (`familiar`, Ryan) | Commercial BYOK AI co-GM; "Combat AI" runs monster turns | **PolyForm Shield**, $6/month | MCP + 230 tools | v2.26.0, 2026-10 | Foundry `>=13` verified 14.368, but **monster turns are D&D 5e (2024) only**; on PF2e it does narrative only | n/a |

**Bottom line.** For rules checks, three modules write traces worth reading: Toolbelt's Target Helper (chat message
flags with each target's save), Visioner (token flags with per-observer visibility and cover), and Reaction Checker
(combatant reaction flags). *(Addendum)* **PF2e Combater** is the one live PF2e module that plans and executes a
GM creature's whole turn on Foundry v14 + pf2e 8.x. It is the closest existing thing to an agent-run monster turn,
but it cannot serve as a base: it has no public API to drive, it is GPL-3.0 (so its code cannot be copied into the
Apache-2.0 adapter, ADR 0006), and it moves daily. It is best treated as a **design reference and a coexistence
concern** (both would spend actions and reactions on the same combatant). Every other turn driver is dead (AI Combat
Assistant, mookAI PF2e: v12/13), D&D 5e only, or in-memory only (Theholycole's Combat Simulator).

## Rules automation modules

### PF2e Toolbelt (reonZ/pf2e-toolbelt)

- **What.** Tools registered from `pf2e-toolbelt:src/tools/index.ts`: actionable, anonymous, arp, auto-cover,
  better-chat/effects-panel/inventory/merchant/movement/sheet/trade, character-importer, condition-manager, droppeth,
  giveth, hero-actions, identify, perception, resource-tracker, roll-tracker, share-data, **target-helper**, underground,
  unided.
- **Target Helper** adds a row per target to strike, damage, spell, action, check and area messages, rolls NPC saves
  from the card, and applies damage per target. It also turns pf2e's area Region into targets
  (`createRegionTemplateHook`). [src: `pf2e-toolbelt:src/tools/target-helper/tool/tool.ts`]
- **Trace.** The message flag `flags["pf2e-toolbelt"].targetHelper` is zod-validated
  (`src/tools/target-helper/data/targets-data.ts`). It holds `type` (`area|damage|spell|action|check`), `author`,
  `item`, `targets` and `splashTargets` (token UUIDs), `traits`, `options`, and `saveVariants`, each with
  `{ dc, basic, statistic, saves: { [tokenId]: SaveInstance } }`. It also holds `applied`, which records per target
  which damage rolls were applied. `SaveInstance` (`data/save-instance.ts`) stores `die`, `value`, `roll` (the
  serialised roll), `modifiers`, `notes`, `success`, `unadjustedOutcome`, `dosAdjustments`, `significantModifiers`
  and `rerolled`. This is almost exactly the "DC, roll breakdown, degree before and after adjustment" trace ADR 0011
  wants for saves.
- **API.** `MODULE.apiExpose(tool.key, tool.api)` (`src/main.ts`). Target Helper exposes `getMessageTargets` and
  `setMessageFlagTargets`. Hooks `pf2e-toolbelt.rollSave` and `pf2e-toolbelt.rerollSave` fire with
  `{ data, message, ... }` (`tool/_saves.ts` ~L117, ~L339). Reyzor's PF2e Automations and PF2e Assistant already
  listen to them.
- **Licence.** No licence file in the repo, and GitHub reports `license: null`. Reading its flags is fine, but its
  code cannot be copied.
- **Maintenance.** 3.59.1 on 2026-10-14, frequent releases. The package page lists one line per Foundry major
  (11, 12, 13, 14). Manifest: Foundry `14.361`-`14` verified `14.369`, pf2e `>=8.4.0`, requires `lib-wrapper`.

### PF2e Visioner (roi007leaf/pf2e-visioner)

- **What.** Per-observer to target visibility states and cover, Seek/Hide/Sneak/Point Out/Create a Diversion
  outcome dialogs, an "AVS" auto-visibility system driven by lighting, senses and movement, auto-cover, and custom rule
  elements. Package page: "Some code of this module has been generated by AI, mostly css".
- **API.** `game.modules.get("pf2e-visioner").api` = `Pf2eVisionerApi` (`scripts/main.js` ~L126,
  `scripts/api.js`): `getVisibility(observerId, targetId)`, `getCover`, `getAutoCoverState`,
  `getRollOptions(observerId, targetId)`, `getVisibilityFactors`, `explainVisibility(observer, target)`,
  `setVisibility`, `bulkSetVisibility`, `setCover`, `getVisibilityStates`, `getCoverStates`. It is typed in
  `docs/api-definition.md`. Hooks: `pf2e-visioner.visibilityChanged(observerId, targetId, ...)`,
  `pf2e-visioner.batchStart/batchComplete`, `pf2e-visioner.tokenMovementComplete`.
- **Trace.** On tokens: `flags["pf2e-visioner"].visibilityV2` (per-observer map,
  `scripts/stores/visibility-profile-flag-persistence.js`), `cover`, `autoCoverMap`, `stateSource` (why a state
  holds), `coverOverride`. On chat messages for its actions: `sneakStartStates`, `seekTemplate`, `pointOut`,
  `rollId`. A check can therefore tell whether an NPC strike was rolled against an off-guard or hidden target that
  Visioner considered so.
- **Licence.** GPL-3.0. Reading flags or calling the API from our module is fine; copying code would make the adapter
  GPL.
- **Maintenance.** Very active: 8.14.6 on 2026-10-19, eight releases in the past week.
- **Compatibility caveat.** The manifest declares Foundry `>=13.341` verified `14` with no maximum, and pf2e
  `>=7.0.0` **verified 8.2.0**, so 8.6 is untested by the author. Requires `lib-wrapper` and `socketlib`.

### PF2e Workbench (xdy/xdy-pf2e-workbench)

- **What** (`README.md` "Current features"): NPC mystification, NPC scaling, auto damage roll on hit, automatic
  persistent damage and fast healing, dying/wounded/unconscious automation (including Undying Ferocity), frightened
  and stunned reduction, action-count reminders, breath-weapon recharge reminders, hero point handler.
- **House rules section.** Keeley's Hero Point Rule, extra ancestry/dual-class campaign feat slots, and a
  "house patcher" that permanently rewrites system compendium items from JSON on every load
  (`docs/housepatcher.md`: "definitely a bad idea"). A world with the house patcher on has compendium items that differ
  from pf2e's, which no check can detect from the item alone.
- **API.** `game.PF2eWorkbench = { resetHeroPoints, addHeroPoints, scaleNPCToLevelFromActor, noOrSuccessfulFlatcheck,
  basicActionMacros, autoRollDamage, npcScaler, ... }` (`src/module/xdy-pf2e-workbench.ts` ~L423). Hook
  `xdy-pf2e-workbench.moduleReady`. Integrates with Toolbelt when active (`registerToolbeltWrappers`).
- **Trace.** Few flags (`dyingLastApplied`, `stunReduction`, `rememberedTargets`). Most of its effect is ordinary
  condition and HP updates, so an observation shows them without attribution. The active automations are world/client
  settings (`game.settings` under `xdy-pf2e-workbench`), which the adapter can snapshot.
- **Licence.** Apache-2.0 for code (`LICENSE.md`); packs and assets under OGL, Paizo CUP and their own terms.
- **Maintenance.** 7.7.5 on 2026-09-04. Foundry `14.361`-`14` verified `14.365`, pf2e `>=8.4.1`.

### PF2e Automations (reyzor1991/pf2e-automations) and PF2e Assistant (7H3LaughingMan/pf2e-assistant)

- Both close the same gap: the system posts outcomes but does not apply their consequences (Demoralize's Frightened,
  Trip's Prone, crit specialisation effects, Aid, Battle Medicine immunity...).
- **Reyzor's** is data-driven. Rules are groups of `{trigger, target type, effect}` (`src/rule/ruleTypes.ts`).
  Triggers include `attack-roll`, `damage-taken`, `saving-throw`, `spell-cast`, `start-turn` and `end-turn`; effects
  include `TargetAddCondition`, `SelfEffect`, `TargetDamage`, `RunMacro` and `IncreaseConditionByStep`. They are synced
  from a bundled `rules/config.json` into a world setting by a "Sync Rules" button (`src/helpers.ts` `syncRulesFn`).
  A GM-edited rule table is the closest thing in the ecosystem to declarative house rules, and it is readable from
  `game.settings`. MIT. 1.4.9, 2026-09-29; Foundry `14.360`-`14.999`, pf2e verified 8.0.2.
- **PF2e Assistant** is hard-coded per automation, MIT, v8.1.2 on 2026-05-21; Foundry `14.360`-`14`, pf2e
  `>=8.1.2`. It hooks `pf2e.startTurn`, `pf2e.endTurn`, `createChatMessage` and the Toolbelt save hooks.
- Isaac's PF2e Automation explicitly yields to both: "A spell PF2e Automations or PF2e Assistant already automates
  keeps their riders, not ours" (`isaacs-pf2e-automation:README.md`).

### PF2e Reaction Checker (reyzor1991/foundry-vtt-pf2e-reaction)

- **What.** Detects reaction triggers in `preCreateChatMessage` (attack rolls, movement via `preUpdateToken`,
  targeting) for ~100 reactions (`REACTIONS.md`), including homebrew ones configured in settings. It whispers a GM/owner
  prompt and marks the reaction used.
- **Trace.** Reaction availability lives on the **Combatant**: `flags["pf2e-reaction"].state` (boolean) plus
  counters for multi-reaction features (`triple-opportunity`, `combat-reflexes`, `reflexive-riposte`,
  `quick-shield-block`, `hydra-heads`...). These are reset on `combatStart` and `pf2e.startTurn`
  (`src/hooks.js` `updateCombatantReactionState` ~L48, ~L501, ~L552).
- **Relevance.** ADR 0011 has the adapter "track one reaction per round for each GM creature". If Reaction Checker is
  installed, it already writes that state. The adapter should either read it or make sure both do not double-spend.
  Known issues listed by the author: Nimble Dodge spam with area spells, once-per-day reactions not handled
  (`README.md` "Issues").
- Apache-2.0. 1.4.3, 2026-06-03. Foundry `14.360`-`14.999`, pf2e verified 8.0.2, requires `socketlib`.

### PF2e Modifiers Matter (shemetz/pf2e-modifiers-matter)

- Computes, in `preCreateChatMessage`, which modifiers on the roll or the DC changed the degree of success. It fires
  `Hooks.callAll("modifiersMatter", { rollingActor, actorWithDc, targetedToken, significantModifiers, ... })`
  (`scripts/pf2e-modifiers-matter.mjs` ~L591) and writes no flags. Toolbelt reimplements the same
  `significantModifiers` into its save flag. MIT, 1.16.9 on 2026-06-23, Foundry `>=13` verified 14.

### New PF2e automation stacks (October 2026)

- **Isaac's PF2e Automation** (zarex97, MIT, repo created 2026-10-06, v1.7.0). It places areas as Regions and turns
  them into targets, enforces frequencies ("pf2e records it and never reads it"), and applies "riders" by degree of
  success. It uses one staged wrapper per pf2e method (cast, damage, check, reroll), so it patches system methods
  heavily.
- **PF2e Resolution Core** family (Theholycole, MIT, repos created 2026-10-07 to 10-09). Core 0.7.1 wraps pf2e's
  `applyDamage`, `prepareRuleElements`, `Check.roll` and `CheckRoll#evaluate` (`PF2e-Automation-Core:README.md`).
  Automatic Spell/Ability/Item Resolution compile items into "plans" and post "confirmation-first chat cards". All
  target Foundry 14 + pf2e `>=8.5.0`.
- Both are one-author projects two weeks old with high churn. Treat them as signals of what the system leaves
  undone, not as dependencies.

## Monster turn and combat AI modules

| Module | System | Drives the turn? | State |
|---|---|---|---|
| PF2e AI Combat Assistant | PF2e | LLM suggests the next action; on GM confirm it executes strikes (`strikeAction.variants[i].roll({event})`) and spells (`spellcastingEntry.cast(spell, {rank, slotId})`), tracks actions left and MAP in actor flags (`scripts/main.js` ~L1825, ~L1923, ~L869) | No licence, Foundry 12 / pf2e 6.x, last push 2025-04-06 |
| mookAI | dnd5e | Yes, move + attack | MIT, last commit 2022-01, Foundry 9 |
| Smart Combat NPC | dnd5e | Yes: targeting, pathfinding, flanking, spells, per-token robot toggle | Patreon-gated, source not published |
| Familiar | multi | Combat AI "resolves the attack under real 5e (2024) rules" | PolyForm Shield, paid; on PF2e: "Pathfinder 2e automates its own combat. Familiar runs the story around it." (familiarvtt.com/capabilities) |
| **PF2e Combater** *(addendum)* | PF2e | **Yes, live, step by step.** Planner reads the actor's real strikes, spells (slots, focus, innate, wands/scrolls), system and skill actions, and the grid (walls, reach, threat lines, cover routes). NPC "tactic personalities" (role + temperament), aggro targeting, turn-intent rules. Executor rolls strikes from `action.variants[i]`, casts through `item.cast({ event, rank })`, rolls saves via `statistic.roll({ dc })`, moves tokens through Foundry movement, creates area Regions with a countdown effect, and records revert envelopes (`scripts/engine/execution/*.js`, `CONTEXT.md`). Run all stops at a step needing a choice or the GM. No LLM: heuristic scoring only | GPL-3.0, 2.5.5, Foundry 14 / pf2e 8.3+, one author (roileaf, also Visioner), very high churn |
| mookAI PF2e *(addendum)* | PF2e | Yes, for mooks: target, path, Stride, Strike, end turn; optional auto-run below a level | No licence file, Foundry 12-13, pf2e 6.8, last push 2025-02 |
| PF2e Combat Simulator | PF2e | **No live control**: "The simulations move nothing on the canvas and change no actor". It has an in-memory expected-value planner (`src/engine/planner.js`: "Each creature searches its possible plans for the rest of its turn with a small beam search") over range bands, not the grid | MIT, 0.14.1, Foundry 14 / pf2e 8.5, ~16.7k lines of engine, two weeks old |

- An "Auto Combat AI" package by the same publisher as Smart Combat NPC appears in search results, but its
  foundryvtt.com page returns 404 today.
- Generic Foundry MCP bridges (for example `laurigates/foundryvtt-mcp`, `wanoo/foundry-mcp-gateway`) expose
  documents and tokens to an LLM. They do not model a PF2e turn (actions, MAP, reactions), so they do not count as
  monster control.

**Base for agents running monster turns.** None qualifies as a base, but one is a strong reference:

- *(Addendum)* **PF2e Combater** does live what ADR 0011's adapter must do (strike variants, `cast` with rank,
  save rolls with a DC, movement, Regions, per-step undo, action and reaction accounting). Three things rule it out
  as a base. First, its only exported API is a self-test runner, so an agent could only drive it by scripting its UI.
  Second, it is GPL-3.0, while the Foundry modules are Apache-2.0 (ADR 0006): calling it at runtime is fine, copying is
  not. Third, a single author ships several releases a day. It does show that a heuristic planner over the real
  action set is feasible on v14 + 8.x. If both run in one world they will fight over the same state: Combater counts
  spent actions from chat cards and token movement, and writes its own `reactionUsed` combatant flag (it also reads
  Reaction Checker's flag and Sundry's effect). The adapter must detect it and either defer to it or ask the GM to
  turn off its auto-open and tracking for GM creatures.

- The only PF2e executor (AI Combat Assistant) cannot be reused: it has no licence, targets v12 and has been abandoned
  for 18 months. Its approach is the same as ADR 0011's adapter, which calls `strike.variants[n].roll` and
  `entry.cast` and keeps action/MAP state in flags. That confirms the shape but provides no code.
- The live turn drivers are D&D 5e only, and closed or source-unavailable.
- Theholycole's planner is MIT and PF2e-aware (MAP, flanking, off-guard, spells, morale). As a source of tactical
  heuristics or a scoring oracle it is worth watching. It is not an executor, and it is too young to depend on.

## House rules: where they become visible

- **System variant rules** are world settings under the `pf2e` namespace: `gradualBoostsVariant`, `staminaVariant`,
  `freeArchetypeVariant`, `automaticBonusVariant`, `mythic`, `proficiencyVariant` and the five
  `proficiency*Modifier` values (`foundryvtt/pf2e:src/module/system/settings/variant-rules.ts`). They are cheap to
  snapshot and change math a check would recompute (proficiency without level, ABP).
- *(Addendum)* **Degree-of-success house rules that go through the check context are visible.** PF2e
  Incapacitation Variants wraps `Check.roll` but pushes a labelled entry into `context.dosAdjustments`, and pf2e
  writes `dosAdjustments` and `unadjustedOutcome` into the message's `flags.pf2e.context`
  (`foundryvtt/pf2e:src/module/system/check/check.ts` ~L198-L302, commit `46f7c3c`). A rules check that reads those
  two fields accepts the house-ruled degree and can name it. A check that recomputes the degree from total vs DC
  alone would raise a false discrepancy.
- **Module settings** (Workbench automations and house rules, Reyzor's rule table, Reaction Checker's homebrew
  reactions) are also `game.settings` entries, so they are readable the same way.
- **Invisible to checks:** Workbench's house patcher (rewrites compendium items in place) and any libWrapper patch of
  `Check.roll`, `applyDamage` or `CheckRoll#evaluate` (Resolution Core, Isaac's, Toolbelt). Foundry does not record
  which module made an update (ADR 0011). The adapter can at least record the active modules and their versions
  as observation context.

## Implications for SecondChair

- **Read, do not depend.** The adapter can treat Toolbelt, Visioner and Reaction Checker flags as optional evidence:
  when present, they enrich the trace of an outcome. None needs to be installed. Reading flags creates no licence
  issue even for Toolbelt (unlicensed) and Visioner (GPL).
- **Save checks.** Toolbelt's `targetHelper.saveVariants[*].saves[tokenId]` gives DC, die, total, modifiers and degree
  before and after adjustment per target. That is enough for an internal-consistency check without a re-roll. It is
  the most valuable third-party trace.
- **Reactions.** Coordinate with Reaction Checker's `flags["pf2e-reaction"].state` rather than keep a second counter
  blindly, or detect the module and defer to it. *(Addendum)* There are three such trackers: Reaction Checker
  (combatant flag), Sundry (actor effect `effect-reaction-used`) and Combater (combatant flag `reactionUsed`).
  Combater already reads all three, so the adapter should do the same.
- **Monster turns stay ours.** No module is a usable base. *(Addendum)* PF2e Combater is the reference design to
  study (action facts, execution results with revert envelopes, tactic personalities), and a module to detect and
  stand down from. The adapter's own executor (strikes, `entry.cast`, system
  actions) as ADR 0011 describes it is still required. Combater, the AI Combat Assistant and the Combat Simulator are design
  references only.
- **House rules.** Snapshot `pf2e` variant-rule settings, active module ids and versions, and key automation settings
  into session context, so a discrepancy can be read against them. Accept that compendium patches and method wrappers
  stay invisible.
- **Pin and watch.** Visioner declares pf2e verified 8.2.0 and Reyzor's modules verified 8.0.2, both below 8.6.
  "Supported" in this ecosystem means "not broken yet". A world's module set must be part of what the test bench
  records.
