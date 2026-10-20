# Migration policy

Project-specific rules live in [`project/migrations.md`](project/migrations.md) when the project provides one; they extend this policy and win on conflict.

State the old/new version compatibility window, backup and restore path, backfill idempotence, verification query or invariant, failure recovery, and when contraction becomes safe. A failed migration must not corrupt identity or silently report success. Use a representative upgraded database when a previous release exists.
