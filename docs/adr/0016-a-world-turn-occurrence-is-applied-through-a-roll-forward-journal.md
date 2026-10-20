# A world-turn occurrence is applied through a roll-forward journal

Status: proposed — awaiting the GM ([#169](https://github.com/Hugo-Grellier/SecondChair/issues/169))

One world-turn occurrence writes several canon files: the offscreen event, the closed state fact, the new state fact, the knowledge records, and then the steps it cascades into. `world._apply` takes one `delegation.act` per change, and each act writes its file and appends its action log entry. A crash or an exception between two acts leaves the occurrence half-applied. The first changes are written and logged, the rest are missing, and the occurrence record still says `queued`. A rerun then plans the same key again on top of a moved clock, and undo walks only the entries the record lists, which here are none. Canon stays human-editable Markdown and YAML, with SQLite derived (ADR 0007), so the fix cannot be a database transaction.

We propose that **every multi-change Core operation, starting with one world-turn occurrence and its cascade, is applied through a durable intent journal and rolled forward on recovery**.

1. **Plan, then journal.** Under the workspace lock, compute every change of the occurrence and its cascade, without writing anything. This is already deterministic (ADR 0009). Then write one journal file, `.secondchair/journal/<key-hash>.yaml`, with the occurrence key, each change's target, its content before (or `absent`) and after, and the log entry it gets. The journal is written to a temporary file and renamed, so it either exists whole or not at all.
2. **Apply.** Write each target and append its log entry, in journal order. Each step is idempotent: a target already holding its `after` content, or a log entry already present for that change, is skipped.
3. **Commit.** The occurrence record's `status: applied`, with its entries, is the commit marker. Writing it is the last step, and deleting the journal comes after it.
4. **Recover.** Before any other write, `locked()` looks for leftover journals and rolls each one forward, with step 2 then step 3. Every place that takes the lock therefore recovers first: `serve` at start-up, the CLI, the next world-turn.

## Questions settled

- **Roll forward or back?** Forward. The plan is deterministic and already validated, so finishing it gives the same canon a crash-free run would have. Rolling back would also undo log entries the Director's Desk may already have shown.
- **When recovery cannot roll forward.** If a target holds neither its `before` nor its `after` content, something edited it in the meantime, a hand edit or another tool. Recovery stops and keeps the journal, and the occurrence becomes an exception call on the GM that names the file, its three versions and the occurrence. Nothing more is written for it until the GM resolves the file and runs `secondchair recover`.
- **Undo of a partial occurrence.** There is none to undo. After recovery an occurrence is either applied whole, which undo already handles (LW-12), or blocked behind its call with its journal kept.
- **Locks.** There is still one workspace-wide `flock` (`delegation.locked`). The journal does not replace it: it covers a crash, not concurrency. Hand edits are not locked out. They are detected (`log_hand_edits`) and, during recovery, they lead to the stop above.
- **Scope.** This covers world-turn occurrences first, then any other operation that takes more than one `act`: capture consolidation's fact, then event, then knowledge, and a scene with its documents. A single `act` stays as it is, its file write followed by its log entry. Its one gap is a written file with no log entry, which `log_hand_edits` already reports as a hand edit. A follow-up can fold that case into a one-change journal too.

## Considered Options

- **SQLite as the source of truth with transactions**: rejected. It contradicts ADR 0007, since Markdown is canon and is edited by hand.
- **A copy-on-write workspace snapshot per occurrence**: rejected. It costs a copy of the whole workspace for every tick and breaks hand edits made in the meantime.
- **Roll back on recovery**: rejected, see above. It is kept for one case only: a journal whose plan no longer validates, because the Core's code changed between crash and restart, is rolled back to its `before` contents, with a call on the GM.

## Consequences

- `world._apply` and `_cascade` build the full change list first, then hand it to one `delegation.apply_journal(ws, key, changes)`. `delegation.act` keeps its per-change level checks and logs each change in the journal.
- New workspace directory `.secondchair/journal/`, in the workspace layout contract.
- **Fault-injection test plan.** A test hook raises at step *k* for every *k* across one tick with a threshold cascade: before the journal, after the journal, after each file write, after each log append, after the commit, and before the journal is deleted. For each *k*, recovery must produce a byte-identical workspace (canon, action log, occurrences) to an uninterrupted run, and a second recovery must change nothing. Further cases: a hand edit made between the crash and recovery (an exception call, journal kept), a journal whose plan is stale (rolled back), a subprocess killed with SIGKILL during a real world-turn, and two Core processes racing (the second waits on the lock, then finds nothing to recover).
