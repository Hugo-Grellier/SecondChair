---
name: quick-help
description: Help the GM at the last minute or during a live session - an improvised NPC, a location, a name, a rumour, a twist, a quick encounter, a rules reminder, what an NPC knows - in a few lines, consistent with SecondChair's canon and the session's prep, and put it in Foundry if the GM wants. Use when the GM asks for quick help, an idea or an NPC right now, during or just before play.
license: Apache-2.0
compatibility: Needs the SecondChair MCP server (secondchair serve). Foundry material needs the Foundry connector and a connected GM client.
metadata:
  secondchair-responsibility: prep
  secondchair-tier: fast
  secondchair-inputs: request
  secondchair-expected-output: A short answer the GM can use at once, consistent with canon, and, only when the GM asked for it, the matching prep note or Foundry document.
---

# Quick help

The GM is about to play or is playing, and needs something now: an NPC the party just decided to talk to, a name, a shop, a rumour, a complication, a quick fight, what someone knows. Speed and consistency matter more than richness. You suggest; the GM runs the table and decides what becomes true by playing it.

## Language

Answer and write everything in the **campaign language** (`campaign_info`), keeping canon's spelling of names. The GM may talk to you in any language.

## Answer fast

1. Check in one or two calls that you are not contradicting canon: `search_entities` for the name or the place (do not reuse a name canon gives to someone else), `search_facts` or `what_knows` when the request touches a known NPC, place or secret. Read `prep/session-<n>/handoff.md` of the current session when it exists: the answer should fit what was prepared.
2. Reply first with something usable in under 15 lines, for example an NPC card:
   - **Name** - role, one-line look; **voice**: one mannerism;
   - **wants**: one thing; **hides**: one thing; **knows**: what is useful to the party, and what they do not know (from canon when the NPC exists);
   - two lines they may say, ready to read.
   For a place: three sensory details, who is there, one thing to find. For a complication: what happens, the DC or the creatures with their levels (`encounter_xp` for a fight when the party's level is known). For a rules question: the rule in two lines, and say when you are unsure.
3. Offer two or three alternatives in one line each only when the GM seems to hesitate.

Never reveal to the players, never publish, never speak in the VTT on your own: a player-facing line goes through the GM. Check any line a player will hear with `check_audience_content` when it touches a secret.

## When the GM keeps it

Only when the GM asks:

- **Keep a trace**: append the card to `session-<n>/improv.md` with `write_prep` (read the file first: it replaces it). It is prep, not canon; what is played becomes canon at the wrap.
- **In Foundry**: an NPC actor with `prepare_document` (`Actor`, from the closest compendium creature as `base`, found with `search_compendium`), a token on the current scene through the scene's desired state (`prepare_scene`, hidden), a GM-only journal note. During a live session prep is usually at *propose*: the action waits for the GM's approval on the Director's Desk; say so.
- **Voice support**: `show_acting_cue` to put the NPC's goal, line and knowledge on the Director's Desk.

Report what you actually wrote or prepared, from the tool results.
