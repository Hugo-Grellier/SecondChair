# Editorial rubric and evaluator sheet

Score what is on the page, not what a good GM could make of it. Scores are 1-5 per dimension; use 2 and 4 between anchors. Never average dimensions.

## Anchors

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| Originality | Stock tropes in stock order; names and setting swappable with any other adventure | Familiar frame with one or two specific, campaign-rooted twists | Premise, NPCs and conflicts could only belong to this campaign; tropes, when used, are turned |
| Character stakes | NPCs exist to deliver information; PCs have no personal reason to care | Main NPCs want something; one PC hook is personal | Every major NPC has a want, a fear and a cost; each PC has a stake tied to their player's stated goals |
| Setup and payoff | Revelations arrive unprepared or contradict earlier material | Most payoffs are set up; some setups lead nowhere | Every revelation has visible causes earlier; foreshadowing is traceable and none is orphaned |
| Player agency | One route; choices change flavour only; a hidden mandatory plot | Two or three routes converge on a fixed scene | Several approaches lead to different, consistent consequences; ignoring a hook has a defined world reaction, not a forced return |
| Clue robustness | A required conclusion hangs on one clue or one roll | Three-clue rule mostly holds; some chokepoints | Every conclusion has 3 or more clues on reachable nodes, proactive leads, and a fallback for missed clues |
| PF2e mechanical integration | Encounters, DCs or treasure missing or wrong for the level | Budgets correct; tactics and terrain generic | Budgets verified, tactics and terrain serve the scene's purpose, non-combat resolutions and rewards fit PF2e |
| Session usability | GM must rewrite before playing; information buried in prose | Usable with some searching and filling gaps | Scannable at the table: an NPC, a scene or a DC is found in seconds; contingencies stated |
| Immersion | Read-alouds flat or overlong; no sensory anchor | Serviceable descriptions | Short, vivid, player-safe read-alouds and NPC voices a GM wants to perform |
| Foundry readiness | Phantom maps, tokens or UUIDs; nothing realised | Scenes realise with gaps listed | Every referenced asset exists in the GM's install; scenes, actors, journals and playlists realise; gaps listed honestly |

Foundry readiness and mechanical integration are checked by tools first (see `bench/editorial.py`); score what the tools cannot see: does the scene serve play.

## Evaluator instructions

1. Read the brief, then the artifact once through, before scoring.
2. Score each dimension alone against the anchors.
3. Tick **uncertain** rather than guess (you lacked information or expertise). An uncertain score is reported but excluded from medians.
4. Cite the passage (file and heading or line) for every score of 1, 2 or 5; one sentence for the others.
5. Do not look at the other reviewer's sheet, how the artifact was produced, or any LLM critique before you submit.
6. List up to three things the GM would have to write or fix before running it.

## Evaluator sheet (copy one per reviewer per artifact)

```yaml
artifact: ""        # random id from the blind render, never the condition
brief: ""           # political-intrigue | dungeon | character-arc | mystery | sandbox
reviewer: ""        # gm | outside
scores:             # score 1-5, uncertain true/false, cite = one sentence with file and heading
  originality:                 {score: , uncertain: false, cite: ""}
  character_stakes:            {score: , uncertain: false, cite: ""}
  setup_and_payoff:            {score: , uncertain: false, cite: ""}
  player_agency:               {score: , uncertain: false, cite: ""}
  clue_robustness:             {score: , uncertain: false, cite: ""}
  pf2e_mechanical_integration: {score: , uncertain: false, cite: ""}
  session_usability:           {score: , uncertain: false, cite: ""}
  immersion:                   {score: , uncertain: false, cite: ""}
  foundry_readiness:           {score: , uncertain: false, cite: ""}
fix_before_running:  # up to three
  - ""
```

## Disagreement record (one per artifact, filled after both sheets are submitted)

A gap of 2 or more on a dimension is recorded with both justifications and discussed. Keep both scores; never write a negotiated one.

```yaml
artifact: ""
gaps:
  - dimension: ""
    gm:      {score: , cite: ""}
    outside: {score: , cite: ""}
    discussion: ""   # what was said; the scores above stay as submitted
```
