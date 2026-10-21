---
name: ballast-security-review
description: Review changes that affect authentication, authorization, data visibility, search, paths, secrets, external integrations, or agent authority.
---

# Security review

Read the change, relevant acceptance criteria, security policy at `docs/policies/security.md` (plus `docs/policies/project/security.md` when it exists) and the Invariants section of the project's `AGENTS.md`, then the affected authority boundary. Trace an authorized user, an unauthorized user, a user whose access was just revoked or downgraded, and malformed input through the changed path. Check whether inaccessible content can be inferred through existence, counts, metadata, citations, search candidates or model context; cross-tenant IDs; stale caches after revocation; malformed access rules; direct object references; path traversal and symlink escape; untrusted YAML/Markdown; shell/process execution; external service trust; MCP permissions; external API input/output; secret/log exposure; and agent/tool authority relative to the caller. Add the boundaries the project policy lists. Scope checks to the affected surface and state what was examined.

Return structured findings, for example:

```yaml
review: security
verdict: changes_required
findings:
  - id: SEC-001
    severity: high
    invariant: <AGENTS.md invariant, if any>
    location: path/to/file:line
    description: Concrete disclosure path and evidence
    required_action: Specific correction and regression evidence
```

Use `approved` with `findings: []` only after relevant paths and negative cases are accounted for. Distinguish demonstrated defects from unresolved assumptions.
