# SecondChair workflow

Extends the [workflow policy](../workflow.md) and wins on conflict.

## Risk

R2 here, beyond the base list. Raise to R2 when the diff touches any of these, even through a helper or a test fixture that changes what ships:

| Boundary | Examples | Authority |
| --- | --- | --- |
| Provenance and ranking | Canon ranking (played, GM decision, cited official source, agent proposal), citations, capture, candidate facts, the wrap | [ADR 0007](../../adr/0007-facts-are-the-unit-of-canon.md), [ADR 0008](../../adr/0008-capture-cited-facts-rank-as-played.md), [04](../../spec/04-canon-memory-capture.md) |
| Role, permission and delegation | Responsibilities, delegation levels and table, entity overrides, MCP tool registration and its read/action/reversible flags, job and session binding | [ADR 0003](../../adr/0003-core-is-the-only-gateway.md), [03](../../spec/03-delegation.md), [tool registration](../../contracts/tool-registration.md) |
| Canon writes | Anything that writes facts, entities, relations, decisions or the action log in the campaign workspace | [ADR 0007](../../adr/0007-facts-are-the-unit-of-canon.md), [workspace layout](../../contracts/workspace-layout.md) |
| Transactional recovery and undo | Undo, irreversible actions, crash recovery, the derived SQLite index and its rebuild | [02](../../spec/02-architecture.md), [workspace layout](../../contracts/workspace-layout.md) |
| Temporal state | Campaign calendar, current date, world-turn, forecast, occurrences | [ADR 0009](../../adr/0009-world-turn-deterministic-three-effect-classes.md), [ADR 0014](../../adr/0014-declarative-campaign-calendar-core-follows-paizo.md), [05](../../spec/05-living-world-calendar.md) |
| Foundry ceiling and player disclosures | The ceiling, the Foundry write queue and bridge, what players can see, behaviour-trace consent | [ADR 0004](../../adr/0004-foundry-connector-library-plus-system-adapters.md), [ADR 0010](../../adr/0010-local-core-reached-by-the-gm-browser.md), [ADR 0012](../../adr/0012-behaviour-traces-capture-raw-input-with-consent.md), [Foundry bridge](../../contracts/foundry-bridge.md) |
| Licensed Sources and secrets | Sources, the reference library, shipped content, the sample campaign, the LIC guards, credentials, runner configuration | [ADR 0006](../../adr/0006-agpl-core-apache-connector-cla.md), [08](../../spec/08-licensing-repos.md), [project security](security.md) |
| Destructive migration and backup restore | Workspace format changes that rewrite or drop authored files, export, restore | [migrations policy](../migrations.md), [09](../../spec/09-packaging.md) |
| CI and release permissions | `.github/`, workflow permissions, pinned Actions, pre-commit hooks, guard scripts, branch protection, packaging and release | [ci.yml](../../../.github/workflows/ci.yml), [#76](https://github.com/Hugo-Grellier/SecondChair/issues/76) |

R2 needs the owner's explicit approval of the design before implementation (on the issue or a proposed ADR) and of the merge. R1 is a feature inside an existing contract; R0 is docs, tests or cleanup that changes no shipped behaviour. Changing an R2 rule's meaning is never a routine fix: an agent does not reinterpret provenance, temporal or permission rules on its own, it stops and asks.

A cross-cutting data or architecture decision (a source of truth, a persistence format, a process or package boundary, the permission model, narrative authority, release policy) starts as a proposed ADR: a new `docs/adr/NNNN-*.md` in its own draft PR, labelled `ready-for-human`. It is accepted when the owner merges it; implementation waits for that.

## Review triggers

On top of the base matrix: any R2 row above gets an architecture review against the ADR or spec section the row names. Player disclosure, the ceiling, Sources and secrets also get the security review.

## Verification matrix

Run what the change touches; run all of it before marking an R1 or R2 PR ready. CI runs the same commands (`.github/workflows/ci.yml`); `uv run pre-commit run --all-files` runs the Python, Foundry, guard and workflow rows locally with the pinned tools.

| Area | Commands |
| --- | --- |
| Python 3.14 and 3.15 | `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest` |
| Foundry modules (Node 22) | `npm ci`, `npx biome ci`, `npx tsc --project tsconfig.json`, `node --test "foundry/**/*.test.js"` |
| S0 bench | `uv run secondchair bench s0 <empty dir> --runner fake/scripted/none` (scripted fake runner only; a real-model run is local and the GM's) |
| Licensing and Source guards | `uv run python scripts/guard_no_workspace.py`, `uv run python scripts/guard_sample_campaign.py` |
| Workflows | `uv run actionlint`, `uv run zizmor --offline .github/workflows` |

The PR records each command run with its result, and every gate not run with the reason. Only a command actually executed counts; an agent's claim that checks pass is not evidence. Link the CI run for the exact head that was reviewed: a run on an earlier head, a pending or missing check, or a run on another base does not count, and keeps the PR draft.
