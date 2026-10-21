# The Core's seams are named modules in one process over Markdown and SQLite; an adapter only where an implementation varies

Status: accepted 2026-10-21, by owner Hugo in conversation 2026-10-21 ([#184](https://github.com/Hugo-Grellier/SecondChair/issues/184), epic [#173](https://github.com/Hugo-Grellier/SecondChair/issues/173)). Map: [write-paths.md](../research/write-paths.md).

The read-only map of every write path (write-paths.md, read at `e96207e`) found one gateway that holds: every canon write is a `delegation.act`, a GM gesture on an authenticated Surface, or a hand edit that `log_hand_edits` catches. It also found that `delegation.py` carries the gateway together with GM interactions, overrides, holds, moments and disclosure, and that the invariants of the gateway itself sit in about 250 of its lines. Since the map, several of its findings have been fixed: the Core-path deny-list is complete and tested (#210), observations, the Foundry binding and `upgrade` take the workspace lock (#211), and a desired scene of unknown origin is bounded by the ceiling (#163). Evidence admission is moving into `core/admission.py` (ADR 0015, #232), and the world-turn journal (ADR 0016, #169) adds about 300 lines of planning, journal and recovery code, today written into `delegation.py`. `delegation.py` makes 15 function-local imports of modules that build on it (`calls`, `jobs`, `world`, `capture`, `index`, `knowledge`), and `index.rebuild` calls back into `delegation.log_hand_edits`. The cost of that coupling is review scope and merge conflicts, not a defect, so the decision is where the seams are and when code moves, not a rewrite.

We propose that **the Core keeps one process over Markdown and YAML canon with a derived SQLite index, names seven seams inside it, and moves code to a seam only when a change to one seam forces an edit inside another**. A seam is a module of plain functions with a stated invariant. It is not an interface.

## Seams

| Seam | Owns | Code (main, or in flight) | Invariant it keeps |
|---|---|---|---|
| Evidence admission | Whether an origin's evidence confers its rank | `admission.admit`, `under`, `CORE` (#232); `index.rank_of` stays a pure shape check | A rank above agent_proposal only on evidence the Core resolved itself; who calls is set by the code path, never by data (ADR 0015) |
| Gateway | Taking one delegated action | `delegation.act`, `_target`, `_apply`, `_append`, `_write`, `locked`, `wrap`, `session_job` | Level at most the table, override and job allow; Core paths unreachable; compare-and-swap on `before`; every applied change logged; one writer per workspace |
| GM interaction | The GM's gestures on the log | `approve`, `reject`, `undo`, `confirm`, `promote`, overrides, holds, moments | Each gesture is its own log entry (DEL-27); irreversible ones need an authenticated Surface (DEL-28, DEL-29); a frozen moment is refused |
| Disclosure | What the party learns | `_disclose`, `_party_learns`, `hold_whispers`, `_known_to_party` | The living world never discloses (LW-08); whispers wait for the wrap (CAP-08); the Core composes the knowledge record (ADR 0015 `CORE`) |
| World-turn planning and journal application | One occurrence and its cascade | `world.world_turn`, `_cascade`, `_effect` as a planner; `apply_journal`, `recover`, `inputs_digest` (#169) | Deterministic plan, level checked once, roll forward or back whole, recovery before `log_hand_edits` (ADR 0009, ADR 0016) |
| Index projection | The derived read model | `index.connect`, `rebuild`, `_fingerprint`, the `search_*` reads | Readers never see a half-built index; hand edits are logged before projecting (CAN-11); it never writes canon |
| Job lifecycle | Queued work for runners | `jobs.queue`, `start`, `end`, `finish`, `raise_exception`; `calls` for its calls on the GM | Known tier and responsibility; raw library paths refused; a writing job finishes only with a live action logged under it (#171, #221); a missed live job acts no further (ARC-28) |

The action log is shared by all seven. Its reads (`read_log`, `core_states`, `last_writes`) and its append are the lowest layer above the workspace files.

## Dependency direction

From the bottom up, each layer may import only the layers below it:

1. **Workspace**: `workspace`, the files, `delegation.locked` and `_write`.
2. **Action log**: append and read, `log_hand_edits`.
3. **Index projection**: it reads canon and the log, and calls `log_hand_edits`.
4. **Evidence admission**: it reads the index, observations, the library and the job's Sources.
5. **Gateway**, then **disclosure** and **journal application**, which write through the gateway's primitives.
6. **Domain tools and planners**: `canon`, `capture`, `knowledge`, `rules`, `notes`, `prep`, the world-turn planner, **job lifecycle**, `calls`, and **GM interaction**.
7. **Entry points**: `server` (MCP), the CLI, and the bridge's Surface routes.

A function-local import that points up this list is recorded debt: new code adds none, and each staged refactor below removes some. The Core/System/VTT boundary is unchanged (ARC-01, ADR 0003, ADR 0004). The Core imports neither `secondchair_pf2e` nor `secondchair_foundry`. The System extension and the connector depend on Core contracts and register through entry points. The bridge reaches canon only through layer 5 or 6, like any Surface. No seam above becomes a package or a process boundary.

## Why one process over Markdown and SQLite

- **Query patterns.** The reads are by entity, by words, by relation type, valid at a campaign date, with retcon status, and who knows what. A relation is followed one or two hops at most. SQLite answers each of these from one rebuilt file, and nothing seen needs graph traversal.
- **Transactions.** Every hard invariant is per workspace and serialised by one lock. Only the world-turn needs several files to change as one, and ADR 0016 solves it with a journal, because no database transaction can cover hand-editable Markdown (ADR 0007).
- **Hand edits.** The GM edits canon in an editor and keeps it in git, and the Core detects the edit (CAN-11). A graph or SQLite store as canon makes the canon opaque, or needs a two-way sync, which is a second source of truth.
- **Migration cost.** Changing storage touches the workspace schema and `upgrade` (ADR 0018), every tool, the sample campaign, the bench fixtures and the synthetic generator. Services add inter-process authentication and deployment for one GM on one machine (ADR 0010).
- **The measured cost is the projection.** #230 found that an index rebuild parsing every document dominates write cost at 100 sessions (#172). That is fixed inside index projection (a stat cache), not by a new store.

Revisit this when a bench at the L size shows a read pattern the projection cannot serve, or when a second concurrent writer process is required. Either one needs its own ADR with the bench numbers.

## When an adapter is warranted

An interface with substitutable implementations is warranted only when one of these holds:

- two implementations exist or are scheduled, such as VTT connectors, System extensions and runners;
- the boundary crosses a process or trust boundary, such as MCP, the bridge or a Surface;
- a test cannot otherwise reach the behaviour, such as the VTT behind `vtt.perform`.

It is needless abstraction otherwise. Examples are a repository class over the workspace files, an index interface with one SQLite implementation, an in-process event bus between seams, and a dependency-injection container. Tests use a temporary workspace instead of a fake.

## Staged refactors

Each stage is one PR, keeps the whole suite passing without editing a test's assertions, and leaves the S0 bench workspace byte-identical. None starts while an urgent security fix or first dogfooding needs the same module (#184 acceptance 5).

| # | Stage | Trigger | Payoff | Invariant kept |
|---|---|---|---|---|
| 0 | Contract tests at the seams: the traced write path (`tests/test_write_path.py`), crash injection between `_apply` and `_append`, the ADR 0016 fault-injection plan | Now (R0) | Each later stage has a test that fails when it breaks the spine | Behaviour unchanged |
| 1 | Allow-list in `_target`: delegated tools write only the prefixes registered tools write today, `canon/`, `prep/`, `scenes/` and `documents/` | #163 is closed, so now | A new Core-written path is safe by default | Core paths unreachable |
| 2 | Journal application into `core/journal.py` when #169 lands | #169 merge | `delegation.py` does not grow by 300 lines; recovery is reviewed alone | Recovery on first lock acquisition, before `log_hand_edits` |
| 3 | Action log into `core/log.py` (`read_log`, `core_states`, `last_writes`, `log_hand_edits`, `_append`) | The next change that touches both `index` and `delegation` | `index` no longer imports the gateway; the cycle goes | Hand edits logged before projection, under the lock |
| 4 | GM interaction into `core/interactions.py` | A change to a gesture that forces an edit in `act` | The gateway fits in one review | Each gesture logged; CAS; authentication rules |
| 5 | Disclosure into `core/disclosure.py` | A change to disclosure that forces an edit in `act` | Disclosure rules reviewed alone | Living world never discloses; whispers held |

Not planned: splitting `index.py`, `world.py` or `capture.py` by size alone.

## Owner answers (2026-10-21)

The owner's calls on #184, accepted by owner Hugo in conversation 2026-10-21.

- **Names.** write-paths.md calls the gateway "admission". After ADR 0015, admission means evidence admission only, and the gateway is the ADR 0003 word.
- **When code moves.** Stages 0 and 1 now; stages 2 to 5 on their trigger, each with its own PR and no ADR, since none changes behaviour.
- **Log-then-apply.** Not adopted. Apply-then-log fails safe (a misattributed hand edit, never a false rank), and ADR 0016's scope note keeps a one-change journal as the upgrade path.

## Considered Options

- **A graph database as canon**: rejected. It loses hand edits and git history (ADR 0007), and no query seen needs it.
- **SQLite as canon with transactions**: rejected, as in ADR 0016.
- **Services** (an index or world-turn process): rejected. It adds authentication and deployment between processes for one local GM, and the lock already serialises writers.
- **Split `delegation.py` now**: rejected. Nothing measured pays for it, and it would conflict with #169 and #232 in flight.
- **Ports and adapters at every seam**: rejected, see *When an adapter is warranted*.
- **No ADR, keep the research note**: rejected. The note recommends; only an ADR binds new code to the dependency direction.

## Consequences

- New code follows the dependency direction, and an upward import needs a reason in review.
- `docs/spec/02-architecture.md` gets a pointer to the seams once this is accepted.
- **Test plan.** `tests/test_write_path.py` traces one `record_fact` from the MCP call to `search_facts` step by step and shows a forged origin refused at the same seam. Once #232 lands, it also refuses an observation whose quote the Core cannot find. Stage 0 adds crash injection between `_apply` and `_append`: one rebuild logs one `hand_edit`, never a rank above agent_proposal. ADR 0016's fault-injection plan covers the journal. Each stage 2 to 5 keeps these tests and the existing seam tests (`tests/test_delegation.py` for Core paths, `tests/test_admission.py` for evidence) green, unedited.
