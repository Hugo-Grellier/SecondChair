# PF2e system automation beyond strikes and moves

Answers [#20](https://github.com/Hugo-Grellier/SecondChair/issues/20). Facts checked on **2026-10-19** against the
`foundryvtt/pf2e` source at commit
[`46f7c3c`](https://github.com/foundryvtt/pf2e/tree/46f7c3cf48e776eef89e4fe843e72e3c9bc721a0) (main, one week after
tag `pf2e-8.6.1`), its git history and `CHANGELOG.md`. All `src:` paths below are relative to that commit; line
numbers are approximate anchors. Strikes and movement are out of scope (covered elsewhere).

## Answer in one table

| Capability | Programmatic entry point | Drivable without a click? | Chat card / GM click needed for |
|---|---|---|---|
| Cast a spell (consume + post) | `SpellcastingEntryPF2e#cast(spell, { rank, slotId, consume, message, messageMode })` | **Yes** | Nothing to cast; the result is a chat card |
| Consume slot / focus / innate use only | `entry.consume(spell, rank, slotIndex?)` | **Yes** | - |
| Prepare a slot, mark expended | `entry.prepareSpell(spell, groupId, slot)`, `entry.setSlotExpendedState(groupId, slot, bool)` | **Yes** | - |
| Focus points | `actor.system.resources.focus {value,max,cap}`, plain `actor.update` | **Yes** | - |
| Heightening | `spell.loadVariant({ castRank })` (fixed + interval heightening); `cast({ rank })` | **Yes** | - |
| Alternate cast modes (e.g. Heal 1/2/3 actions) | `spell.loadVariant({ overlayIds })`; overlays in `spell.system.overlays` | **Yes**, if you pick the overlay id | Card "variant" buttons do the same thing for humans |
| Spell attack roll | `spell.rollAttack(event, attackNumber, { skipDialog, dc, target })` | **Yes** (event can be a synthetic one) | - |
| Spell damage roll | `spell.getDamage({ skipDialog: true, target })` then `DamagePF2e.roll(template, context)`; or `spell.rollDamage(event)` | **Yes** | - |
| Target's saving throw vs spell | `targetActor.saves[fortitude|reflex|will].check.roll({ dc, item, origin, skipDialog })` | **Yes** | Card "Save" button rolls for the clicker's *controlled* tokens only |
| Apply damage / healing | `actor.applyDamage({ damage, token, item, rollOptions, outcome })` | **Yes** | Card "apply damage" buttons apply to controlled tokens only |
| Area / template | `spell.placeTemplate(message?)` (now a Region) | **No**, interactive placement | User drags the region on the canvas |
| Counteract | `spell.rollCounteract(event?)` | **Yes** | - |
| System actions (Demoralize, Trip, Escape, Seek...) | `game.pf2e.actions.get(slug).use({ actors, event, difficultyClass, statistic, rollOptions, ... })` | **Mostly**; dialog shown unless the *running user* has check dialogs off | Pass a synthetic event with `shiftKey` to invert, or call the statistic directly |
| Feat / ability with a cost (free, reaction, 1-3 actions) | `createUseActionMessage(item)` (internal, reached from the sheet); costs read from `item.actionCost` | Posting the card: **yes** (via `item.toMessage`) | Self-effect "apply" button; any follow-up roll |
| Frequency (1/day, 1/round...) | `item.system.frequency.value`; decremented by `createUseActionMessage` | **Yes** (plain update) | - |
| Variable-action spells with no overlay (Force Barrage 1-3) | None: `time.value` is the free-text string `"1 to 3"` | **No** system support | Human chooses and rolls the right number of missiles |
| Reactions as an economy (1 per round, triggers, AoO prompts) | **None** in the system | n/a | Entirely the GM / player, or a third-party module |

## Spells

### Casting, slots and focus

- `SpellcastingEntryPF2e#cast(spell, options)` consumes the resource (unless `consume: false` or the spell is at
  will), then posts the spell card with `actualCast: true` and the computed `castRank`. `CastOptions` is
  `{ slotId?, rank?, consume?, message?, messageMode? }`. [src: `src/module/item/spellcasting-entry/document.ts`
  `cast` ~L268, `src/module/item/spellcasting-entry/types.ts` `CastOptions` ~L56]
- `consume(spell, rank, slotIndex?)` handles every casting style in one place: rituals and zero-cost
  focus/cantrips are free; focus spells deduct `system.resources.focus.value`; prepared (non-flexible) entries mark
  the matching slot expended via the spell collection; innate spells decrement `system.location.uses.value`;
  spontaneous/flexible decrement `system.slots.slotN.value`. Failure returns `false` **and raises a
  `ui.notifications.warn`** on the running client, so a module should pre-check rather than rely on the toast.
  Prepared casting with no resolvable slot **throws**. [src: same file, `consume` ~L280-360]
- Slot preparation and expended state are exposed: `prepareSpell(spell, groupId, slot)` and
  `setSlotExpendedState(groupId, slot, value)`. [src: same file ~L368-378]
- `canCast(spell, { origin })` tells whether an entry may cast a spell (tradition or list match, scroll/wand
  origins). [src: same file ~L243]
- Focus pool lives on the creature as `system.resources.focus` (`value`, `max`, `cap`); there is no dedicated
  refocus API beyond plain updates and the `restForTheNight` macro. [src: `src/module/actor/creature/data.ts`
  ~L213, `src/scripts/set-game-pf2e.ts`]

### Heightening and variants

- `spell.loadVariant({ castRank, overlayIds, entryId })` returns an in-memory clone with heightening layers
  (`heightening.type: "fixed"`) and/or overlays applied; `interval` heightening is resolved at damage time from
  `castRank`. Only one `override` overlay may be applied at once (throws otherwise). `loadBaseVariant()` undoes
  it. [src: `src/module/item/spell/document.ts` `loadVariant` ~L467, `getHeightenLayers` ~L543]
- Multi-mode spells are modelled as overlays. Example: Heal (`time.value: "1 to 3"`) carries overlays for the
  1-action touch, 2-action 30 ft (vs living / vs undead) and 3-action 30 ft emanation forms.
  [src: `packs/pf2e/spells/spells/rank-1/heal.json`]
- Variable cost without overlays is **not** modelled: Force Barrage has `time.value: "1 to 3"` and no overlays,
  so the number of missiles is a human decision. `time.value` is free text; the system only maps it to a glyph.
  [src: `packs/pf2e/spells/spells/rank-1/force-barrage.json`, `src/util/misc.ts` `getActionGlyph` ~L182,
  `src/module/item/spell/data.ts` `time` ~L21]

### Rolls and resolution

- Attack: `rollAttack(event, attackNumber, context)` rolls the entry's statistic with `action: "cast-a-spell"`
  and DC defaulting to the defense statistic. [src: `src/module/item/spell/document.ts` ~L943]
- Damage: `rollDamage(event, mapIncreases?)` reads `castRank` from the clicked DOM element and the current
  user's **targets**; it is UI-shaped. The module-friendly path is `getDamage({ skipDialog, target })` then
  `DamagePF2e.roll`. [src: same file `rollDamage` ~L967, `getDamage` ~L276]
- Saves: the card's `spell-save` button calls `#rollActorSaves`, which rolls for
  `game.user.getActiveTokens()` (controlled tokens of whoever clicks). A module should instead call
  `actor.saves.<type>.check.roll({ dc, item, origin, skipDialog: true })` per target.
  [src: `src/module/chat-message/listeners/cards.ts` `spell-save` ~L119, `#rollActorSaves` ~L341;
  `src/module/system/statistic/statistic.ts` `StatisticRollParameters` ~L647: `dc`, `item`, `origin`, `target`,
  `skipDialog`, `createMessage`, `callback`]
- Damage application through the card also targets controlled tokens; `actor.applyDamage({...})` is the direct
  call, IWR included unless `skipIWR`/`final`. [src: `src/module/chat-message/helpers.ts`
  `applyDamageFromMessage`; `src/module/actor/base.ts` `applyDamage` ~L1076]
- Areas: `placeTemplate()` starts interactive region placement on the canvas; there is no headless
  "place here" parameter. [src: `src/module/item/spell/document.ts` ~L553]
- Card variant buttons (`spell-variant`) just call `loadVariant` and re-render the message, so anything the card
  does here a module can do directly. [src: `cards.ts` ~L146]

## Actions with non-standard costs

- **Cost model.** `ActionCost` for system actions is `"free" | "reaction" | 0..3`
  [src: `src/module/actor/actions/types.ts`]. Feat/ability items expose
  `actionCost: { type: "action"|"reaction"|"free", value: 1..3|null } | null` derived from
  `system.actionType.value` and `system.actions.value`; `passive` returns `null`.
  [src: `src/module/item/feat/document.ts` `actionCost` ~L51, `src/module/item/ability/document.ts` ~L33,
  `src/module/item/ability/data.ts` ~L88-96]. Activities with costs like "1 minute" exist only as text (spell
  `time.value`, item descriptions); the system does not track exploration/downtime durations as costs.
- **System actions registry.** `game.pf2e.actions` is a `Collection<slug, Action>`; each `Action` has `cost`,
  `traits`, `variants` and `use(options)` / `toMessage(options)`. 47 macros use `SingleCheckAction`, 18 use
  `SimpleAction`. Legacy function-style entries (`raiseAShield`, `restForTheNight`, `earnIncome`,
  `steelYourResolve`, `takeABreather`) are kept "until everything has been converted".
  [src: `src/scripts/set-game-pf2e.ts`, `src/module/actor/actions/{types,base,single-check,simple}.ts`,
  `src/module/system/action-macros/`]
- **Dialogs.** Whether a check dialog opens is decided by `eventToRollParams`: without an event, it follows the
  *running user's* `showCheckDialogs` setting; with an event, `shiftKey` inverts it. Action `use()` takes no
  `skipDialog`, so a GM-side module either passes a synthetic `KeyboardEvent`/`PointerEvent` with the right
  `shiftKey`, or bypasses the action and rolls the statistic with `skipDialog: true`.
  [src: `src/module/sheet/helpers.ts` `eventToRollParams` ~L140, `src/module/system/action-macros/helpers.ts`
  ~L173]
- **Using a feat/ability.** `createUseActionMessage(item)` decrements `frequency`, runs crafting abilities, then
  posts either the plain item card or a card with a **self-effect "apply" button**. The button is the only
  built-in way the effect lands; a module can instead create the effect item on the actor itself
  (`system.selfEffect.uuid`). It is not exported on `game.pf2e`. [src: `src/module/chat-message/helpers.ts` ~L18]
- **Reactions.** No reaction economy exists in the system: nothing in `src/module/encounter` or the chat
  listeners tracks reactions per round, trigger windows or Attack of Opportunity prompts. A reaction is just an
  ability whose `actionType` is `reaction` (counted as 1 action where a number is needed). [src: grep of
  `src/module/encounter`, `src/module/chat-message`; `src/module/item/ability/helpers.ts` ~L62]

## Observing what humans did

Cast cards carry `flags.pf2e.origin` with roll options; since 8.5.0 an actual cast (as opposed to "send to
chat") is marked by the roll option `origin:action:slug:cast-a-spell`, and self-effect cards carry
`flags.pf2e.context.type = "self-effect"`. A connector can watch `createChatMessage` and read these instead of
scraping HTML. [src: commit `df5e905` "Add flag to differentiate actual casting from send-to-chat (#22892)",
`src/module/item/spell/values.ts` `CAST_A_SPELL_OPTION`; `chat-message/helpers.ts`]

## Stability across recent versions

- **No published API contract.** The repo documents no public module API or deprecation policy; README only
  states the licence. `game.pf2e` is the de facto surface, and "Export module-subclassable classes (#20216,
  2025-09)" also dropped `PF2e` suffixes from class names, i.e. internal names do move. [src: `README.md`, `CONTRIBUTING.md`,
  commit `c3cd3e2`]
- **Major version = Foundry major.** 7.12.x requires Foundry 13 (`minimum 13.348, maximum 13`); 8.0.0
  (2026-04-10) moved to Foundry 14 only (`minimum 14.360`); 8.6.1 needs `14.361`. A module pins one system
  major per Foundry major. [src: `system.pf2e.json` at tags `pf2e-7.12.2`, `pf2e-8.0.0`, `pf2e-8.6.1`]
- **What moved in the last ~16 months** (git log of the files above since 2025-06):
  - Measured templates replaced by Regions (`71face4`, 8.0): `placeTemplate` now returns a `RegionDocumentPF2e`;
    anything touching templates broke.
  - `actualCast` flag added to `toMessage` (`df5e905`, 2026-08): additive.
  - `loadVariant` chaining fixes (`61c5e0d`, `927ef25`, 2025-07): behavioural, signature unchanged.
  - Spellcasting dialog moved to ApplicationV2/Svelte (`068d166`, 2026-09): UI only.
  - `cast`/`consume`/`prepareSpell`/`setSlotExpendedState`/`loadVariant`/`rollAttack`/`rollDamage` signatures
    are unchanged in that window. The last structural rename was "slot levels" to "slot groups" / `rank`
    (`955c20a`, 2023-12).
- **Data churn is constant.** Every release changes compendium content (action costs corrected, overlays and
  spell effects added, actors replaced by remaster reprints). Anything keyed on compendium ids or on a spell's
  exact overlay ids should resolve them at runtime. [src: `CHANGELOG.md` 7.9.0-8.6.1 "Data Updates"]

## Implications for SecondChair

- The System extension can drive spell casting end to end (consume, heighten, attack, damage, saves, apply)
  without any human click, by calling document methods rather than replaying chat-card buttons. Card buttons
  act on the *clicking user's* controlled tokens and targets, which is the wrong model for a server-side agent.
- Three things stay human or need our own logic: area placement (interactive Region), variable-cost choices not
  encoded as overlays (Force Barrage), and the whole reaction economy (triggers, once-per-round).
- Pin the system major, wrap every call in one System adapter, and expect to re-check `game.pf2e.actions`
  (legacy entries) and template/region code on each major.
