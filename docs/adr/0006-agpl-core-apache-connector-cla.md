# AGPL-3.0 for the Core, Apache-2.0 for the Foundry modules, and a CLA for outside contributions

SecondChair is open source, but if it works well the owner wants to keep a closed hosted fork from capturing it and to keep a later monetization path open. So the Core, the PF2e System extension, the CLI and the test-bench harness are AGPL-3.0: anyone hosting a modified copy must publish their changes. The Foundry modules (`secondchair-foundry`, `secondchair-foundry-pf2e`) and the playbooks are Apache-2.0, because an AGPL plug-in running inside proprietary Foundry carries risk, and the two licences mix freely across the WebSocket. Every outside contribution is accepted only under a CLA (a bot on pull requests), so the owner keeps the right to dual-license or run an official hosted service. The copyright on outside contributions is the part that cannot be undone later, which is why the CLA starts before the first outside pull request. Everything lives in one public monorepo, with releases tagged per package. The repository goes public when the v4 spec is handed off.

## Considered Options

- **Apache-2.0 everywhere**: rejected; it gives no leverage against a closed hosted fork.
- **Source-available (FSL, BSL)**: rejected; not open source, and it pushes away the technical GMs and contributors v4 targets.
- **AGPL without a CLA**: rejected; contributions would freeze the licence and rule out dual licensing.
- **One repository per package**: deferred; the Core and the connector contracts change together during v4. An adapter maintained by a third party can live in its own repository, since it plugs in through a hook (ADR 0004).
