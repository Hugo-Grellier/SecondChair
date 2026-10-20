# SecondChair security

Extends the [security policy](../security.md) and wins on conflict.

## Confidentiality boundary

SecondChair runs locally for one GM, so the base policy's users and tenants map onto two boundaries:

- **GM and players.** What reaches a player (Foundry visibility, chat, journals, the disclosure responsibility, the ceiling) is the access rule. A change that can show a player something the GM has not disclosed, or act above the ceiling, fails closed ([ADR 0003](../../adr/0003-core-is-the-only-gateway.md), [Foundry bridge](../../contracts/foundry-bridge.md)).
- **The campaign and the public repository.** Campaign workspaces and Sources never enter the repository (LIC-10, LIC-11, [08](../../spec/08-licensing-repos.md)). The guards in `scripts/` enforce part of this; they are not the whole rule.

Caller identity: the loopback MCP endpoint is unauthenticated by design (PKG-06, [ADR 0010](../../adr/0010-local-core-reached-by-the-gm-browser.md)). Where the base policy says authorization gates every read or MCP tools are bound to the caller, read it here as: a read is accepted at every delegation level, manual included, and its only gate is the content it returns (for example an audience check before anything reaches a player); a delegated action goes through the Core's level check for its responsibility and the job or session it is bound to (ARC-04, [tool registration](../../contracts/tool-registration.md)); an irreversible approval needs an authenticated Surface ([ADR 0003](../../adr/0003-core-is-the-only-gateway.md)). Do not add MCP authentication without a proposed ADR.

In these policies, "source" and "source of truth" mean the authoritative record of something. A capitalised **Source** is the glossary term: material the GM supplies.

## Private material and secrets

Never put any of these in a commit, issue, PR, review, CI log, Ballast progress record or test fixture, even redacted or quoted briefly:

- the owner's private campaign material (the Westerhold campaign, its workspace, notes and Sources);
- purchased or copyrighted PDFs and their text, Paizo text, stat blocks or translations;
- player transcripts, recordings, behaviour traces or player names from a real table;
- credentials, tokens, provider keys, subscription or account details, local hostnames, IPs and absolute paths.

Fixtures and evidence use the original sample campaign or new fictional material. Model access and credentials stay in the operator's environment and in ignored files such as `AGENTS.local.md`, never in the repository or CI. Raw worker output stays private; publish a curated summary and links.
