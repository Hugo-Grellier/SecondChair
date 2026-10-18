# Legal constraints for an open-source SecondChair

Research for issue #4 (map #1). Read on 2026-10-18 from primary sources, each linked inline.
**This is not legal advice.** Open uncertainties are listed at the end and marked **(uncertain)** in the text.

## TL;DR

- **The tool can be open source under any licence.** Foundry's package licence does not dictate one. The Foundry connector must only work alongside a licensed Foundry copy and copy no more Foundry code than it needs.
- **Foundry's AI policy binds only packages in the official listing.** A self-distributed connector is free of it. A listed one must sit in the "AI Tools" category, ship no AI-made prepared content, and never *automatically* feed the model content the author has no rights to, such as other installed modules or purchased maps.
- **Ship code, not content.** PF2e rules data, Paizo books, PathfinderWiki GIS data, purchased Foundry assets, the Westerhold campaign and the Craig recordings all stay **user-supplied** or user-fetched. Each one is gated by a licence that is non-commercial, has reserved material, or is a personal purchase, or it holds personal data.
- **Licences:** use Apache-2.0 for the connector (it runs inside proprietary Foundry). Core can be Apache-2.0 (recommended, given the audience and no SaaS) or AGPL-3.0 if blocking closed hosted forks matters. The two mix fine across the WebSocket boundary.

## 1. Foundry VTT licence for modules

Source: [Foundry VTT Software License, "Limited License for Package Development"](https://foundryvtt.com/article/license/) (EULA "Updated March 2, 2023").

- Licence holders "are granted license to develop Game Systems, Add-on Modules, and Worlds, referred to as 'packages'".
- "Publication of packages which reference or include software code and function in the absence of the base software is not permitted." and "Including portions of software code is only permitted to the extent strictly necessary for proper functioning of the package."
- "You may distribute these packages provided they are designed to be used only in conjunction with a licensed copy of the software." Selling is allowed for "package content which you have the rights to distribute".
- "You bear the sole responsibility to uphold intellectual property rights as required by copyright law."
- Packages are bound by the latest licence version whenever they are updated.
- The licence **names no required licence** for package code. The pf2e system itself is Apache-2.0 ([LICENSE](https://github.com/foundryvtt/pf2e/blob/master/LICENSE), [README §Licenses](https://github.com/foundryvtt/pf2e#licenses)).

**Implications.** The connector (today `bible-sync`) may be open source. It must not vendor Foundry client code beyond what it needs, and it is useless without Foundry by design. Core (MCP server, CLI, memory) is not a Foundry package, so this licence does not cover it. It must simply not embed Foundry code.

## 2. Foundry AI Content Policy (revised March 18, 2026)

Source: [AI Content Policy](https://foundryvtt.com/article/ai-policy/). Compliance deadline for existing listed packages: September 14, 2026.

**Scope: listing vs self-distribution (§1.2).** "This policy applies only to packages distributed through our official listing and marketplace." License holders "retain the right to create and distribute packages that do not comply with this policy, provided you do so through channels other than our official platforms". Self-published packages still follow the package licence (§1 above).

**Prepared vs improvised content (§3, §4, §5).**
- "Prepared content must be human-made." This covers text, images, audio and marketing that are "intentionally pre-created". AI may only do limited editing or post-processing.
- "Improvised Content is content generated at runtime in direct response to unpredictable prompts made by an end user during their session." It "is permitted for all content types", including "NPC generators, randomized game content, map builders".
- "it is not allowed for packages to provide runtime access to content that was pre-created via AI generation."
- Packages with runtime AI generation "must be categorized in an 'AI Tools' category" (§6.7).

**AI-assisted code (§4).**
- AI-written code is allowed if "Package authors must personally understand and be prepared to maintain all code". Authors attest to this at submission and may have to prove it "through commit history, design notes, or direct explanation".
- Runtime-generated code must be shown "in a readable format before execution" and confirmed explicitly by the user.
- Foundry client source may be given to AI coding tools "only ... for the specific purpose of Foundry VTT package development and not for the creation of any other work."
- Package descriptions on foundryvtt.com "must be human-written".

**Third-party content as AI context (§1.1).**
- "Authors may only provide materials to an AI model, whether as training data or as runtime context, for which they hold the copyright or have a license that permits such use. This applies equally to locally-run models and external services."
- "Packages must not be designed to automatically collect or inject context from sources the author does not have rights to — such as scraping content from other installed modules or assets."
- The policy says nothing about an end user choosing to supply their own content. Its stance on improvised content is "We do not police what users choose to generate at their own table." **(uncertain)** Whether a user-configured, opt-in context source counts as "designed to automatically collect" is not addressed.

**Implications for SecondChair.**

| Concern | Self-distributed connector | Listed connector |
|---|---|---|
| Policy applies | No (package licence only) | Yes |
| Category | n/a | "AI Tools" |
| Bundled AI-written text, images or sample campaign content | Allowed | **Forbidden** (prepared content) |
| Agent-driven prep written into the world (scenes, journals, NPC lines) | Allowed | Probably fine as improvised content made at the user's request. **(uncertain)** Prep made ahead of a session is "pre-created" in spirit, but the user creates it, not the author. |
| Reading the purchased asset index, other modules' compendia or journals into the LLM | Allowed by Foundry. Copyright and the asset's own EULA still apply. | **Forbidden if automatic.** Only an explicit user opt-in might pass. **(uncertain)** |
| AI-assisted code | Allowed | Allowed with an attestation. The owner must be able to explain every line. |
| Feeding Foundry client source to agents while building *core* | Not covered by Foundry | Policy restricts it to package development **(uncertain)** whether it reaches non-package code at all |

Recommendation: **self-distribute the connector first** (a manifest URL from GitHub releases), as `bible-sync` does today. Keep the connector code-only with no bundled content (`bible-sync` already is). If a listing becomes a goal, make every third-party context source an explicit, per-source, off-by-default user setting, and keep a human-written listing text.

## 3. PF2e rules and the Foundry PF2e system data

Sources: [ORC License (Paizo page)](https://paizo.com/orclicense); [Paizo licenses overview](https://paizo.com/licenses); [Community Use Policy](https://paizo.com/licenses/communityuse); pf2e repo [README §Licenses](https://github.com/foundryvtt/pf2e#licenses), [static/licenses/ORCLicense.md](https://github.com/foundryvtt/pf2e/blob/master/static/licenses/ORCLicense.md), [static/licenses/](https://github.com/foundryvtt/pf2e/tree/master/static/licenses).

- **ORC.** Licensed Material is "those expressions reasonably necessary to convey functional ideas and methods of operation of a game", meaning rules and statblocks. It is royalty-free and "irrevocable" once the notice is published. Reserved Material (trademarks, proper nouns, art, characters, settings, plots) is excluded. Reuse requires an ORC Notice, an attribution to each Licensor, and a Reserved Material statement. "Nothing in this license restricts the platform", and the plain-English summary names "AI" among allowed technologies.
- **Which books.** The pf2e system's ORC notice credits Beginner Box (Remastered), Player Core, GM Core, Player Core 2, NPC Core and others. Its Reserved Material clause lists "proper nouns (characters, deities, locations, etc. …), artworks, characters, dialogue, locations, organizations, plots, storylines, and trade dress" and "no Expressly Designated Licensed Material". Pre-remaster content stays under **OGL 1.0a** (`OpenGameLicense.md`).
- **The pf2e system itself.** Code is Apache-2.0. "Any Pathfinder Second Edition information used with permission granted by the license agreement between Paizo. Inc and Foundry Gaming LLC". "Game system information and mechanics are licensed under the Open Game License". Icons come under separate third-party EULAs (for example Rexard: no redistribution "other than as part of the relevant End Product"). So the compendium JSON is a mix: ORC/OGL mechanics, Paizo proper nouns used under a **private Paizo–Foundry agreement that does not extend to us**, and third-party art.
- **Community Use Policy.** The project must be free: "Your project must be free". It must be unofficial, carry the notice "is not published, endorsed, or specifically approved by Paizo", and Paizo "may deny use of its IP at any time". If Paizo deems you "operating as a business", you have no rights under it. It covers "software" in scope.
- **Paizo and AI.** Paizo's [AI statement](https://paizo.com/blog/paizo-and-artificial-intelligence) bars AI content from Paizo products and the Infinite marketplaces. It does **not** mention the CUP or tools. **(uncertain)** Whether Paizo would object to a CUP project that generates content with AI.

**Implications.**
- **Do not ship** the pf2e compendium data, Paizo book text, or any Golarion proper nouns as bundled data. The existing pattern holds: `bible pf2e sync` fetches a pf2e release into the user's machine, and `bible source ingest` reads the user's own PDFs. The user supplies these.
- The **PF2e System extension code** may ship under the project licence. It may hold mechanics-level logic (MAP, action costs, degrees of success) written from scratch. If it ever reproduces ORC rules text, add an ORC Notice plus attribution and keep proper nouns out.
- Using the word "Pathfinder" descriptively ("works with Pathfinder Second Edition") is nominative use. If the repo ships any Paizo IP under the CUP, it needs the CUP notice and must stay free. A no-Paizo-content repo needs neither, so prefer that.
- Short `[src:… p.N]` citations stored in a user's campaign are the user's affair, not the tool's.

## 4. PathfinderWiki GIS data

Sources: [pf-wikis/mapping LICENSE](https://github.com/pf-wikis/mapping/blob/main/LICENSE) (CC BY-NC-SA 4.0); [mapping README §Acknowledgments](https://github.com/pf-wikis/mapping#acknowledgments); [pf-wikis/mapping-data](https://github.com/pf-wikis/mapping-data) (GitHub reports **no licence file**); [PathfinderWiki:Copyrights](https://pathfinderwiki.com/wiki/PathfinderWiki:Copyrights).

- The mapping repo is **CC BY-NC-SA 4.0**. NonCommercial means "not primarily intended for or directed towards commercial advantage or monetary compensation". ShareAlike requires adaptations to carry "a Creative Commons license with the same License Elements".
- The README also says the project uses Paizo IP "under Paizo's Community Use Policy" and that "Paizo owns the copyright of these raster source map images". The geometry is volunteer georeferencing of those maps.
- The wiki says derivative works of Paizo IP "must also be released under the CUP and the appropriate game license".
- **(uncertain)** The `mapping-data` repo (the actual geometry, a Kart repo) has no licence file. It is presumably covered by the project's CC BY-NC-SA plus the CUP, but that is not stated there.

**Implications.** Do not commit GIS-derived maps or GeoJSON to the SecondChair repo. If they were committed, the repo would inherit NC-SA and the CUP for those files, which conflicts with Apache/AGPL freedoms such as commercial use. Ship the **importer code** (`gis extract`, `map import`). The user downloads the data and the importer writes the attribution header into the generated map, as v3 already does. A user's generated campaign map is an adaptation and stays under BY-NC-SA, which is fine for a private campaign.

## 5. Purchased content (maps, playlists, adventures) as AI context

Sources: Foundry AI policy §1.1 (above); Foundry package licence ("You bear the sole responsibility to uphold intellectual property rights").

- A purchase gives the buyer a personal-use licence under each vendor's EULA. The Foundry policy addresses only package authors. Whether a vendor EULA allows sending its text or images to a cloud LLM is **vendor-specific (uncertain)**. Most EULAs predate the question.
- Low-risk uses: metadata the user's own install exposes (scene name, wall and light counts, playlist names), used to *select and place* an asset; the asset itself never leaves the machine. Higher-risk uses: sending purchased adventure journal text or map images to a remote model.

**Implications.** Keep the asset index (`sources/foundry/assets.json`) user-generated and never committed. Default to metadata-only. Make "send asset content to the model" an explicit per-source opt-in that names the destination (local vs remote model). This posture is also what a future catalogue listing would need.

## 6. Apache-2.0 vs AGPL-3.0 for Core vs connector

Sources: [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0); [GNU AGPL v3 §13](https://www.gnu.org/licenses/agpl-3.0.html); [FSF licence list, Apache 2.0](https://www.gnu.org/licenses/license-list.html#apache2); [GPL FAQ: plug-ins](https://www.gnu.org/licenses/gpl-faq.html#GPLPlugins), [plug-in for a nonfree program](https://www.gnu.org/licenses/gpl-faq.html#GPLPluginsInNF); [choosealicense.com](https://choosealicense.com/licenses/).

- **Apache-2.0** is permissive with an explicit patent grant and patent-retaliation clause (§3). It requires NOTICE and change notices (§4) and grants no trademark rights (§6). FSF: "compatible with version 3 of the GNU GPL" (one-way: Apache code can go into (A)GPLv3 works, not the reverse) and not with GPLv2.
- **AGPL-3.0 §13**: a modified version "must prominently offer all users interacting with it remotely through a computer network … an opportunity to receive the Corresponding Source". It stops closed hosted forks, which matters only if someone runs SecondChair as a service. Hosted SaaS is out of scope for v4.
- **Connector inside Foundry.** The module is dynamically loaded into the proprietary Foundry client and calls its API. The GPL FAQ says dynamically linked plug-ins that "make function calls to each other and share data structures" form "a single combined program". For a GPL plug-in in a nonfree host, "combination … would violate the GPL" unless an exception is added. So an (A)GPL connector needs a linking exception or carries risk. **(uncertain)** It is unclear how this applies to interpreted JS loaded at runtime by the end user. Many Foundry modules ship GPL anyway, but Apache-2.0 or MIT avoids the question.
- **Core ↔ connector boundary.** They talk over a WebSocket as separate programs with message passing, which the GPL FAQ treats as separate works. So AGPL core plus Apache connector is coherent.

| | Apache-2.0 core | AGPL-3.0 core |
|---|---|---|
| Adoption by technical GMs, other VTT/system extensions | Easiest | Some companies avoid AGPL |
| Closed hosted forks | Allowed | Must publish source |
| Third-party extensions (System/VTT) | Any licence | Separate processes: any licence. In-process: AGPL-compatible. |
| Relicensing later | Easy | Needs every contributor's consent (or a CLA) |

**Recommendation.** Use **Apache-2.0 for the connector** in all cases. For core, use **Apache-2.0 by default**: the audience is technical GMs, SaaS is out of scope, it allows one licence across the repo, and it carries a patent grant. Choose AGPL-3.0 for core only if preventing a closed hosted SecondChair is a stated goal. That is a decision for the GM, not a legal requirement.

## 7. What may ship vs what stays user-supplied

| Ships in the open-source repo | Stays user-supplied, fetched or private |
|---|---|
| Core, System extension and connector code (project licence) | pf2e system compendium data (`bible pf2e sync` fetch) |
| Skills, prompts and docs written by the project | Paizo books and PDFs, and their extracted text (`bible source ingest`) |
| Mechanics logic written from scratch; ORC rules text only with ORC Notice and attribution, no proper nouns | Golarion proper nouns, lore, art, maps (Reserved Material, CUP) |
| GIS importer code | PathfinderWiki GIS data and maps generated from it (CC BY-NC-SA + CUP) |
| Asset-index *tool* (`asset-index.mjs`) | `assets.json`, purchased scenes, playlists, adventure journals |
| Synthetic test fixtures written for the project | Westerhold campaign, Beginner Box content, Craig session recordings |

**Test corpus.** Westerhold and the Beginner Box contain Paizo Reserved Material. The Craig FLACs are **voice recordings of identifiable players**, which is personal data under the GDPR. Never commit them. Use them only locally, with the players' consent, and build public tests from synthetic fixtures.

## Open uncertainties

1. Whether an explicit, user-configured context source escapes Foundry's "designed to automatically collect or inject" ban for a listed package.
2. Whether agent-prepared world content (prep done before a session at the GM's request) counts as "improvised" or as "prepared" under Foundry's policy.
3. Whether Paizo tolerates AI generation in a CUP project. The AI statement covers only Paizo products and Infinite.
4. The licence of `pf-wikis/mapping-data` (no licence file).
5. Whether purchased-content EULAs allow sending content to remote LLMs. This is vendor by vendor.
6. Whether GPL "combined program" doctrine applies to a JS module loaded by Foundry at runtime. It is avoided by choosing Apache-2.0 for the connector.
7. The Player Core and GM Core ORC notices were checked through the pf2e system's ORC notice, not the books' own legal pages.
