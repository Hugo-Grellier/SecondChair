# A campaign snapshot is the workspace plus a paired Foundry world; restore is into a fresh directory; a destructive migration needs consent

Status: proposed — awaiting the GM ([#197](https://github.com/Hugo-Grellier/SecondChair/issues/197))

Not binding until the GM accepts it. Until then ADR 0010 and PKG-16 hold as written.

**Amends [ADR 0010](0010-local-core-reached-by-the-gm-browser.md) (its upgrade consequence) and PKG-16 ([09](../spec/09-packaging.md#export-and-schema-evolution)).** ADR 0010 says an older schema blocks `serve` "until `secondchair upgrade` migrates it in place as a reviewable diff". PKG-16 says the same. On acceptance, PKG-16 becomes:

> **PKG-16** `workspace.yaml` carries the schema version. A newer schema is refused. An older one blocks `serve` until `secondchair upgrade` migrates it: after a pre-upgrade snapshot (skipped only when the GM passes `--no-snapshot`), on a sibling copy swapped in by two renames once `check` passes, with `--preview` showing the diff first. A destructive migration step runs only from an authenticated Surface with typed confirmation (ADR 0018).

The reviewable diff survives, as `--preview` and as the git diff after the swap. "In place" no longer holds: the workspace directory is replaced, not edited.

A multi-year campaign must survive a dead disk, a moved workspace and a SecondChair or Foundry upgrade. ADR 0010 already makes the campaign workspace the full export: `workspace.yaml` carries the schema version, the derived index lives in a git-ignored `.secondchair/`, and `secondchair check` rebuilds everything from the directory alone. This ADR states what a backup holds, how a restore proves itself, and when an upgrade may change authoritative data.

**The snapshot boundary.** A snapshot is two artefacts taken at one quiet point and paired by a manifest:

1. **The workspace archive**: every file in the campaign workspace except `.secondchair/`. That covers canon, the action log, jobs, calls, occurrences, capture candidates, prep, desired scenes and documents, notes, sessions, Source reference files (`sources/`, `library.yaml`), house rules, friction reports, the Foundry binding (`foundry.yaml`), the delegation table and `workspace.yaml`. The manifest records each file's path and SHA-256, the schema version, the SecondChair version, and the git commit when the workspace is a repository.
2. **The Foundry world**, backed up by Foundry's own means (the world folder, or The Forge's backup). The Core never dials Foundry (ADR 0010). It only records, in the manifest, the bound world id, the Foundry, system and module versions last reported by the handshake, and the time the GM declared the world backup taken.

Excluded, and why:

- `.secondchair/` is derived (the index, reconciliation reports, the acting cue, purchased-content metadata indexes and the lock). `check` and the next reconciliation rebuild it.
- **Machine configuration** never travels (PKG-13). It holds the Foundry token, runner configuration, Source locations, library paths and permissions, and the purchased-content list. A restore on a new host lists what must be granted again rather than copying it. Permissions are GM gestures and stay so.
- **The machine-wide library index** (`$XDG_DATA_HOME/secondchair/library/`) is derived from Sources. It is expensive to rebuild (around 11 min per 138-page book on a CPU), so `--with-library-cache` may copy it. It is never needed for correctness.
- **Sources** (rulebooks, raw audio, full transcripts) and **behaviour traces** stay outside (PKG-12, ADR 0008, ADR 0012). Traces never enter a snapshot, so erasure stays real.

**A quiet point.** `secondchair backup` takes the delegation lock and refuses while an action is `unknown` (its VTT outcome is pending) or a job is `started`. The GM can wait, or end the job. It writes the archive with mode 0600, because the workspace holds GM secrets. SecondChair does not encrypt it. The GM's backup tool does.

**Restore.** `secondchair restore <archive> <new-dir>` only writes into an empty or new directory, never over a live workspace. It verifies every hash against the manifest, then runs `check`. It reports, without fixing: a Foundry world id or versions that differ from the manifest, machine permissions to grant again, and Source references whose paths are missing on this host. Foundry state then converges by the ordinary reconciliation of desired scenes and documents, which keeps played state.

**Upgrade and migration consent.** `secondchair upgrade` (`workspace.upgrade`) migrates in place one schema version at a time. It rewrites `schema_version` after each step and keeps no copy. This ADR amends that, together with ADR 0010 and PKG-16 (see above):

- Before the first step, upgrade takes a snapshot of the workspace archive. Without one it refuses unless the GM passes `--no-snapshot`.
- Each migration declares itself **additive** (new files or fields; nothing removed or rewritten) or **destructive** (it removes, rewrites or merges authoritative content).
- `--preview` runs the migrations on a temporary copy and prints the diff. No migration touches the workspace before the GM has had the chance to see that diff.
- A destructive step runs only from an authenticated Surface (an interactive terminal), with the GM typing the workspace name. This is the same bar as an irreversible approval (ADR 0003).
- **The copy.** `upgrade` refuses while `serve` runs on the workspace. It takes the workspace lock (`.secondchair/delegation.lock` of the original directory, #211/#213) and holds it until the swap ends. It writes `.secondchair/upgrading` in the original, which `serve` and `check` refuse to run past. It copies the workspace to `<dir>.upgrading`, **including `.git`** (history and the reviewable diff move with it) and excluding `.secondchair/` (rebuilt by `check`). Every migration step and `check` run on the copy. Then `.upgrading/.secondchair/upgrade-complete` is written.
- **The swap is two renames**, since POSIX `rename` cannot replace a non-empty directory: (1) `<dir>` → `<dir>.pre-upgrade`, (2) `<dir>.upgrading` → `<dir>`. Between them nothing exists at `<dir>`. Linux `renameat2(RENAME_EXCHANGE)` and macOS `renamex_np(RENAME_SWAP)` close the window. They are optional, because the recovery below covers the portable path.
- **Recovery.** Every command that opens a workspace first checks for the siblings:
  - The upgrade was interrupted before (1): `<dir>` exists with the marker, plus a `.upgrading` copy. Delete the copy and remove the marker. The original is untouched.
  - The window: `<dir>` is missing, and `.pre-upgrade` and `.upgrading` exist. If the copy carries `upgrade-complete`, finish (2). Otherwise rename `.pre-upgrade` back.
  - Done: `<dir>` is the migrated copy and `.pre-upgrade` remains. It is reported, and kept until the GM deletes it. It is the fast rollback.
  
  No state leaves the authoritative workspace half migrated: each directory is either wholly old or wholly migrated and checked.
- **Lock waiters.** A CLI process waiting on the lock holds the old inode, which after the swap lives in `.pre-upgrade`. `locked()` therefore re-checks, once it acquires the lock, that the lock file is still the one at `<dir>/.secondchair/delegation.lock` (same device and inode). If it is not, it releases and retries on the new directory. `serve` cannot be a waiter, because upgrade refuses while it runs.
- Rollback: rename `<dir>.pre-upgrade` back while it exists, otherwise restore the pre-upgrade snapshot.

**Software upgrades.** One qualified pair is supported at a time (Core tag × Foundry major × PF2e system major), as the handshake's protocol check already enforces. An upgrade of the tool is `uv tool install …@<tag>`, then `secondchair upgrade`.

## Considered Options

- **Back up `.secondchair/` too**: rejected. It is derived, and restoring a stale index could hide a hand edit that the rebuild logs (CAN-11).
- **Include non-secret machine configuration** (runners, Source paths): rejected for now. Paths are host-specific, and permissions must be granted again consciously. Revisit if restores to the same host prove tedious.
- **SecondChair backs up the Foundry world itself**: rejected. The Core never reaches Foundry (ADR 0010), and Foundry and The Forge already do this well. Pairing by manifest is enough.
- **Rely on git alone**: rejected as the only mechanism. Not every GM commits, and uncommitted edits are exactly what is lost. A git commit is recorded when one exists.
- **In-place migration with git as rollback** (today): rejected for destructive steps, which can leave a half-migrated authoritative workspace on interruption.

## Consequences

- New commands: `backup`, `restore`, and `upgrade --preview`. `upgrade` changes behaviour (snapshot, copy-and-swap, destructive consent).
- `MIGRATIONS` entries gain a declared class. A test asserts that every migration declares one, and that a destructive one is refused from a non-interactive Surface.
- The library's per-workspace settings are keyed by the workspace path hash (`library._settings`), so a restore to a new path starts with no registered paths or permissions. That is intended under this ADR, and the restore report says so.
- A restore rehearsal (back up the populated sample campaign and a bench world, delete, restore to a fresh `XDG_*`, run `check` and the S0 probes) becomes a CI-able R0 test, without Foundry.
- Out of scope: privacy controls on what leaves the machine, the status page, and retention of raw audio. These are other leaves of #197.
