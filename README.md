# SecondChair
Human-directed, AI-operated campaign director for tabletop GMs (PF2e + Foundry first)

**New here? Follow [Your first hour](docs/first-hour.md)**: install to a wrapped session, with every command and what you should see. Not sure what to ask your agent? See [What to ask](docs/what-to-ask.md).

## Install and reference

The quickest path is [Your first hour](docs/first-hour.md); this section is the full reference.

Python 3.14 or later, with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install "secondchair @ git+https://github.com/Hugo-Grellier/SecondChair@main"
secondchair init ~/campaigns/my-campaign --language en --calendar absalom
secondchair serve ~/campaigns/my-campaign
```

`serve` listens on 127.0.0.1 only, on the port set in `~/.config/secondchair/config.yaml` (`port: 7240` by default). The workspace layout is described in [`docs/contracts/workspace-layout.md`](docs/contracts/workspace-layout.md).

`secondchair backup <workspace> <archive>` archives the workspace with a manifest of hashes, and `secondchair restore <archive> <new-dir>` verifies it into an empty directory and runs `check`; back up the Foundry world separately.

Agents reach the campaign through the Core's MCP server at `http://127.0.0.1:7240/mcp` (Streamable HTTP). To configure an agent host, run `secondchair host setup claude` or `secondchair host setup codex` and apply what it prints; it never edits the host's files. How blocks register tools is described in [`docs/contracts/tool-registration.md`](docs/contracts/tool-registration.md).

Every delegated action goes through the Core, at the level the campaign's delegation table (`delegation.yaml`) gives its responsibility in the current moment. From the workspace directory:

```sh
secondchair moment between-sessions        # interactive terminal only
secondchair session start                  # open the live session (interactive terminal only)
secondchair break                          # signal a break: show the calls held for it
secondchair session end --notes notes.md   # end it and queue "wrap a session" on your notes
secondchair transcribe --session 1 gm=gm.flac al=al.flac   # transcribe the tracks for the wrap job
secondchair jobs run                       # run the wrap job (or ask your agent to start it)
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

## The GM loop: create, prepare, play, wrap

The [GM guide](docs/gm-guide.md) walks through one campaign, and [What to ask](docs/what-to-ask.md) maps what you want to the playbook that does it. In short, with your agent open in the workspace:

- **Create**: talk ideas through with the `campaign-workshop` skill; confirmed decisions become canon (`secondchair confirm <id>…`), the rest stays in `notes/workshop/`.
- **Prepare**: "prepare session 3" runs `prepare-a-session`: a table-ready handoff in `prep/session-3/handoff.md` and the session's Foundry material (scenes, NPC actors, journals and hidden handouts, treasure, playlists).
- **Play**: Start session on the Director's Desk; `quick-help` answers last-minute needs ("an NPC for this tavern, now").
- **Wrap**: End session, `secondchair transcribe`, run the wrap job, `secondchair wrap 3`: what was played becomes canon.

`secondchair status` says where the campaign stands and what to do next.

## Review and read your prep

`serve` also shows a read-only page at `http://127.0.0.1:7240/`, for a second screen or a tablet next to Foundry: the pending proposals and open calls with their diff, the recent action log, the Markdown under `prep/` and `notes/` (rendered, with a table of contents, printable), the desired scenes and their last reconciliation, canon search and jobs. It refreshes itself every few seconds. It approves nothing: each entry shows the `secondchair approve`, `reject` or `log undo` command to run in your terminal, since only the CLI and the Director's Desk are authenticated Surfaces. It answers on loopback only, to `127.0.0.1` or `localhost` Host headers, and never serves a file outside `prep/` and `notes/`.

## Development and bench

For contributors and benchmark runners; GMs can stop above.

```sh
uv sync
npm ci                              # Biome, tsc and ajv for the Foundry modules
uv run pre-commit install
uv run pre-commit run --all-files   # ruff, ty, pytest, Biome, tsc --checkJs, node --test, the LIC-10 guard, actionlint, zizmor
```

CI runs the same checks, the Python ones on 3.14 and 3.15. The spec is in [`docs/spec/`](docs/spec/README.md).

The original [sample campaign](sample-campaign/README.md) supplies S0 material,
synthetic session notes and a frozen reference set under CC BY 4.0.

The S0 bench rebuilds the sample campaign three times at the delegated table and three times at
the manual baseline, and reports GM effort, entity recall and precision and the two invariants
from the stored action logs; it exits 1 when an invariant fails. CI runs it with the scripted fake
runner and holds no model credentials. The real run is local, with your own agent host:

```sh
uv run secondchair bench s0 ~/bench/s0-run --runner claude/<model>/high   # serves each run on your configured port
uv run secondchair bench s0 /tmp/s0 --runner fake/scripted/none          # what CI runs
uv run secondchair bench report ~/bench/s0-run                           # recompute from the stored logs
```

Two more benches need no model and no private material. They generate a seeded synthetic
campaign of 10, 100 or 400 sessions (S, M, L) through the Core's own APIs: `bench scale` reports
the Core's cost per size, and `bench recall` scores its temporal queries against a generated
gold set, in the GM's view and the party's, and exits 1 when the delayed-revelation or retcon
invariant fails. The gold set is generated, so its scores are tracked, not reference floors. M
takes about two minutes to generate; L takes far longer, because the Core rebuilds its index after every write (#172), and was not run. S is what the tests run.

```sh
uv run secondchair bench scale --sizes S,M
uv run secondchair bench recall --sizes S
```

S2, Beginner Box prep, is private: its scenario directory (`scenario.yaml` with the command that
restores the bench world from its snapshot and the `calibrate-encounters` job inputs, and
`gold.yaml` with what the scripted GM keeps) lives outside the repository. Each run restores the
bench world first, so a run never touches the players' world; the report gives prep GM effort,
failed actions and acceptance rate:

```sh
uv run secondchair bench s2 ~/bench/s2-run --scenario ~/bench-private/s2 --runner claude/<model>/high
```
