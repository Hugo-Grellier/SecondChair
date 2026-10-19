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

## Development

```sh
uv sync
uv run pre-commit install
uv run pre-commit run --all-files   # ruff, ty, pytest, the LIC-10 guard, actionlint, zizmor
```

CI runs the same checks on Python 3.14 and 3.15. The spec is in [`docs/spec/`](docs/spec/README.md).

The original [sample campaign](sample-campaign/README.md) supplies S0 material,
synthetic session notes and a frozen reference set under CC BY 4.0.
