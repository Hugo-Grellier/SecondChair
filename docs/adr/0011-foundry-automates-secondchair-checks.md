# Foundry automates the rules; SecondChair checks outcomes against their own trace

SecondChair v4 does not implement PF2e. The PF2e system and whatever automation modules the GM installs (PF2e Visioner, PF2e Toolbelt, others) automate the rules inside Foundry. Agents act only for the GM's creatures, never for a PC: in encounters they drive what the system exposes in code (strikes, system actions, spells with their resource, heightening and variants, saves of GM-controlled targets, damage, conditions, including damage applied to PCs as a consequence). The adapter creates self-effects and area Regions itself, and tracks one reaction per round for each GM creature so that agents can fire Reactive Strike-style reactions on a closed list of triggers. Spells with a variable cost and no overlay, every other reaction, and every PC choice stay manual. Understanding goes further than acting and covers every mode of play: the adapter enriches observations with each outcome's trace (roll breakdown, DC, damage instances and IWR applied, conditions before and after), and the System extension runs a rules check on each one for internal consistency. A failed check is a discrepancy, a call on the GM under rules and combat, held for the break by default. The adapter targets one Foundry and system major pair at a time (v14 and pf2e 8.x), because the system publishes no API contract.

## Considered Options

- **Recompute outcomes from the character and the full rules**: rejected. It would mean reimplementing PF2e and chasing every system release. A real calculation is added only when a specific check needs one.
- **Agents act in exploration and downtime too**: rejected for v4. There, SecondChair only checks and computes for prep.
- **Agents act for PCs or roll their saves**: rejected. PC choices and rolls belong to the players.
- **Support v13 (7.x) and v14 (8.x) side by side**: rejected. Without an API contract the cost doubles for no player benefit.

## Consequences

- Checks run in Python on observations, so the test bench replays them from traces (S3, S4) without Foundry.
- A discrepancy is not attributed to a module, because Foundry does not record which module made an update. The observation keeps the user and any module flags.
- Whether to build on a third-party monster-control module, and how house rules become visible to checks, is left to a later decision.
