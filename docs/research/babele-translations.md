# Babele and PF2e translations in Foundry VTT

Research for issue #16. Question: how Babele and the PF2e translation modules
work, what they translate, how a module reads the translated and the original
name of an entity, and under which licences. Sources read on 2026-10-19:

- Babele: <https://gitlab.com/riccisi/foundryvtt-babele>, commit `f23c71a`
  (2026-05-25), module version 2.9.1.
- French PF2e module `pf2-fr`:
  <https://gitlab.com/pathfinder-fr/foundryvtt-pathfinder2-fr>, commit `2dd849d`
  (2026-10-14), module version 8.6.0.
- German PF2e module `lang-de-pf2e`:
  <https://github.com/Foundry-VTT-PF2-German/lang-de-pf2e> (module.json, GitHub
  licence metadata) and <https://foundryvtt.com/packages/lang-de-pf2e>.
- PF2e system: <https://github.com/foundryvtt/pf2e> (README, LICENSE, `static/lang`).

## 1. Translation has two layers

| Layer | Mechanism | Where the language comes from |
|---|---|---|
| UI strings (sheets, chat cards, rule-element labels) | Foundry core i18n: `languages` entries in a module's `module.json` pointing at `lang/<code>.json`, read with `game.i18n.localize()` | the client's core language setting (`game.i18n.lang`) |
| Compendium content (names, descriptions, embedded items, token names) | Babele, at runtime | translation JSON files registered by a language module |

The PF2e system itself ships only English: `static/lang` holds `en.json`,
`action-en.json`, `kingmaker-en.json`, `re-en.json`, `sf2e-overrides-en.json`.
Every other language comes from a separate community module. Both the French
and the German module declare a dependency on Babele (`pf2-fr` requires
babele >= 2.9.0; `lang-de-pf2e` requires babele >= 2.9.1).

## 2. How Babele works

From the Babele README: it "applies [translations] on the original compendium,
overwriting the mapped properties of the entity in memory without altering the
original content". The pack on disk stays English, so system updates still flow.

- **Hook point.** `module/script/foundry/wrapper.js` wraps
  `CONFIG.DatabaseBackend._getDocuments` and
  `CompendiumCollection.prototype.indexDocument` through libWrapper, so both
  the compendium index and every loaded document arrive already translated.
- **What gets translated** is set by mappings
  (`module/script/mapping/default-mappings.js`). The defaults cover `name` plus
  `description` (or its system path) for Adventure, Actor
  (`system.details.biography.value`, `prototypeToken.name`, embedded items and
  effects), ActiveEffect, Cards, Item, JournalEntry, Scene, RollTable and so on.
  A language module adds system-specific paths with `registerMapping()` and
  custom converters with `registerConverters()`.
- **Translation files** are one JSON per pack, named after the pack id, for
  example `babele/vf/fr/pf2e.vehicles.json`:
  `{"label": "...", "entries": {"Steam Giant": {"name": "<French name>", ...}}}`.
  Entries are keyed by the **English name** by default; embedded items are
  keyed by `_id`. A legacy array format with an `id` per entry is also
  accepted (`translation/translation-entries.js`).
- **Registration.** A module calls `babele.register({module, lang, dir})`
  inside `Hooks.once("babele.init", ...)`. Registrations after init are
  rejected (`DEVELOPER_MIGRATION_2_8_0.md`).

### Reading the translated and the original name

`module/script/translation/document-translation.js` merges the translated
payload into the source document, then adds these fields to it:

```js
translated, hasTranslation, originalName,          // top-level copies
flags: { babele: { translated, hasTranslation, originalName,
                   originalPayload /* optional */, lang /* optional */ } }
```

`originalName` is `source.name`, the English name from the system pack.
So for any document coming from a translated compendium:

- translated name: `doc.name`
- original English name: `doc.flags.babele.originalName`
  (or `doc.getFlag("babele", "originalName")`)
- whether a translation matched: `doc.flags.babele.hasTranslation`

Flags are part of the document source, so they persist when the document is
imported into the world or dropped onto an actor. `pf2-fr` relies on that: in
`translateActorItems` it reads
`fromUuidSync(item._stats.compendiumSource)?.flags?.babele?.originalName`
to retranslate actor items.

The supported API is the `game.babele` facade: `translate(pack, data,
translationsOnly)`, `translateField(field, pack, data)`, `isTranslated(pack)`,
`translateIndex(index, pack)`, `extract(...)`, `mappedCompendiumFor(pack)`,
`translatedCompendiumFor(pack)`. Classes under `module/script/*` are internal.

Babele client settings: `showOriginalName` (default off) shows the English name
next to the translated one in compendium UIs; `searchOriginalName` (default on)
lets compendium search match English names.

## 3. The French module (`pf2-fr`)

- **Scope**: UI strings (`lang/fr.json`, plus rule elements, actions,
  Kingmaker, companions) and the PF2e system and companion compendia: names,
  descriptions, embedded actor items, vehicle fields and so on.
- **Name format is a world setting.** `pf2-fr.name-display` (scope `world`,
  default `vf-vo`) selects a different translation directory:
  `vf-vo` gives `"<French name> (Steam Giant)"`, `vo-vf` gives English first,
  `vf` French only, `vo` English name with French descriptions, `vf-bbe` French
  plus the official Black Book Editions name. **`doc.name` can therefore hold
  both languages.** The README recommends the bilingual modes because many
  automation modules match on English keywords.
- **Proper nouns and terms**: there is a glossary, `data/dictionnaire.md`
  (English name, French name, id), and per-category term files such as
  `data/feats/_folders.json` (`"Alchemist": "<French name>"`). Source files under
  `data/` carry `Name`, `Nom`, `NomBBE` and `État` (`libre` = fan translation,
  `officielle` = Black Book Editions text).
- **Slug**: `pf2fr.js` sets `system.slug` from the English original name when
  it is missing. The PF2e `system.slug` is an English-derived identifier and
  stays stable whatever the display language.

## 4. Licences

| Project | Licence | Notes |
|---|---|---|
| Babele | CC BY 4.0 (README) | plus Foundry's module-development licence |
| PF2e system | Apache-2.0 for code; game content under OGL 1.0a / ORC and Paizo's licence to Foundry Gaming LLC | `static/lang` is English only |
| `pf2-fr` code | Apache-2.0 (`LICENSE`) | repo also ships `OpenGameLicense` and `ORClicence` |
| `pf2-fr` translations | OGL + Paizo Community Use Policy; `officielle` texts belong to Black Book Editions | README: no commercial use; the module may not be a dependency of a non-free module; reusing the `libre` fan translations outside the module needs the translators' permission (Rectulo, Njini) and credit (README, `data/LICENSE.md`) |
| `lang-de-pf2e` | MIT (GitHub licence metadata) | content based mainly on Ulisses' official German texts |

## 5. Facts that bear on SecondChair

1. Proper nouns and terms the GM sees come from Babele at read time. To read
   them, take `doc.name` and `doc.flags.babele.originalName` from Foundry
   through the connector, along with `system.slug` for PF2e. Do not keep a
   copy of the dictionary.
2. `doc.name` is a display string. With `pf2-fr` it may be bilingual
   (`FR (EN)`). Use `originalName` or `slug` as the identity key and `name` as
   the label to reuse in generated text.
3. Babele leaves the source pack and world documents created from scratch
   untouched. Generated content written into the world is not translated by
   Babele, so it has to be generated in the GM's language from the start.
4. The GM's language can be read from `game.i18n.lang` (client) and, for
   `pf2-fr`, `game.settings.get("pf2-fr", "name-display")` (world).
5. Licences: SecondChair may read translations at runtime from the GM's own
   install. It may not bundle or redistribute `pf2-fr` fan translations without
   the translators' permission, and it may not use them commercially. It also
   may not declare `pf2-fr` as a dependency unless SecondChair is free.
