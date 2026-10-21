# Dependency policy

Use this for manifest, lockfile, container image or GitHub Action changes. Project-specific rules live in [`project/dependencies.md`](project/dependencies.md) when the project provides one; they extend this policy and win on conflict. The project file lists its lockfiles, update automation and known exceptions.

Keep every lockfile committed and install from it in CI. Prefer the repository's existing update automation (for example Dependabot) over adding another tool until a concrete missing capability justifies migration. Broad dependency auto-merge stays disabled.

Prerelease, nightly and `next` versions need a documented reason, qualification evidence and a tracked upgrade or replacement plan. Do not force an audit fix that changes generated output without comparing it.

Patch updates may get automated PRs and normal checks. Minor updates need review of changed behavior; major or foundational updates follow the [dependency migration skill](../../.agents/skills/ballast-dependency-migration/SKILL.md). Security advisories can raise urgency regardless of version class.
