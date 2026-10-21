---
name: ballast-database-migration
description: Review or plan a database schema or data migration, especially changes to identity, ownership, access rules, or grants.
---

# Database migration

Read `docs/policies/migrations.md`, plus `docs/policies/project/migrations.md` when it exists, then the changed migration and the affected data model. Check expand/compatible-code/backfill/verify/switch/observe/contract sequencing, mixed-version behavior, rollback and backup, idempotent backfill, failed-run recovery, locks and data volume. For resource IDs, bindings, source locators, access rules, membership or grants, require representative old-data characterization and explicit identity/authorization verification.

Report `review: migration`, verdict, migration phase, risks, exact verification evidence and required actions. Do not assume fresh or empty production data once releases exist.
