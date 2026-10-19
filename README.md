# SecondChair
Human-directed, AI-operated campaign director for tabletop GMs (PF2e + Foundry first)

## Install

Python 3.14 or later, with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install "secondchair @ git+https://github.com/Hugo-Grellier/SecondChair@<tag>"
secondchair init ~/campaigns/my-campaign --language en
secondchair serve ~/campaigns/my-campaign
```

`serve` listens on 127.0.0.1 only, on the port set in `~/.config/secondchair/config.yaml` (`port: 7240` by default). The workspace layout is described in [`docs/contracts/workspace-layout.md`](docs/contracts/workspace-layout.md).

## Development

```sh
uv sync
uv run pre-commit install
uv run pre-commit run --all-files   # ruff, ty, pytest, the LIC-10 guard, actionlint, zizmor
```

CI runs the same checks on Python 3.14 and 3.15. The spec is in [`docs/spec/`](docs/spec/README.md).
