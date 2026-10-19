# Contract: campaign workspace layout

Workspace schema version: **1**. Requirements: ARC-17a, CAN-10, CAN-18, LIC-09, PKG-13, PKG-16.

A **campaign workspace** is a directory the GM chooses, outside the tool repository, optionally inside a private repository of their own (LIC-09). It is the source of truth for one campaign and its full export (PKG-15). `secondchair init <dir> --language <bcp47>` creates it; `secondchair serve <dir>` serves it.

## Tree

```text
my-campaign/
├── workspace.yaml     # schema version and campaign language; written by `init`
├── .gitignore         # contains `.secondchair/`; `init` appends to an existing one
└── .secondchair/      # derived state (SQLite index, caches); git-ignored, rebuildable
```

Later contracts add the canon, decisions, action log, delegation table, calendar, speaker table and friction reports next to `workspace.yaml`, each as Markdown + YAML (CAN-10). Nothing in `.secondchair/` is a source of truth: deleting it loses nothing.

## `workspace.yaml`

```yaml
schema_version: 1
campaign_language: fr
```

| Key | Type | Rule |
|---|---|---|
| `schema_version` | integer | The workspace schema this file follows (PKG-16). A version newer than the running SecondChair supports is refused. An older one blocks `serve` until `secondchair upgrade` migrates it in place, as a reviewable diff. |
| `campaign_language` | string, BCP 47 tag | Set at `init` and fixed for v4 (CAN-18). `init` refuses to run on an existing workspace, so it cannot be changed through the tool. |

## What is not in the workspace

- **The machine configuration** (PKG-13) lives in `$XDG_CONFIG_HOME/secondchair/` (default `~/.config/secondchair/`) and never travels with the workspace. Its `config.yaml` holds, so far, the port `serve` listens on:

  ```yaml
  port: 7240   # default when the file or the key is absent
  ```

- **Sources** (raw audio, full transcripts, Foundry worlds, rulebooks) stay outside both; the workspace only references them (PKG-12).

## In the tool repository

The tool never ships a workspace (LIC-09). The CI guard `scripts/guard_no_workspace.py` (LIC-10) fails on any tracked `workspace.yaml`, any file under a `.secondchair/` directory, and files that look like Sources (audio, PDF, a Foundry `world.json`), except inside the sample campaign's folder, `sample-campaign/`.
