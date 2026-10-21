---
name: ballast-engineering-review
description: Review a feature diff for requirement coverage, architecture, failure behavior, data integrity, and unnecessary complexity; use for correctness or architecture review before a PR.
---

# Engineering review

Read the issue/spec and acceptance criteria, the diff, and engineering policy: Read `docs/policies/engineering.md`, plus `docs/policies/project/engineering.md` when it exists. Read the project's domain glossary and only the relevant accepted architecture sections and ADRs for domain or boundary changes. For architecture review, identify the exact existing decision and whether a new ADR is required.

Inspect requirement coverage, source authority, durable identity, duplicated responsibility, unnecessary abstraction, concurrency, partial failure, compatibility, and silent scope expansion. Trace changed behavior through callers and persistence. Leave formatting to the project's linters and formatters.

Report `review: engineering`, `verdict: approved | changes_required`, then findings with `id`, `severity`, `location`, `invariant_or_requirement`, `evidence`, and `required_action`. Separate facts from uncertainty. A clean review names the behavior and boundaries checked.
