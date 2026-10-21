# Documentation policy

Project-specific rules live in [`project/documentation.md`](project/documentation.md) when the project provides one; they extend this policy and win on conflict.

Update user and operator documentation when public behavior, configuration, API contracts, permissions, migration steps or failure semantics change. Keep README commands synchronized with scripts and CI; include screenshots for visible UI PRs. Explain the behavior and operational consequence, not obvious code.

Comments explain why, invariants, security assumptions, provider/protocol quirks, workarounds and compatibility constraints. A persistent TODO/FIXME normally cites an issue or upstream limitation. Track security or correctness requirements as work with an owner and acceptance criteria; do not defer them through an untracked TODO.

Write a new ADR for an accepted decision introducing or changing a source of truth, persistence subsystem, service/process boundary, resource identity semantics, authorization architecture, major provider abstraction or deployment architecture. Ordinary implementation choices stay in the plan or PR. Keep historical ADRs; supersede them explicitly rather than editing away the decision history. Read the domain glossary and the relevant architecture section when domain behavior changes.
