# Write paths: a read-only map

Design note for [#184](https://github.com/Hugo-Grellier/SecondChair/issues/184) (maintainable boundaries for canon, world turns, delegation and indexing). It maps every path that writes campaign or machine state, and the invariant each one enforces. **No refactor is proposed here.** Recommendations come last and are deliberately small. Read against `main` at `e96207e`, 2026-10-20. All paths are under `src/`.

## The spine: one delegated action

Here is the traceable path #184's first acceptance criterion asks for:

1. An agent's MCP call reaches the tool registered by `core/server.py:55`, which wraps it with `delegation.wrap` (`core/delegation.py:290`). The wrapper reserves `agent`, `job` and `blocking`, and binds the MCP session to its job through `session_job` (`:337`, #112).
2. `delegation.act` (`:407`) takes `locked(ws)` (`:1385`, one workspace-wide `fcntl` lock, reentrant per thread). It reads the moment, then the job's moment and runner configuration (ARC-23, DEL-24). It computes the strictest effective level over the tool's and the job's responsibility (DEL-23). `manual` is refused, and a living-world disclosure is refused (LW-08).
3. The block's `fn` describes the change (`Change` or `VttAction`) and never writes. A `Contradiction` is logged as `refused` (MET-01).
4. A file change goes `_target` (`:1284`, inside the workspace, never into Core-owned paths), then `_apply(entry, "after")` (`:1306`, compare-and-swap: refused if the file is not in the `before` state), then `_append` (`:1342`, next id, atomic temp+rename via `_write`, `:1405`). A VTT action is first logged `unknown`, then `_take` (`:842`) performs it **outside the lock** and records the outcome under it. A late answer is settled in a thread (`_settle`, `:895`).
5. `_disclose` (`:964`) marks the facts the party now knows, and `calls.open_call` holds a `propose`-level action for the GM.
6. The derived read model: the next `index.connect` (`core/index.py:133`) sees a changed fingerprint and rebuilds (`:150`). It first runs `log_hand_edits` under the lock, so a file that no logged write explains becomes a `hand_edit` entry (CAN-11).

## Map

| # | Path | Entry point | Writes | Invariants enforced |
|---|---|---|---|---|
| 1 | Delegated action | `delegation.act` `core/delegation.py:407` | target file or VTT; `action-log/` | level ≤ table/override/job; no living-world disclosure; Core paths unreachable (`_target`); CAS on `before`; log after apply |
| 2 | Approve | `delegation.approve` `:547`; Surfaces at `core/server.py:133` (CLI/HTTP), `secondchair_foundry/desk.py:83` (Desk) | target or VTT; log entry; GM-interaction entry; call answered | pending only; current moment only (`_check_not_frozen`, `:1233`); an irreversible one needs an authenticated Surface; a relayed approval needs the GM's quote (DEL-28); cites rechecked against current canon |
| 3 | Reject | `delegation.reject` `:589` | log entry, interaction, call | reason from the closed list (DEL-26) |
| 4 | Undo | `delegation.undo` `:601` | target back to `before`; interaction | applied, reversible, current moment; CAS on `after` |
| 5 | Confirm into canon | `delegation.confirm` `:626` via `canon.confirm` `core/canon.py:49` | canon file rewritten; `gm_interaction` with before/after | authenticated Surface only (DEL-29). **No CAS**: it transforms whatever the file holds under the lock, so an unlogged hand edit is folded into the confirmed version (kept only in the entry's `before`) |
| 6 | Hand edit | `delegation.log_hand_edits` `:1120`, called from `index.rebuild` | `hand_edit` entries | every canon file differing from the last Core write is logged at `agent_proposal` (CAN-11) |
| 7 | Promote hand edit | `delegation.promote` `:1158` | entry rank; interaction | authenticated; refused if the file changed since |
| 8 | Overrides / holds / moment | `add_override` `:701`, `remove_override` `:744`, `merge_overrides` `:772`, `set_hold` `:217`, `change_moment` `:126` | `delegation.yaml` (table and overrides), `moment.yaml`; interactions | GM gestures, logged; an override withdraws covered queued jobs and calls (`_withdraw`, `:813`) |
| 9 | World-turn | `world.world_turn` `core/world.py:324` → `_apply` `:505` → `delegation.act` per change, `_cascade` `:541` | `occurrences/`, `living-world.yaml` cursor, canon via act; queues jobs | each effect goes through path 1 (ADR 0009); occurrence key used once (LW-13). **Not atomic across files**: one occurrence's N changes are N separate acts, followed by the occurrence save (#169) |
| 10 | World-turn GM gestures | `settle_unless` `:563`, `decide` `:601`, `undo` `:659`, `set_active` `:699` | occurrences; canon via act or `delegation.undo` | the cascade is undone in reverse entry order; frozen moments refused |
| 11 | Capture | `capture.capture` `core/capture.py:114` | `capture/` candidate YAML | quote checks; never calls on the GM live (ADR 0008) |
| 12 | Consolidate | `capture.consolidate` `:213` → `_route` `:249` → `delegation.act` (`:303`) | canon via act; candidate status | a new name needs two attestations (CAP-12); a contradiction is held as a call (CAP-10); everything goes through path 1 |
| 13 | Wrap / time | `capture.wrap` `:396`, `set_current_date` `:342`, `_write_time` `:605` | `time.yaml`; queues the world-turn | the date moves only by wrap or GM gesture (ADR 0009) |
| 14 | Jobs | `jobs.queue` `core/jobs.py:41`, `start` `:154`, `end` `:180`; `capture.attach_transcript` `core/capture.py:93` | `jobs/` | known tier and responsibility; raw library paths refused (`library.guard_job_inputs`); purchased paths replaced by a metadata index (`_metadata_index` `:116`, writes `.secondchair/purchased/`) |
| 15 | Calls | `calls.open_call` `core/calls.py:48`, `raise_exception` `:94`, `take_break` `:134`, `_default` `:177`, `_miss` `:191` | `calls/`; a pending log entry set to `rejected`; `safe_default` entries | the safe default never applies (DEL-32); a missed live job takes no further action (ARC-28) |
| 16 | Rules and house rules | `rules.check` `core/rules.py:50`, `mark_intended` `:108`, `remove_house_rule` `:148`, `propose_fix` `:181` (→ act) | calls; `house-rules.yaml` **directly**; interaction | GM gesture logged; a fix goes through path 1 |
| 17 | Observations | `observations.record` `core/observations.py:61` | `observations/<session>.jsonl` (append + fsync) | once per id; torn lines are skipped. Uses its own module lock, **not** `locked(ws)` |
| 18 | Bridge: binding | `Bridge.bind` `secondchair_foundry/bridge.py:142` | `foundry.yaml` | one world per campaign (PKG-09). Plain `write_text`, not atomic |
| 19 | Bridge: reconciliation reports | `Bridge._realise` `bridge.py:437` (write at `:486`) | `.secondchair/scenes|documents/*.json` (derived) | level from `scene_level` (`:516`), which fails open for unknown origin (#163) |
| 20 | Library | `library.register` `core/library.py:81`, `permit` `:117`, `build_index` `:420`, `_store` `:239` (also from `search` `:468`) | `library.yaml`; machine `library/<hash>.json`; the machine-wide SQLite | permissions are GM gestures with no MCP tool; changed-index replacement needs an interactive terminal. `search` **writes** the machine index (it embeds campaign Markdown on first sight) |
| 21 | Transcripts / Sources | `transcribe._reference` `secondchair/transcribe.py:216` | `sources/<id>.yaml`; machine `sources.yaml` | the reference lives in the workspace, the path in machine config (PKG-12) |
| 22 | Acting cue | `knowledge.show_cue` `core/knowledge.py:93` | `.secondchair/cue.json` | derived; temp+rename |
| 23 | Traces / friction reports | `traces.record` `core/traces.py:59`, `erase` `:97`, `report` `:135` | `$XDG_DATA_HOME/…/traces/`; `frictions/<seq>.md` | consent (ADR 0012); erasure rewrites reports |
| 24 | Workspace lifecycle | `workspace.init` `core/workspace.py:34`, `upgrade` `:86`; `campaign_skill.install` `core/campaign_skill.py:54` | `workspace.yaml`, `.gitignore`, skills, manifest | schema refused if newer; managed skills never overwrite local edits. `upgrade` has no lock and no copy (ADR 0018, proposed) |
| 25 | Index projection | `index.rebuild` `core/index.py:150` | `.secondchair/index.sqlite` (temp+rename) | readers never see a half-built index; a hand edit is logged first |

## Observations

- **One gateway holds.** Every canon write goes through path 1 (directly, or via 9, 12, 16). The exceptions are GM-authenticated `confirm`/`promote` and human hand edits, which path 6 catches.
- **Order inside path 1 is apply-then-log.** A crash between `_apply` and `_append` leaves a changed file with no entry. The next rebuild logs it as a hand edit at `agent_proposal`: safe (no false rank), but misattributed. Log-then-apply with a `status: applying` entry would attribute it. Worth a test before changing anything.
- **Lock coverage is uneven.** Paths 17 (observations) and 18 (binding) write outside `locked(ws)`. Path 24 (`upgrade`) writes while `serve` might run. `serve` refuses an old schema, but nothing stops an `upgrade` against a running `serve` of the new version.
- **Multi-file effects are not transactional** (path 9, #169). This is the one place where the "one act = one file" spine is stretched by a domain operation that needs N files.
- **Core-owned paths are a deny-list** (`_target` `:1284`), and it is already incomplete: `capture/`, `time.yaml`, `house-rules.yaml`, `library.yaml`, `foundry.yaml` and `sources/` are Core-written but not listed. No current tool can reach them, because each tool fixes its own prefix (`write_prep` confines to `prep/`). The guard is latent, not exercised.
- **`delegation.py` is 1,420 lines** because it holds the gateway (`act`, `_apply`, `_target`, the log) *and* GM interactions, overrides, disclosure and moments. Path 1's invariants concentrate in roughly 250 lines (`act`, `_take`, `_apply`, `_target`, `_append`, `locked`).

## Boundary recommendations (no refactor now)

1. **Keep single-process Markdown + SQLite.** No query pattern seen here needs a graph store or a service. Every hard invariant is per-workspace and lock-serialised. Record that in the ADR #184 asks for.
2. **Name the seams; do not move code yet.** In order of payoff:
   - *Admission*: `act` plus `_target`, `_apply`, `_append`, the gateway every write passes.
   - *GM interactions*: approve, reject, undo, confirm, promote, overrides.
   - *Disclosure*: `_disclose`, `_party_learns`, `hold_whispers`.
   - Moving GM interactions and disclosure out of `delegation.py` would leave admission small enough to review alone. Do it only when a change to one forces edits in the other.
3. **Contract tests at the seams first** (R0):
   - Every Core-written top-level path appears in `_target`'s deny-list (a test listing the `*_DIR`/`*_FILE` constants of `core/`). It fails today on the six paths above.
   - Every write in `core/` is reached under `locked(ws)`, or is listed as exempt with a reason (observations, traces, binding).
   - Crash injection between `_apply` and `_append`: a rebuild yields one `hand_edit`, and never a rank above `agent_proposal`.
   - A world-turn occurrence interrupted after k of N changes is detected by `check` (#169).
4. **Allow-list rather than deny-list** for `_target` once #163 is settled. Delegated tools may write only `canon/`, `prep/`, `scenes/`, `documents/` and `notes/`.
5. **Put `observations.record` and `Bridge.bind` under `locked(ws)`**, or document why not (observations are append-only and hot during play; contention matters there).
