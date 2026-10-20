# Licensing

SecondChair is one repository holding artefacts under different licences ([ADR 0006](docs/adr/0006-agpl-core-apache-connector-cla.md), [08 — Licensing and repository split](docs/spec/08-licensing-repos.md)).

| Artefact | Licence | Licence file |
|---|---|---|
| Core, PF2e System extension, CLI, test-bench harness | AGPL-3.0 | [`LICENSE`](LICENSE) |
| Foundry modules `secondchair-foundry`, `secondchair-foundry-pf2e` | Apache-2.0 | `LICENSE` in each module's folder |
| Playbooks | Apache-2.0 | `LICENSE` in each package's `playbooks` folder |
| Sample campaign (material and its gold set) | CC BY 4.0 | [`sample-campaign/LICENSE`](sample-campaign/LICENSE) |

- Anything not listed above, including the documentation, is under the root [`LICENSE`](LICENSE) (AGPL-3.0).
- Each folder under another licence carries its own `LICENSE` file, added with the folder's first content. That file wins over the root one for everything inside the folder.
- Outside contributions are accepted only under the Contributor Licence Agreement, which a bot checks on every pull request (LIC-03).
- The repository ships no PF2e system data, Paizo text, official translations or other third-party content (LIC-11).
