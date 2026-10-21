# 09 — Packaging and deployment

Decision: [ADR 0010](../adr/0010-local-core-reached-by-the-gm-browser.md); ticket [#18](https://github.com/Hugo-Grellier/SecondChair/issues/18), amended for transcripts ([README](README.md#amendments-settled-while-writing-this-spec-gm-2026-10-19)).

## Install

- **PKG-01** Plain Python install with `uv tool install`, one extra per building block (`[pf2e,foundry,capture]`), from a git tag of the public repository (PKG-17). No Docker image in v4.
- **PKG-02** Python ≥ 3.14; CI on 3.14 and 3.15 (the floor rises once the capture stack supports 3.15).
- **PKG-03** Linux and macOS first-class; Windows through WSL, best effort.

## Process

- **PKG-04** One long-running `secondchair serve <workspace>` per campaign, one active campaign per machine, on a configurable port.
- **PKG-05** Agents reach the Core over MCP Streamable HTTP on 127.0.0.1. No stdio mode: several agents (the GM's session, the runners) and the Foundry module share one Core over one workspace.
- **PKG-06** The loopback MCP endpoint is unauthenticated. That is acceptable because irreversible approvals require an authenticated Surface ([ADR 0003](../adr/0003-core-is-the-only-gateway.md)).

## Foundry link

- **PKG-07** The Foundry module, running in the active GM's browser client, opens a WebSocket to the loopback Core. The Core never dials Foundry, so a remotely hosted Foundry (The Forge, a homelab) works the same.
- **PKG-08** The module authenticates with a shared token the Core generates (`secondchair token`) and keeps in the machine configuration, mode 0600. One GM connection at a time.
- **PKG-09** The handshake checks the protocol version and that the Foundry world matches the one declared in the workspace, and refuses a mismatch.
- **PKG-10** The Core sees and acts on Foundry only while a GM client is open, in prep as in play. Without one, VTT actions fail cleanly and the desired state waits for reconciliation.
- **PKG-11** The install docs say that Firefox (and possibly Chrome) asks once per site before a page may open a loopback WebSocket. While that prompt is unanswered the module shows, after a few seconds, a non-blocking notice pointing to the prompt or the site permissions, and keeps waiting.

## Where things live

| Place | Holds |
|---|---|
| Campaign workspace (GM-chosen directory) | Canon, decisions, action log, delegation table, campaign language and calendar, speaker table, friction reports, `workspace.yaml` (schema version) |
| `.secondchair/` inside the workspace, git-ignored | The derived SQLite index and caches |
| Machine configuration (`~/.config/secondchair/`) | Runner configuration, Source locations, port, Foundry token |
| Outside both | Sources: raw audio, full transcripts, raw behaviour traces, Foundry worlds, rulebooks |

- **PKG-12** Sources are referenced by id and hash, never copied into the workspace.
- **PKG-13** The machine configuration never travels with the workspace.

## Secrets

- **PKG-14** The only secret the tool manages is the Foundry token. The Hugging Face token WhisperX / pyannote still need for diarization comes from an environment variable. Agent hosts handle their own authentication ("bring your own agent host").

## Export and schema evolution

- **PKG-15** The workspace is the full export. `secondchair check` rebuilds the index and validates everything from the directory alone. Neither Foundry state nor Sources are included.
- **PKG-16** `workspace.yaml` carries the schema version. A newer schema is refused. An older one blocks `serve` until `secondchair upgrade` migrates it in place, as a reviewable diff.
- **PKG-23** `secondchair backup <workspace> <archive>` writes a gzip tar (mode 0600, never over a file, outside the workspace) of every file except `.secondchair/`, with a `manifest.json`: each file's path and SHA-256, the schema and SecondChair versions, the git commit when the workspace is a repository, the bound Foundry world id, the versions the handshake last reported (the newest recorded `rules_context`), and the time of the Foundry world backup the GM declares with `--foundry-backup-at`. It takes the workspace lock and refuses while an action is `unknown` or a job is `started`. `--with-library-cache` also copies `$XDG_DATA_HOME/secondchair/library/`. `secondchair restore <archive> <new-dir>` writes only into an empty or new directory, verifies every hash, runs `check`, and reports without fixing: the paired world and versions to compare, the machine configuration to set up again (token, runners, purchased content), library references and Sources with no path on this host (permissions are keyed by workspace path, so a restored workspace starts with none). The archive is not encrypted (the GM's backup tool does that). `upgrade --preview` and the copy-and-swap upgrade are separate leaves ([ADR 0018](../adr/0018-snapshot-boundary-restore-and-upgrade-consent.md)).

## Distribution

- **PKG-17** One Python distribution, `secondchair`, installable by `uv tool install`, with extras per block. v4 publishes to no package index: it installs from a git tag of the monorepo (`uv tool install "secondchair[…] @ git+https://github.com/Hugo-Grellier/SecondChair@<tag>"`). A wider distribution channel is decided after v4, with a Docker image as the preferred direction over a package index (settled in planning, 2026-10-19).
- **PKG-18** Foundry modules by manifest URL on GitHub releases, kept catalogue-compliant ([08](08-licensing-repos.md), LIC-16).
- **PKG-19** Playbooks as a Claude Code plugin and a Codex skill bundle. `secondchair host setup <claude|codex>` prints the host configuration and never writes host files.

## Development quality stack

- **PKG-22** Every package gates in CI on a modern QA stack, set up by the first ticket that writes code in its language (settled in planning, 2026-10-19):
  - Python: `ruff` for lint and format, `ty` for type checking, `pytest` for tests, all run through `uv` with versions pinned in the lock file;
  - JavaScript (Foundry modules): Biome for lint and format, and `tsc --noEmit` with `checkJs` for type checking;
  - one pre-commit configuration running the same checks locally;
  - GitHub Actions workflows checked by `actionlint` and `zizmor`.

  A check that fails blocks the merge; no rule is silenced without a comment naming why.

## Deferred

- **PKG-20** A remote or hosted Core is deferred, not excluded: `serve` already speaks HTTP and WebSocket, so hosting it means binding beyond the loopback and authenticating the MCP endpoint, with no contract change.
- **PKG-21** Docker can be added later without changing anything else.
