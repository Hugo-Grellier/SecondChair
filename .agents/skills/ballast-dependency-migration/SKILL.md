---
name: ballast-dependency-migration
description: Plan or review replacement of a foundational dependency such as an ORM, framework, transport, or provider SDK.
---

# Dependency migration

Read `docs/policies/dependencies.md`, plus `docs/policies/project/dependencies.md` when it exists. Inventory all current usage and characterize behavior with meaningful tests. Evaluate the replacement, including supported versions, security, license and provider lock-in. Add a compatibility boundary only where it reduces migration risk. Implement in reviewable slices, compare old/new behavior, switch, observe, remove the old package and temporary scaffolding, clean lockfiles and update docs. Record rollback and exceptions to this sequence; a one-shot rewrite requires a documented reason.

Report remaining behavior gaps and the exact safe switch/removal condition. Do not call a migration complete while both packages or compatibility scaffolding remain without a tracked reason.
