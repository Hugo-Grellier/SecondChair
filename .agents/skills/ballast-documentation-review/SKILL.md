---
name: ballast-documentation-review
description: Review documentation when user behavior, configuration, API, operations, or an architecture decision changes.
---

# Documentation review

Read `docs/policies/documentation.md`, plus `docs/policies/project/documentation.md` when it exists, then the diff and affected public interface. Check README/setup, generated API and config examples, migration/recovery steps, permission wording, failure states and screenshots where UI changed. Check whether a major decision needs a new ADR and whether existing ADR history is preserved.

Report `review: documentation`, verdict, mismatches and exact files/actions. Prefer a truthful limitation to an undocumented assumption. Ignore comments that simply narrate code.
