# Development policies

Copied from [Hugo-Grellier/ballast](https://github.com/Hugo-Grellier/ballast) on 2026-10-20.

| Adopted | Value |
| --- | --- |
| Tag | [`v2.1.0`](https://github.com/Hugo-Grellier/ballast/tree/v2.1.0) |
| Commit | `d0db2c717d0f2192a31f6efd3ffd77a16fec405a` |

- `docs/policies/*.md` and `.agents/skills/ballast-*` are the Ballast templates as published, except that Ballast links point at the tag rather than `main`, and [triage labels](triage-labels.md) and the [issue tracker](issue-tracker.md) use only the labels this repository has.
- [`project/`](project/) holds SecondChair's rules; they extend the generic policies and win on conflict.
- [`AGENTS.md`](../../AGENTS.md) and the [PR template](../../.github/pull_request_template.md) are rewritten from the Ballast starters.
- Not adopted: the observability policy, Dependabot, the issue template and the PR-title workflow. Ballast's source and helpers stay in a separate checkout; nothing here imports or runs them.

Ballast never overwrites these copies. To upgrade, diff the templates between the adopted tag and the new one (`git diff v2.1.0..vB -- templates/` in a Ballast checkout), apply what fits by hand in a reviewed PR, and update the table above. To remove Ballast, revert the adoption commit.

The copied files keep Ballast's MIT licence ([`LICENSE`](LICENSE) here and in `.agents/skills/`).
