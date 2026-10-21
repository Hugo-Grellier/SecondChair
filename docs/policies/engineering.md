# Engineering policy

Apply this policy to code and behavior changes. The [workflow](workflow.md) owns risk and review routing; the project's `AGENTS.md` names its invariants. Project-specific rules live in [`project/engineering.md`](project/engineering.md) when the project provides one; they extend this policy and win on conflict.

When goals conflict, prioritize: **correctness → security → data integrity → source authority → backward compatibility → maintainability → observability → performance → developer convenience**. Surface a conflict with an accepted ADR or architecture document before changing behavior.

Keep changes within the issue. Prefer an existing module, standard library, or installed dependency to a new abstraction. Preserve explicit failure states. A failed operation must not appear successful.

An agent must never silently weaken a failing test or validation, broaden exception swallowing, add blanket lint/type suppressions, weaken authorization, change source authority, create a second source of truth, or fold in an unrelated refactor. Explain a necessary exception in the change and obtain the review required by its risk.

For an agent implementation, record deviations from the plan in the PR. The agent acts only with the caller's authority. Human approval is required for R2 work and for merging every feature PR.
