# SecondChair
Human-directed, AI-operated campaign director for tabletop GMs (PF2e + Foundry first)

## Install

Python 3.14 or later, with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install "secondchair @ git+https://github.com/Hugo-Grellier/SecondChair@<tag>"
secondchair init ~/campaigns/my-campaign --language en --calendar absalom
secondchair serve ~/campaigns/my-campaign
```

`serve` listens on 127.0.0.1 only, on the port set in `~/.config/secondchair/config.yaml` (`port: 7240` by default). The workspace layout is described in [`docs/contracts/workspace-layout.md`](docs/contracts/workspace-layout.md).

Agents reach the campaign through the Core's MCP server at `http://127.0.0.1:7240/mcp` (Streamable HTTP). To configure an agent host, run `secondchair host setup claude` or `secondchair host setup codex` and apply what it prints; it never edits the host's files. How blocks register tools is described in [`docs/contracts/tool-registration.md`](docs/contracts/tool-registration.md).

Every delegated action goes through the Core, at the level the campaign's delegation table (`delegation.yaml`) gives its responsibility in the current moment. From the workspace directory:

```sh
secondchair moment between-sessions        # interactive terminal only
secondchair session start                  # open the live session (interactive terminal only)
secondchair break                          # signal a break: show the calls held for it
secondchair session end --notes notes.md   # end it and queue "wrap a session" on your notes
secondchair wrap 1                         # the wrap's round, then advance the date (interactive only)
secondchair approve 3                      # apply a pending proposal
secondchair reject 3 --reason tone         # contradiction, rules, tone or other
secondchair log undo 2 --reason rules      # undo an action of the current moment
secondchair override add e-1a2b3c4d npcs manual   # I voice this NPC myself
secondchair override remove e-1a2b3c4d npcs       # hand it back (interactive terminal only)
secondchair hold lift disclosure live-session    # let disclosures run at their level, no undo (interactive only)
secondchair hold restore disclosure live-session # hold them for approval again
```

To connect Foundry VTT, run `secondchair token` and install the `secondchair-foundry` module as described in [`foundry/README.md`](foundry/README.md). Your browser may ask once whether the Foundry site may connect to services on your computer: allow it.

Work that needs a model is a **job**: the Core queues it with its contract ([`docs/contracts/job.schema.json`](docs/contracts/job.schema.json)) and never calls a model itself. A runner starts it in Claude Code or Codex with the host, model and effort your machine configuration gives its tier (fast, standard or deep), trying each entry in order; without one, ask your own agent host session to start the job.

```sh
secondchair jobs queue rebuild-entities-from-a-bible --input bible=~/sources/bible.md
secondchair jobs                           # pending jobs and their tier
secondchair jobs run                       # start queued jobs with the configured runner
```

```yaml
# ~/.config/secondchair/config.yaml
runners:
  standard:                                # fast, standard or deep
    - {host: claude, model: <model>, effort: high}
    - {host: codex, model: <model>, effort: medium}   # tried if the first fails
```

The playbooks ship as a Claude Code plugin and a Codex skill bundle; `secondchair host setup` prints how to install them.

## Development

```sh
uv sync
npm ci                              # Biome, tsc and ajv for the Foundry modules
uv run pre-commit install
uv run pre-commit run --all-files   # ruff, ty, pytest, Biome, tsc --checkJs, node --test, the LIC-10 guard, actionlint, zizmor
```

CI runs the same checks, the Python ones on 3.14 and 3.15. The spec is in [`docs/spec/`](docs/spec/README.md).

The original [sample campaign](sample-campaign/README.md) supplies S0 material,
synthetic session notes and a frozen reference set under CC BY 4.0.
