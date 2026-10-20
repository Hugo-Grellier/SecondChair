# SecondChair security

Extends the [security policy](../security.md) and wins on conflict.

## Confidentiality boundary

SecondChair runs locally for one GM, so the base policy's users and tenants map onto two boundaries:

- **GM and players.** What reaches a player (Foundry visibility, chat, journals, the disclosure responsibility, the ceiling) is the access rule. A change that can show a player something the GM has not disclosed, or act above the ceiling, fails closed ([ADR 0003](../../adr/0003-core-is-the-only-gateway.md), [Foundry bridge](../../contracts/foundry-bridge.md)).
- **The campaign and the public repository.** Campaign workspaces and Sources never enter the repository (LIC-10, LIC-11, [08](../../spec/08-licensing-repos.md)). The guards in `scripts/` enforce part of this; they are not the whole rule.

In these policies, "source" and "source of truth" mean the authoritative record of something. A capitalised **Source** is the glossary term: material the GM supplies.

## Private material and secrets

Never put any of these in a commit, issue, PR, review, CI log, Ballast progress record or test fixture, even redacted or quoted briefly:

- the owner's private campaign material (the Westerhold campaign, its workspace, notes and Sources);
- purchased or copyrighted PDFs and their text, Paizo text, stat blocks or translations;
- player transcripts, recordings, behaviour traces or player names from a real table;
- credentials, tokens, provider keys, subscription or account details, local hostnames, IPs and absolute paths.

Fixtures and evidence use the original sample campaign or new fictional material. Model access and credentials stay in the operator's environment and in ignored files such as `AGENTS.local.md`, never in the repository or CI. Raw worker output stays private; publish a curated summary and links.
