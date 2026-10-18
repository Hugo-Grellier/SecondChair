# Rebuild rather than evolve the existing tool

SecondChair v4 is a clean rebuild in this repository, in English, split into Core / System extension / VTT connector / Surface from the start, with Python (`uv`) for the Core, System extension and CLI and JavaScript only inside the Foundry connector. The predecessor (`pf2e-open-campaign`) is carried over as a **specification**, not as a codebase: its contracts, algorithms and test cases become English ADRs and acceptance tests, and only pure, dependency-free algorithms are transplanted (translated, each into its building block): calendar arithmetic, XP and treasure tables, world-turn occurrence keys, the mystery graph, scene reconciliation, and the Foundry reliability mechanisms (idempotent requests, write queue, durable capture). We chose this because the predecessor was never proven in a real session, so a rebuild loses tests rather than field validation, while evolving it in place would mean translating ~25 k lines of French prose and untangling PF2e and Foundry logic that leaks into its generic code. The price is rewriting working, tested code.

## Considered Options

- **Evolve in place** (translate, split layers, rename): rejected. The v4 seams do not exist in the predecessor, and French reaches into data-contract words.
- **Copy then refactor**: rejected. It would import the tangled boundaries the rebuild exists to remove.

## Consequences

- No storage compatibility with the predecessor and no migration path: the v4 format is free.
- Dropped outright: French contract words, the read / prep / play access levels (replaced by the delegation model), LoreForge-specific transcript revision, and every shipped campaign or GIS dataset. The Absalom calendar and the GIS import survive as code in the PF2e System extension, with no data.
- The predecessor is stopped now and archived (private, read-only); it remains the reference for the v3 spec and for transplants.
- The Westerhold campaign, a fictional test campaign, is not migrated: its v3 bible becomes a read-only source that v4 rebuilds with its own playbooks, as an acceptance scenario of the test bench. Real-session material comes from the PF2e Beginner Box (Foundry world and recorded sessions).
