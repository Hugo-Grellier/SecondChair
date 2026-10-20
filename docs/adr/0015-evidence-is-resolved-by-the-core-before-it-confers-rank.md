# Evidence is resolved by the Core before it confers a rank

Status: proposed — awaiting the GM ([#168](https://github.com/Hugo-Grellier/SecondChair/issues/168))

A fact's rank comes from its origin (ADR 0007, CAN-06..08), and today `rank_of` only checks the origin's shape. Any caller of `record_fact`, `record_event` or `record_knowledge` can write `{kind: observation, quote, locator}` with made-up strings and get **played**, or `{kind: source, source, page}` and get **cited_source**. Three paths already check their evidence: capture finds the quote in the job's Source or transcript segment (CAP-04), knowledge resolves an `observations/…#id` locator and its visibility (ARC-16), and a disclosure's locator is an action log entry the Core wrote itself (CAN-17). Every other path trusts the caller. Provenance is a trust boundary, so the decision is where rank-conferring evidence gets checked and what happens when it fails.

We propose that **a rank above agent_proposal is admitted only on evidence the Core resolved itself, in one admission step shared by every write path**. The caller names evidence, and the Core looks it up. The caller never states a rank, and never states who it is.

| Origin | Admitted at its rank when the Core… | Otherwise |
|---|---|---|
| `observation`, locator `observations/<session>.jsonl#<id>` | finds the observation, and the quote is in it; for knowledge, its visibility allows it | refused |
| `observation`, locator `<file>:<line>` | finds the file among the Sources of the job the action runs under, and the quote at that line or transcript segment | refused |
| `observation`, locator `action-log/<n>.yaml` | is composing the record itself, for a disclosure (see *Who is calling*) | refused to every MCP caller |
| `source` | finds the Source registered in the reference library with its permission, and the page in its index; when the origin carries an `excerpt`, finds it on that page | refused, whether the Source is unknown or only registered and not yet indexed |
| `gm` | is in an authenticated Surface gesture (`confirm`, DEL-29) | agent_proposal, as today |
| `rule` | is the world-turn composing the record itself | refused, as today |
| `job` | needs nothing | agent_proposal |

## Who is calling

Admission needs to know whether the record comes from an MCP caller or from the Core's own composition, and that must not be a caller-supplied value, or the `action-log/` and `rule` rows are spoofable the same way origins are today. It is established by the code path, not by data:

- Every MCP delegated action enters through `delegation.wrap`, which calls `act`. `act` already resolves the job (`session_job`: bound to the MCP session, and only a `started` job). Around `describe()` it sets an admission context, a frozen value in a module-private `ContextVar`: the job and its Sources, `authenticated=False`, `core=False`. The block's tool function (`record_fact` and the rest) reads it when it calls `admit`. Neither the `ContextVar` nor `core` is a tool parameter, and `wrap` already refuses blocks that declare the Core's reserved parameters. A job id passed by the agent only selects which started job's Sources are searched; the quote must still be found in them.
- The Core's own writers never go through a tool function. A disclosure's party knowledge is composed in `delegation._party_learns`, and the world-turn's rule effects, facts, events and knowledge in `world._evolution` and `world._effect` (whose rule origin `world._rule_rank` builds); each calls `admit` with `core=True` directly. Capture needs no `core=True`: it acts through the tool functions under its wrap job, so its `<file>:<line>` locators resolve against that job's Sources like any agent's.
- Python blocks loaded through entry points run in the Core's process (ARC-02, ARC-17) and are trusted code, as they already are for everything else they can do there. The boundary this ADR guards is the MCP call and the files an agent hands in, not in-process code.

## Proposed answers

These are the GM's calls on #168; the ADR proposes, it does not settle them.

- **(a) Refuse or demote a forged origin?** Refuse with a `CanonError` that names the missing evidence. A silent demotion hides the bug in the agent or playbook, and the agent can still record the fact honestly as a `job` origin. The one case that looked like an exception, a Source registered but not yet indexed (a book only on the shelf), is refused too: the agent records a `job` origin carrying the `source` and `page` as supporting evidence (b), which ranks agent_proposal and stays there (CAN-08). Demoting it "until the GM confirms it" would need a new gesture, since `confirm` only raises `gm` origins and job and agent proposals cannot be confirmed (workspace-layout contract, CAN-08); one refuse rule with no exception is simpler to state and test. The GM who wants cited_source indexes the book (`secondchair sources index`) and the fact is recorded again from it.
- **(b) Evidence apart from authority.** An origin keeps its pointer (`quote`, `locator`, `page`, `excerpt`) as evidence. Only the kind, checked as above, carries authority. A `job` origin may carry the same pointers as supporting evidence without being raised (#167).
- **(c) Evidence that changes after admission.** It is checked once, at admission. The quote is stored verbatim, so the record stands even if its Source is later edited or lost. Rebuilding the index does not check again. A `secondchair doctor` check can re-resolve evidence and report what no longer resolves, but it never changes a rank.
- **(d) Imports and the GM's own edits.** A bible or import job writes `job` origins, or `source` ones that resolve against the library. A hand edit to canon Markdown follows CAN-11 unchanged: the Core logs it as a `hand_edit` entry and the index ranks its content agent_proposal, whatever origin its front matter declares, so a hand-typed `{kind: observation, quote: "anything"}` gains nothing. The GM raises it with `secondchair promote <entry>` on an authenticated Surface, which makes it a gm_decision, not played or cited_source: admission is not run on hand edits, because the promotion is the GM's word, not evidence. Whether anything else with disk access must be told apart from the GM is the same question as [#163](https://github.com/Hugo-Grellier/SecondChair/issues/163), and it is settled there.

## Considered Options

- **Check in each tool (status quo, extended)**: rejected. The checks drift apart, which is how direct `record_fact` was left open.
- **Signed observations (an HMAC on each observation line)**: not needed. The Core resolves the locator against its own append-only files. A signature only helps once the files leave the Core's machine.
- **Demote instead of refusing**: rejected, see (a).
- **A `core` or `trusted` flag on the tool call**: rejected. Anything an MCP caller can pass, it can forge.

## Consequences

- One `admit(ws, origin, context)` in the Core, called by `canon`, `knowledge`, `capture` and `world` before `rank_of`, and by `delegation._party_learns`. `rank_of` stays a pure mapping. The context is the one described in *Who is calling*.
- An agent outside a job cannot write an `observation` with a file locator, because it has no Sources. It can quote VTT observations by id.
- The `source` origin gains an optional `excerpt`. The library's index already holds page text.
- Capture's `_answered` finishes a held candidate's event and knowledge with `act(…, None)`, outside the job, so its `<file>:<line>` origin would be refused. It admits under the wrap job the candidate records (`c["job"]`) instead; that job may have ended by then, so this context takes the job's Sources from its record rather than requiring `started`.
- Callers that write rank-conferring origins directly, without evidence the Core can find, break and are migrated:
  - `tests/test_world.py` `SEEN` (`s1.md:4`, written by `prep-agent` outside a job) and `tests/test_canon.py` `SEEN` (`s1.md:3`, through MCP outside a job): the fixtures that need a played fact either record a real observation and quote it by id (as `tests/test_observations.py` `seen()` already does), or run the write under a job whose Source holds the line. Tests about rank ordering rather than evidence write the fact through a test helper that composes it with `core=True`, named as such.
  - `tests/test_canon.py` `cited` (`Core Rulebook` p. 12), `tests/test_mystery.py` `BIBLE` and `tests/test_s0_probes.py` (`sample-campaign/bible.md`, and the `S1-02` observation locator): the bible is registered and indexed in the test's library first, or the origin becomes `job`.
  - `src/secondchair/bench/fake.py` and the `rebuild-entities-from-a-bible` playbook write `{kind: source, source: <bible>}` for the job's bible input: the rebuild job registers and indexes its bible before it starts, or writes `job` origins carrying the page. The playbook's instruction changes with it.
  - Records already on disk are never re-admitted (c): their ranks stand. `secondchair doctor` reports the ones whose evidence no longer resolves, for the GM to correct or promote; it changes nothing itself.
- Tests: a forged file locator, a nonexistent observation id, a quote not in its observation, a spoofed `action-log/` locator through MCP, a `rule` origin through MCP, an unknown Source, a registered but unindexed Source, a Source edited after admission (the record stands, doctor reports it), a hand edit declaring `observation` ranking agent_proposal until promoted to gm_decision, legitimate capture (including `_answered`), disclosure, world-turn and import paths keeping their ranks, and authenticated confirmation.
