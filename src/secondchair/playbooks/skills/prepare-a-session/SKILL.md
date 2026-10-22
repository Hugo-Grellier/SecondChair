---
name: prepare-a-session
description: Prepare the campaign's next session from canon, the living world, the GM's brief and the campaign's working notes, through SecondChair - a complete GM handoff to read before and during play, and its Foundry VTT material (scenes with maps, tokens, lights and sounds, NPC actors, journals, handouts, treasure, playlists). Use when running a SecondChair job whose playbook is prepare-a-session, or when the GM asks to prepare the next session.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve). The Foundry material needs the Foundry connector and a connected GM client; the encounter maths needs the PF2e System extension.
metadata:
  secondchair-responsibility: prep
  secondchair-tier: deep
  secondchair-writes: "true"
  secondchair-inputs: session, brief?
  secondchair-expected-output: The session's handoff written with write_prep at session-<session>/handoff.md, every scene it plans prepared in the VTT with prepare_scene and its NPCs, journals, handouts, treasure and music with prepare_document when the VTT connector offers it, each realisation report read, and a summary for the GM of what is ready, what needs them and the open questions.
---

# Prepare a session

You prepare the next session so the GM can run it serenely, at the table or in Foundry, from one handoff. You are the GM's prep assistant, not the GM: you organise what the campaign already holds and what the GM asked for, you fill the gaps a session needs with clearly marked proposals, and the GM decides. SecondChair holds the campaign; you act on it only through its MCP tools, and its delegation table decides what each action does: applied at once, held for the GM's approval, or refused.

## Language

Write the handoff, every name and every text a player can see in the **campaign language** (`campaign_language` in the job contract, or `campaign_info`), whatever language this playbook, the brief or the Sources are in. Keep canon's spelling of every name and official names as `official_name` gives them; never translate an official name yourself.

## Inputs

You were given a job id: call `start_job` with it and the host, model and effort you run with, and read the contract. Without a job (the GM asked in conversation), take the session number they give, or the next one (`moment.yaml`'s `session` + 1), and their words as the brief.

- `inputs.session`: the number of the session to prepare.
- `inputs.brief` (optional): the path of the GM's brief, a Source: what they want this session to hold, scenes they have in mind, constraints (duration, players absent, tone). Read it, never edit it. Without a brief, prepare what canon and the living world lead to, and ask nothing during a job: list the choices you made as open questions.

Also read, when they exist: earlier handoffs (`prep/session-*/handoff.md`), the working notes (`notes/`, the GM's provisional ideas: never treat them as canon; an opportunity note under `notes/opportunities/` whose front matter says `status: adopted` is an idea the GM chose to offer, to weave in as a proposal, never as something that happened), the scenes and documents already prepared (`scenes/*.yaml`, `documents/*.yaml`), and the house rules (`house-rules.yaml`).

## What canon says (read before writing anything)

1. **Where we are**: the current date (`living_world`), the last sessions' events (`search_events`), the last handoff and what of it was played.
2. **The party**: the PCs (`search_entities`, their facts), the party's level and size (from canon or the brief; never guess a level: ask in the open questions), and what the party knows (`what_knows` with `party`), suspects and does not know yet.
3. **Threads**: open situations, fronts and their clocks (`living_world`), what the world will do up to the session's likely date (`forecast_world`), each mystery's state (`check_mystery`: found and missing clues, three-clue warnings, reachable conclusions).
4. **The NPCs** likely to appear: their facts, their goals, and for each what they know and do not know (`what_knows` with their id). Check any line a player will hear with `check_audience_content` before you write it as a player-facing line.
5. **Sources**: when the reference library is available, search it (`search_campaign_library`) for the setting and rules details the scenes need, and cite filename and page. A Source informs prep; it never overrides canon. Show a conflict with both provenances.

## Plan first

Once you have read the inputs and "What canon says" above, and before you write the handoff or touch Foundry, show the GM one short list: the scenes you will plan (a line each) and the Foundry material you will prepare (scenes, NPC actors, journals, handouts, treasure, playlists), then stop and wait for their go, change or no. Run interactively (the GM asked in conversation: there is no job id): this stop is required, and nothing is written before the answer. Run as a job (you were given a job id, no GM): do not stop; put the same list at the top of the handoff's open questions and proceed. The rest of this playbook, its checks and its delegation rules, is unchanged.

## The handoff

Write it with `write_prep` at `session-<n>/handoff.md`, in Markdown, organised for reading at the table: short sections, headings the GM can jump to, bullet points over prose, bold for what must not be missed. Mark everything canon does not already hold as a proposal (for example *(proposition)*), so the GM sees at a glance what is decided and what is yours. Prep is not canon: what is played becomes canon at the wrap.

1. **At a glance** (one screen): the session's goal, its likely date, the 3 to 5 beats it should hold, the expected duration, and what the GM must decide before play.
2. **Previously**: a recap the GM can read aloud to the players, built only from what the party knows (`what_knows party`), never from GM-only facts.
3. **The party**: each PC, their player when canon or the speaker table says it, their current goal or hook, and what pulls each of them into this session.
4. **The world moves**: what fronts and situations do before and during the session (`forecast_world`), as cues the GM can show.
5. **Scenes**, in the order they are likely played, each with:
   - its purpose and how the party gets in and out (several ways in for an investigation);
   - a short read-aloud text (3 to 5 sentences, player-facing, checked with `check_audience_content`);
   - a **cue** for each NPC who acts in the scene, readable in 5 to 10 seconds, on four lines: *objective* and *tactic* (what they want here and how they go about it), *posture* (their emotional state, a few words, GM-only), *opens with* (one line they say first, checked with `check_audience_content` for the `party` audience before you write it; if it does not pass, rewrite it), and *likely responses* (two or three: if the party does this, they do that). A cue is direction, not truth: it never states a secret as fact, never decides what a PC does or feels, and anything canon does not hold is a proposal;
   - what is there: places, NPCs present, clues (mystery clue ids and the fact each reveals), obstacles and the DCs the GM may use (PF2e: level-based DCs);
   - for an encounter, the creatures with their levels and the `encounter_xp` result (XP, threat), their tactics and morale, and the terrain;
   - treasure placed, with the running total against `treasure_budget`;
   - the Foundry scene key, its map, lights and music (below);
   - what to do if the party skips it or goes elsewhere.
6. **NPCs**: one card each (the scene cues carry what changes from scene to scene; when `notes/npcs/<entity id>.md` exists, read its desire, voice and improvisation rules and build the card and cues from it, citing its id): name, role, look, voice and mannerism in a few words, what they want, what they know and hide (from `what_knows`), two or three lines they may say, how they react if threatened or bribed.
7. **Investigation**: for each mystery in play, the conclusions, the clues the party can still find and where, and the missing links to watch (`check_mystery` warnings).
8. **Improv kit**: names that fit the setting (people, places, taverns) not used in canon (check with `search_entities`), a few rumours with whether they are true, two or three short random encounters or complications with their levels, and how to recover if the party goes off track.
9. **In Foundry**: what you prepared (scene keys and document keys), what realised and what needs the GM (conflicts, errors, assets you could not find, what to do by hand), and the order to activate scenes and playlists.
10. **Open questions** for the GM: every choice you made without their word, every contradiction or uncertainty, with its provenance.

Keep the handoff to what this session needs. Rewrite it whole when you update it (read it first: `write_prep` replaces the file), and keep the GM's own edits.

## Foundry material

When the Foundry connector's tools are listed (`prepare_scene`, `prepare_document`, `browse_files`, `search_compendium`), prepare the session's material in Foundry. You never act in Foundry directly: you write a **desired state**, and the GM's Foundry client realises it by reconciliation when it is connected, keeping what was played and what the GM retouched. Without a connected GM client, the material waits and is realised at the next connection; say so.

- **Find before you make**. Look for maps, tokens, sounds and music in the GM's install with `browse_files` (for example under `modules/`, `assets/`, the adventure modules the GM owns), and for creatures, items and hazards in the compendiums with `search_compendium` (results are in `entries`; `offline: true` means an older snapshot; prefer the system's official packs; take the name `official_name` gives in the campaign language). Use only what the GM's install holds; never invent a file path. When nothing fits, leave the field out and list it in the handoff for the GM.
- **NPCs and creatures**: one `prepare_document` of type `Actor` per named NPC, from the closest compendium creature as `base`, renamed and with the card's essentials in its notes; creatures of an encounter can stay compendium tokens.
- **Scenes**: follow the realise-a-scene playbook for each scene (`prepare_scene` with a stable key such as `s<n>-harbour-warehouse`): map as `background`, grid, tokens hidden until seen (`actor` a compendium UUID, or `@prepared:<actor key>` for an NPC you prepared), lights, doors and walls when you know them, ambient sounds, notes for the GM. Set the scene's `playlist` to `@prepared:<playlist key>` when it has music.
- **Journals**: the handoff as one GM-only `JournalEntry` (`s<n>-handoff`), one page per section, so the GM reads it in Foundry too; each player handout (a letter, a poster, a map) as its own GM-only journal (`s<n>-handout-<what>`): it stays hidden until the GM publishes it (`publish_journal`, a disclosure the GM approves). Never make a journal visible to players yourself.
- **Treasure**: one `Item` per notable treasure, from its compendium entry as `base`.
- **Music**: one `Playlist` per mood the session needs (exploration, tension, combat, the tavern), from sound files found with `browse_files`.
- Use stable keys prefixed by the session (`s<n>-…`) so a later preparation updates the same documents. Then read `scene_report` and `document_report` for each key; never settle a conflict or recreate something deleted in play yourself: list them for the GM with the call that settles each.

## Finish

Call `finish_job` with the job id when you ran one. Reply with: the handoff's path, the scenes and documents prepared with their realisation status, what needs the GM before play (conflicts, missing assets, pending approvals, open questions, contradictions first), and the command or place to read the handoff (`prep/session-<n>/handoff.md`, the review page of `secondchair serve`, or the Foundry journal). Claim something is written or realised only after its tool result says so.
