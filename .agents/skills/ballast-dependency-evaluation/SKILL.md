---
name: ballast-dependency-evaluation
description: Evaluate a proposed or updated dependency, lockfile, image, or Action for fit, advisories, runtime support, license, footprint, and exit cost.
---

# Dependency evaluation

Read `docs/policies/dependencies.md`, plus `docs/policies/project/dependencies.md` when it exists, then the diff and the package's current upstream release/support/advisory/license information. State need and class; stdlib or existing alternatives; maintenance; supported versions and runtime fit; known advisories; license fit; transitive, network, filesystem and process footprint; lock-in and exit strategy. Give provider, persistence and framework changes extra scrutiny. For a prerelease, identify qualification evidence and tracking issue.

Report a recommendation (`accept`, `revise`, `reject`) with evidence links and concrete follow-up. Treat a foundational replacement as a migration with the `ballast-dependency-migration` skill, not a routine version bump.
