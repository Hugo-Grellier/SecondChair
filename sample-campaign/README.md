# The Bell Below the Weir — S0 sample campaign

Original English campaign material, synthetic session notes and a frozen reference
answer set for [issue #33](https://github.com/Hugo-Grellier/SecondChair/issues/33).
Copyright 2026 Hugo Grellier and SecondChair contributors. All files in this folder,
including the gold set, are licensed under **CC BY 4.0**; see [LICENSE](LICENSE) and
[the licence page](https://creativecommons.org/licenses/by/4.0/). Attribute the title,
SecondChair contributors and this repository, link the licence, and indicate changes.

This folder is shipped material, not a campaign workspace. It contains no canon
store, action log, cache or `workspace.yaml`. Rebuild into a directory outside the
repository. No game-system data, rule text, stat blocks or external assets are needed.

## Input boundary

The rebuilding agent receives only [campaign.yaml](campaign.yaml),
[bible.md](bible.md), and (for wrap) the two files in [sessions/](sessions/).
`campaign.yaml` contains the declarative `calendar:` mapping from the workspace
contract. Load it with `secondchair.core.calendar.from_config(config["calendar"])`;
it is not the bare calendar file accepted by `init --calendar`.

The evaluator alone reads [gold.yaml](gold.yaml), [REVIEW.md](REVIEW.md), this file,
and the freeze manifest. Never feed the expected answers back to the agent being
measured. The sample is English; the author-defined calendar has ten months, six-day
weeks, a one-day Bellnight festival and a five-year leap interval. The festival stays
one day even in leap years; Stillwater receives the leap day.

## Reference protocol

1. Reset to the bible's starting date for each independent probe. Import all bible
   material as author-stipulated starting state; retain secret-zone boundaries.
2. Match entity identities and atomic facts to the labels in the gold set. `B01`–`B19`
   are paragraph labels in `bible.md`, not IDs an importer must reproduce. Structured
   expected values are evaluator vocabulary; collection order is immaterial. Resolve
   generated IDs through the entity match before comparison. No LLM judge.
3. Ask the continuity probes in the GM view. Run the audience-specific leak checks
   separately in party/NPC views. A marker reaching any listed audience is a leak.
   Check the structured fact answers too, so paraphrases cannot evade the probes.
4. For capture, feed notes in order. Match the eight authored candidate units by
   their expected content and verbatim quote; several atomic facts from one quote
   form one scoring unit. Recall is matched units / 8; precision is matched units /
   all proposed units (0 when none). A unit matches only if every expected field
   and its quote match. Table chatter and recap are negative examples. A repeated
   canon fact is not another new unit. Admit candidates with the scripted GM before
   advancing the date; knowledge starts at the cited event, not retroactively.
5. Run world-turn cases independently under their stated assumptions. The pristine
   cases use only the bible; the played case admits both notes before advancing
   from the original cursor, so the bypass is open at the first tick. Fact validity
   is start-inclusive, end-exclusive: B17 ends when the opening fact starts.
   A deadline proposal stays pending when unanswered. Rule-effect acceptance never
   authorizes narrative direction or party disclosure. Re-running a completed
   interval must create no additional effects or knowledge.

The reference set is hand-authored directly from the material, independently of any
rebuild/capture run. Its GM role was **agent-emulated at the user's request**; no
human authorship or personal sign-off is asserted. The review records the resulting
BEN-12/MET-02 limitation. It is frozen for implementation and replay; meeting the
literal human gate requires a real GM review and a separately versioned decision.
There is no harness or new metric floor in this issue; this folder defines its inputs
and expected results for the later harness.

## Validation and freeze

From the repository root:

```sh
uv run python scripts/guard_sample_campaign.py
uv run pytest tests/test_sample_campaign.py tests/test_guard_sample_campaign.py
(cd sample-campaign && sha256sum --check frozen.sha256)
```

The deny-list is curated in `scripts/sample-setting-deny-list.txt`, outside the sample.
It checks every sample file, case-insensitively at whole-term boundaries. It is a
regression guard for known terms, not a claim to recognize every official name.
Add newly identified terms there; the planted-term test must continue to fail the scan.

`frozen.sha256` binds every file here except itself, including this protocol and the
gold set. Tests reject missing, added or changed files. Do not refresh it as part of
normal bench runs or to make a regression pass. An intentional amendment requires
an explained review entry, a gold version increment and a new freeze manifest; keep
the prior version in git. No tool regenerates expected answers from observed output.
