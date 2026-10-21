# Agent instructions for SecondChair

SecondChair is a human-directed, AI-operated campaign director for tabletop GMs: the GM keeps the creative calls, agents operate what the GM delegates. v4 targets PF2e on Foundry VTT. This file is for agents developing SecondChair; it says nothing about the agents SecondChair serves at the table.

## Work from the right artifact

- Layout: `src/secondchair/` (Core, CLI, bench, playbooks), `src/secondchair_pf2e/` (PF2e System extension), `src/secondchair_foundry/` (the connector's Python half), `foundry/` (the Foundry modules, JavaScript), `tests/`, `sample-campaign/`, `scripts/` (guards).
- Authority, in this order: the accepted ADRs in [`docs/adr/`](docs/adr/), the [spec](docs/spec/README.md) and [contracts](docs/contracts/), the vocabulary of [`GLOSSARY.md`](GLOSSARY.md), then the issue's outcome and acceptance criteria. Generic Ballast defaults in [`docs/policies/`](docs/policies/) come last; the SecondChair files in `docs/policies/project/` override them.
- Current code is evidence of behaviour, not permission to supersede a decision. Surface a conflict instead of resolving it in code. A cross-cutting data or architecture decision needs a proposed ADR approved by the owner before implementation ([project workflow](docs/policies/project/workflow.md#risk)).
- Ballast's words (coordinator, worker, skill, source) are development-workflow terms. In product code and docs, use the glossary: agent host, agent, runner, playbook, Source.

## Commands

- Install: `uv sync --locked`, `npm ci`.
- Fast gate: `uv run pre-commit run --all-files`. Full gate: the [verification matrix](docs/policies/project/workflow.md#verification-matrix), which adds the S0 scripted bench.
- Record exact commands and any gate not run in the PR. See the [testing policy](docs/policies/testing.md).

## Invariants

- The Core depends on nothing and is the only MCP server agents see; no agent talks to the VTT directly (ADR 0003, ARC-01, ARC-03).
- The Core calls no generative model; work that needs one is a job (ADR 0001). SecondChair has no runtime dependency on Ballast.
- The campaign workspace's Markdown and YAML are authoritative; SQLite is derived and rebuildable.
- No campaign workspace, Source, Paizo text or private material enters the repository, its issues or its PRs ([project security](docs/policies/project/security.md)).
- Everything in the tool is in English (VIS-04). CI holds no model credentials (BEN-06).

## Issue workflow

`BALLAST_SOURCE` is a Ballast checkout at the [adopted tag](docs/policies/README.md), outside this repository; put its local path in the ignored `AGENTS.local.md`. Paths under `BALLAST_SOURCE` never resolve here.

- For `Start #N`, `Fix #N`, `Investigate #N` or `Continue #N`, follow `BALLAST_SOURCE/docs/issue-workflow.md`. Dispatch only an actionable leaf issue, never an Epic or an issue with an open product decision.
- One branch, one worktree and one writer per issue. Workers run through `BALLAST_SOURCE/docs/standalone.md` (Codex app-server on the owner's subscription) with an explicit model and effort verified before task input (`BALLAST_SOURCE/docs/model-routing.md`). An unverified or unavailable route blocks; never fall back to another provider or a paid API.
- An independent reviewer follows `BALLAST_SOURCE/docs/pair-review.md` on the exact committed head: at most three review/fix rounds, then the owner decides.
- One active architectural issue at a time. Overlapping Core changes are serialised, never run in parallel.

## Risk and conditional guidance

Classify R0, R1 or R2 with the [project risk table](docs/policies/project/workflow.md#risk). R2 needs the owner's approval of the design and of the merge. The owner is the only merge decision maker for every PR: an agent never merges, releases or deploys, and an agent decision is never presented as human approval. The [review matrix](docs/policies/workflow.md#review-triggers) selects reviewers.

| When changing | Read and use |
| --- | --- |
| Any implementation | [Engineering policy](docs/policies/engineering.md); [engineering review](.agents/skills/ballast-engineering-review/SKILL.md) |
| Delegation, disclosure, the ceiling, Sources, secrets, MCP tools | [Security policy](docs/policies/security.md) and [security review](.agents/skills/ballast-security-review/SKILL.md) |
| Behaviour or acceptance evidence | [Testing policy](docs/policies/testing.md) and [test review](.agents/skills/ballast-test-review/SKILL.md) |
| Dependency or GitHub Action | [Dependency policy](docs/policies/dependencies.md) and [evaluation](.agents/skills/ballast-dependency-evaluation/SKILL.md); [migration](.agents/skills/ballast-dependency-migration/SKILL.md) for a foundational replacement |
| Workspace format or derived index | [Migration policy](docs/policies/migrations.md) and [migration review](.agents/skills/ballast-database-migration/SKILL.md) |
| Public behaviour, configuration, spec, ADR | [Documentation policy](docs/policies/documentation.md) and [documentation review](.agents/skills/ballast-documentation-review/SKILL.md) |

Never silently weaken a failing test, guard, validation, delegation check, lint or type rule; change source authority; add a second source of truth; or mix unrelated refactors into the work.

## PRs and local environment

Follow the [PR template](.github/pull_request_template.md). Titles and commits use Conventional Commits (`feat: ...`, `fix: ...`, `docs: ...`). PRs open as drafts. Before a destructive operation or an externally visible action (merge, release, label or branch-protection change), get the owner's explicit approval in the PR or conversation.
