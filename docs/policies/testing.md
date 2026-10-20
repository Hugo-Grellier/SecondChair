# Testing policy

Project-specific rules live in [`project/testing.md`](project/testing.md) when the project provides one; they extend this policy and win on conflict. The project file names its critical evidence and its check commands.

The objective is **behavioral evidence**, not a coverage percentage. A changed behavior needs a test at the boundary that can fail when the behavior regresses. Include meaningful denial, invalid-input and partial-failure paths for sensitive behavior.

Use the smallest test seam that proves the behavior. Use the real database for constraints and migrations, and browser/API acceptance for cross-layer behavior. External service qualification runs only when the change needs it, with destinations supplied by environment. Fixtures must be fictional and reusable.

Do not game a metric with trivial assertions, mocks of the behavior under test, deleted difficult tests, or exclusions of important modules. Never weaken a failing test merely to pass CI. Record commands and outcomes in the PR, including skipped gates and why.

Run the project's fast local gate on every change and its full local gate before a behavior-bearing PR.
