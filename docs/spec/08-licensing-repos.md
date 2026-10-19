# 08 — Licensing and repository split

Decision: [ADR 0006](../adr/0006-agpl-core-apache-connector-cla.md); tickets [#4](https://github.com/Hugo-Grellier/SecondChair/issues/4), [#11](https://github.com/Hugo-Grellier/SecondChair/issues/11), [#16](https://github.com/Hugo-Grellier/SecondChair/issues/16), [#22](https://github.com/Hugo-Grellier/SecondChair/issues/22). Not legal advice; open legal uncertainties are listed in the [#4 findings](https://github.com/Hugo-Grellier/SecondChair/blob/research/legal-constraints/research/legal-constraints.md).

## Licences

| Artefact | Licence |
|---|---|
| Core, PF2e System extension, CLI, test-bench harness | AGPL-3.0 |
| `secondchair-foundry`, `secondchair-foundry-pf2e` | Apache-2.0 |
| Playbooks | Apache-2.0 |
| Sample campaign (material and its gold set) | CC BY 4.0 |

- **LIC-01** AGPL keeps a closed hosted fork from capturing the Core: anyone hosting a modified copy must publish their changes.
- **LIC-02** The Foundry modules are Apache-2.0 because an AGPL plug-in running inside proprietary Foundry carries risk. The two licences mix freely across the WebSocket.
- **LIC-03** Every outside contribution is accepted only under a **CLA** (a bot on pull requests), so the owner keeps the right to dual-license or run an official hosted service. The CLA MUST be in place before the first outside pull request.
- **LIC-04** The monetization model itself is out of scope; the licences only keep it possible.

## Repositories

- **LIC-05** One public monorepo, `SecondChair`: Python packages and both Foundry modules in subfolders, releases tagged per package.
- **LIC-06** One private repository, `secondchair-bench-private`: private gold sets and the manifests of paths to Sources.
- **LIC-07** Raw Sources (Craig FLACs, the Beginner Box Foundry world, the Westerhold v3 bible) stay out of git.
- **LIC-08** A system adapter maintained by a third party may live in its own repository, since it plugs in through a hook ([ADR 0004](../adr/0004-foundry-connector-library-plus-system-adapters.md)).
- **LIC-09** A **campaign workspace** lives outside the tool at a path the GM chooses, optionally in their own private repository. The tool never ships one.
- **LIC-10** A CI guard fails if a campaign workspace or a Source enters the tool repository. It exempts the sample campaign's folder, which a deny-list scan of Golarion terms covers instead.

## What ships

- **LIC-11** Code only, plus the sample campaign. Never shipped: PF2e system pack data, Paizo books, PathfinderWiki GIS data or maps generated from it, purchased assets, official translations (pf2-fr texts fall under OGL + Paizo CUP and need the translators' or Black Book's permission), and the test corpus, including players' voices.
- **LIC-12** User-supplied content is read from the GM's own install or Sources at runtime. Purchased content is indexed by metadata by default; sending its content to a model requires an explicit opt-in ([#4](https://github.com/Hugo-Grellier/SecondChair/issues/4)).
- **LIC-13** The **sample campaign** is synthetic, in English, in an original setting with no Golarion names, deities or calendar. Official PF2e content appears only as bare English keys: no stat blocks, no rule text. It ships as material, never as a workspace ([#22](https://github.com/Hugo-Grellier/SecondChair/issues/22)).
- **LIC-14** Westerhold stays a private Source in v4.

## Foundry package constraints

- **LIC-15** Any open-source licence is acceptable for a Foundry package. The modules run only alongside a licensed Foundry and copy no more Foundry code than strictly needed.
- **LIC-16** The Foundry AI policy (2026-03-18) binds only packages in the official listing. v4 self-distributes, but the modules stay catalogue-compliant so a listing remains possible: "AI Tools" category, no AI-made prepared content shipped, an author attestation, and never an *automatic* injection of third-party content (other modules, purchased assets) into a model ([ADR 0010](../adr/0010-local-core-reached-by-the-gm-browser.md)).

## Going public

- **LIC-17** The repository goes public at spec hand-off, after a pass checking that no ticket or commit quotes Paizo content or player data.
- **LIC-17a** The pre-publication pass (settled in planning, 2026-10-19) is the first planning ticket, before any code. Its scope is every issue body and comment, every commit message and diff on every branch, and every file on every branch. Checklist:
  1. Paizo content: quoted rule text, stat blocks, Beginner Box text, PathfinderWiki or GIS data (bare English keys are fine, LIC-13);
  2. player data: real names, Discord handles, voice quotes, transcripts, speaker tables;
  3. restricted third-party text: official translations (LIC-11);
  4. personal or unrelated information: the owner's other work, notes, mail, personal absolute paths;
  5. secrets, by a scan of the full history;
  6. each non-main branch kept or deleted;
  7. preconditions: the licence files of ADR 0006 are present and the CLA bot is installed (LIC-03), since a public repository accepts pull requests.

  An agent runs the scan and writes a findings report. The GM rules on each finding. Fixes edit issue text, or rewrite history and force-push while the repository is still private. The GM makes the repository public personally.
