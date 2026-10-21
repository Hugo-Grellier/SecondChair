# Security policy

Read for authentication, authorization, data visibility, search/retrieval, user-facing data, file paths, integrations, secrets, or agent tools. The [security review skill](../../.agents/skills/ballast-security-review/SKILL.md) applies when the [review matrix](workflow.md#review-triggers) calls for it. Project-specific rules live in [`project/security.md`](project/security.md) when the project provides one; they extend this policy and win on conflict. The project file names its confidentiality boundary and trusted integrations.

## Confidentiality boundary

Authorization gates every read. Authorize before constructing retrieval candidates or exposing details, titles, counts, snippets, metadata, citations, links, embeddings, model context or MCP results. **Filtering after retrieval is not sufficient when retrieval itself can expose existence, counts, metadata, citations or model context.** Check direct object references and cross-tenant IDs through the same boundary.

Unknown, invalid, malformed or ambiguous access rules fail closed. A permission downgrade, revoked grant, invalid source or failed reindex must not leave stale data readable by users who lost access. Privileged stale views, if provided, must be explicit. Security-sensitive failures prefer temporary unavailability over disclosure.

## Untrusted boundaries

- Resolve file paths against their permitted root; reject traversal and symlink escape. Consider races between validation and use. Reading, parsing and indexing must not silently mutate authored files.
- Treat Markdown, YAML, links, external provider payloads and model output as untrusted. Parse safely and preserve provenance; review derived claims before writing them to an authoritative source.
- Keep external commands as argument arrays, pass a validated path as one argument, and never interpolate an untrusted value into a shell.
- Bound external services, webhooks, APIs and MCP tools by the caller's identity and permissions. An agent or tool has no independent authority.
- Keep passwords, tokens, provider keys and restricted content out of shared logs and repository artifacts. Local destinations and credentials belong in ignored local files or environment variables; host-dependent tests skip when unset.
