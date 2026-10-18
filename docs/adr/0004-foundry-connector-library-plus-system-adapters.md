# The Foundry connector is a system-agnostic library module plus one adapter module per system

On the Foundry side the VTT connector ships as two kinds of Foundry package, following the bg3-hud-core pattern: `secondchair-foundry`, a system-agnostic library module (bridge to the Core, ceiling, idempotent write queue, durable capture, scene reconciliation, event envelope, VTT panel Surface, generic reads and actions on journals, scenes, tokens, doors, chat, playlists), and one system adapter module per game system (`secondchair-foundry-pf2e` first) that requires the library and registers through a hook to provide strikes, conditions, turn context, action costs and system event payloads. Code that drives the PF2e Foundry system has to run inside Foundry anyway, so it lives there rather than in the Python System extension, which stays VTT-agnostic (pure calculations, calendar, reference data). Without an adapter the library still works generically and refuses mechanical actions as failed actions. The Python half of the connector is single and system-agnostic; system payloads are typed by the System extension.

## Considered Options

- **System-specific JavaScript inside the Python System extension**: rejected; it ties the extension to one VTT.
- **A separate "system × VTT" building block**: rejected; the adapter module already is that, without a new concept in the Core.
