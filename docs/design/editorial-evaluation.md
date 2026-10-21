# Design: editorial quality and table-use evaluation

Status: proposal — awaiting the GM's decisions ([#182](https://github.com/Hugo-Grellier/SecondChair/issues/182), epic [#173](https://github.com/Hugo-Grellier/SecondChair/issues/173)). Binds nothing until accepted.

S0–S4 ([spec 10](../spec/10-success-bench.md)) measure effort, interruptions, continuity, capture, leaks and cost. An adventure can pass all of them and still be generic, railroaded or unusable at the table. This track judges that, with humans, **beside** the bench and never inside it.

## Fit with spec 10

- **MET-03** (no LLM judge in reference metrics): kept. Scores come from human reviewers. An LLM critique may be shown to the *author* as an editorial aid, labelled as such, and is never a score.
- **MET-02 / MET-04** (gold set written once, then scored with no human; a metric must come from a real session's action log): human rubric scores fail both by construction. **Conflict with #182 as worded**: its rubric cannot be a v4 metric. Resolution proposed here: editorial scores are a separate, reported-only track. They never gate BEN-13, never set floors, and never replace an invariant. If the GM wants them to gate a release, that needs an ADR amending spec 10.
- The deterministic parts below (checker warnings, leaks, frictions, cost, edit size) *are* computable from workspace files, the action log and behaviour traces, so they can be computed without a human. They still do not all come from the action log, observations and traces as MET-01 and MET-04 require (a note's diff size and checker warnings read workspace files), so they join the same reported-only track as the rubric, next to MET-02/MET-04 above, unless a MET-01 amendment admits workspace-file metrics.

## Rubric

Each dimension is scored 1–5 by each reviewer, with an optional **uncertain** flag (the reviewer lacked information or expertise) and one sentence citing the passage that justifies the score. Score what is on the page, not what a good GM could make of it.

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| **Originality** | Stock tropes in stock order; names and setting swappable with any other adventure | Familiar frame with one or two specific, campaign-rooted twists | Premise, NPCs and conflicts could only belong to this campaign; tropes, when used, are turned |
| **Character stakes** | NPCs exist to deliver information; PCs have no personal reason to care | Main NPCs want something; one PC hook is personal | Every major NPC has a want, a fear and a cost; each PC has a stake tied to their player's stated goals |
| **Setup and payoff** | Revelations arrive unprepared or contradict earlier material | Most payoffs are set up; some setups lead nowhere | Every revelation has visible causes earlier; foreshadowing is traceable and none is orphaned |
| **Player agency** | One route; choices change flavour only; a hidden mandatory plot | Two or three routes converge on a fixed scene | Several approaches lead to different, consistent consequences; ignoring a hook has a defined world reaction, not a forced return |
| **Clue robustness** | A required conclusion hangs on one clue or one roll | Three-clue rule mostly holds; some chokepoints | Every conclusion has ≥ 3 clues on reachable nodes, proactive leads, and a fallback for missed clues |
| **PF2e mechanical integration** | Encounters, DCs or treasure missing or wrong for the level | Budgets correct; tactics and terrain generic | Budgets verified, tactics and terrain serve the scene's purpose, non-combat resolutions and rewards fit PF2e |
| **Session usability** | GM must rewrite before playing; information buried in prose | Usable with some searching and filling gaps | Scannable at the table: an NPC, a scene or a DC is found in seconds; contingencies stated |
| **Immersion** | Read-alouds flat or overlong; no sensory anchor | Serviceable descriptions | Short, vivid, player-safe read-alouds and NPC voices a GM wants to perform |
| **Foundry readiness** | Phantom maps, tokens or UUIDs; nothing realised | Scenes realise with gaps listed | Every referenced asset exists in the GM's install; scenes, actors, journals and playlists realise; gaps listed honestly |

Foundry readiness and mechanical integration are mostly checked by tools first (below); the reviewer scores what the tools cannot see (does the scene serve play).

## Evaluator instructions

1. Read the GM brief, then the artifact, once through, before scoring.
2. Score each dimension alone, against the anchors. Use 2 and 4 for in-between. Do not average dimensions into an overall score.
3. Mark **uncertain** rather than guessing; an uncertain score is reported but excluded from medians.
4. Cite the passage (file and heading or line) for every score of 1, 2 or 5.
5. Do not look at the other reviewer's scores, the producing condition, or any LLM critique before submitting.
6. List up to three things the GM would have to write or fix before running it.

## Blind comparison

- **Conditions**: (A) the studio's iterative task skill at tier `deep` (pitches, critique, revision); (B) one-pass generation from the same brief and tier; (C) the iterative skill at tier `standard`. The runner configuration of each run is recorded in a sealed key, not shown to reviewers. Tiers, not models (ARC-25): which model each tier ran is the GM's runner mapping, recorded in the key.
- **Blinding**: every artifact rendered in the same template, random ids, run metadata stripped. Reviewers see the brief and the artifacts only.
- **Reviewers**: two humans, scoring independently. A gap of ≥ 2 on a dimension is recorded with both justifications and discussed after both submit; the record keeps both scores, never a negotiated one.
- **Briefs**: five fixed prompts on the public sample campaign, one each: political intrigue, dungeon, emotional character arc, mystery, open sandbox. A human-edited exemplar per prompt anchors the scale. Private or licensed campaigns stay in `secondchair-bench-private` (BEN-06).

## Table-use log (real play)

After each played session prepared by the studio, the GM fills a short log; players' input only with their consent.

| Item | How |
|---|---|
| Missing information | Count and list what the GM had to invent that prep should have held |
| Lookup time | Behaviour-trace frictions where users consent: hunting and rules lookup (TRC-03); otherwise the GM's estimate, marked as such |
| Forced improvisation | Moments the prep had no answer for |
| Abandoned prep | Scenes and clues prepared and not used (deterministic from the prep index and the wrap's played facts) |
| Surprising choices | Player choices the outline did not anticipate, and whether the studio's proposal for them helped |
| Engagement | GM 1–5, and players 1–5 if they agree to answer |

## Automatable vs human

| Automatable (no model, no human) | Human only |
|---|---|
| `check_mystery` / `check_draft_mystery` warnings | Originality, character stakes, immersion |
| `check_prep`: phantom UUIDs, XP and treasure deviations, dangling clue ids and scene keys | Setup and payoff, player agency (are routes *meaningfully* different?) |
| Leaks and canaries in player text (guard) | Usability beyond lookup time |
| Spotlight distribution per PC | Engagement |
| Lookup frictions from consenting traces | Whether an LLM critique was right |
| Cost: tokens, attempts, retries, failed generations (ARC-27 log) | |
| GM editing effort: size of the diff between the agent's draft and the version the GM adopted (`git diff --stat` on the note) | |

## Cost and quality

Report per condition: median rubric score per dimension, total cost including failed and retried jobs, GM editing effort (diff size, and minutes when the GM records them), and cost per **adopted** artifact (all spend divided by artifacts the GM adopted). A cheap condition whose output the GM rewrites is not cheap.

## Decisions needed

1. Accept that editorial scores are reported only and never gate v4 (resolution of the MET-02 / MET-04 conflict above)?
2. Who is the second reviewer, and is one GM plus one outside reader acceptable?
3. Are the five brief genres right, and may the exemplars be written with agent help and then edited by the GM?
4. Is the diff-size proxy for editing effort acceptable, or should the GM log minutes?
5. Should the optional LLM critique be shipped at all, or left out until the human track has run once?

## Proposed leaves

| Title | Scope | Risk | Depends on |
|---|---|---|---|
| Rubric and evaluator sheet | This rubric as a fill-in Markdown/YAML template; uncertainty flag; disagreement record. | R0 | decision 1 |
| Five briefs and exemplars | Fixed prompts on the sample campaign; GM-edited exemplars. | R0 | decision 3 |
| Blind rendering and sealed key | Render artifacts to one template, strip metadata, write the key separately. | R1 | rubric |
| Deterministic editorial metrics | Aggregate checker warnings, `check_prep`, guard, spotlight, cost and diff size into the bench report as tracked metrics. | R1 | creative-studio checks |
| Table-use log template | The log above, with the abandoned-prep count computed. | R0 | — |
| First blind round | Run A/B/C on the five briefs; two reviewers; publish scores and disagreements. | R0 | all above |
