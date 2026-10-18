# SecondChair

A tool that lets a game master direct a campaign while AI agents carry out the work the GM delegates to them.

## Modes

**Augmented campaign director**:
The target mode: the GM keeps imagination, acting and creative calls; agents operate whatever is delegated.
_Avoid_: AI GM, copilot, assistant

**AI GM**:
The mode where narrative direction itself is delegated to an agent. Not a current goal.
_Avoid_: autonomous GM

## Delegation

**Responsibility**:
A GM function that can be delegated independently of the others (prep, memory, VTT operations, rules and combat, living world, NPCs, narrative direction).
_Avoid_: role, agent, domain

**Delegation level**:
How much autonomy a responsibility is granted, from manual to autonomous. It belongs to the responsibility, not to an agent.
_Avoid_: agent autonomy level

**Delegation profile**:
The set of delegation levels for every responsibility, valid for one moment (prep, live session, between sessions).
_Avoid_: configuration, mode

## Building blocks

**Core**:
The game-agnostic, VTT-agnostic heart: canon, fictional time, knowledge, delegation, proposed changes.
_Avoid_: engine, backend

**System extension**:
Everything specific to one game system: rules, calculations, reference data (PF2e first).
_Avoid_: plugin, module, adapter

**VTT connector**:
Everything specific to one virtual tabletop: reading, acting, capturing traces (Foundry first).
_Avoid_: bridge, module, adapter

**Surface**:
A way for the GM to interact with SecondChair: conversation, CLI, later a GUI or a VTT panel.
_Avoid_: UI, frontend, client
