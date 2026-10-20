---
name: ballast-test-review
description: Review tests and acceptance evidence for a behavior change, including negative cases, failure paths, integration seams, and regressions.
---

# Test review

Read the issue/spec acceptance criteria, changed behavior, tests and testing policy: Read `docs/policies/testing.md`, plus `docs/policies/project/testing.md` when it exists. Map each material criterion to executable evidence. Check denial and failure paths, overmocking, fixtures, and whether a real database, browser or API seam is needed. Flag a test that cannot fail when the relevant behavior breaks.

Report `review: tests`, `verdict: approved | changes_required`, covered criteria, missing evidence, exact location and required action. Do not request a coverage percentage or tests that merely mirror implementation.
