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
A GM function that can be delegated independently of the others: prep, memory, VTT operations, rules and combat, living world, NPCs, narrative direction, disclosure.
_Avoid_: role, agent, domain

**Disclosure**:
The responsibility of letting players see or hear something: publishing an entry, revealing a token, whispering, an NPC speaking in public.
_Avoid_: reveal, publish (as the responsibility's name)

**Delegation level**:
How much autonomy a responsibility is granted. One of four, shared by every responsibility: manual, propose, act-then-review, autonomous. It belongs to the responsibility, not to an agent.
_Avoid_: agent autonomy level

**Manual**:
The level where agents take no action for the responsibility; they only answer when asked.

**Propose**:
The level where agents draft and the GM approves each item before it takes effect.
_Avoid_: suggest, draft mode

**Act-then-review**:
The level where agents act at once, every action is logged and undoable, and the GM reviews afterwards.
_Avoid_: supervised, semi-autonomous

**Autonomous**:
The level where agents act and only surface exceptions to the GM.

**Moment**:
One of three fixed phases of play a profile applies to: prep, live session, between sessions.
_Avoid_: phase, mode

**Delegation profile**:
The set of delegation levels for every responsibility, valid for one moment.
_Avoid_: configuration, mode

**Delegation table**:
A campaign's three delegation profiles, one per moment: a level for every responsibility in every moment. Each campaign owns its own.
_Avoid_: settings, permissions

**Base profile**:
A ready-made delegation profile shipped with the tool (read, prep, play), used as a starting point to fill a column of the delegation table.
_Avoid_: preset, access level

**Ceiling**:
A maximum level the GM sets inside the VTT, enforced by the VTT connector regardless of the active profile.
_Avoid_: access level, permission

**Delegated action**:
One atomic act an agent performs under a responsibility; each is recorded as an entry in the action log.
_Avoid_: operation, command

**Action log**:
The single record of every delegated action, from which any reversible action can be undone individually.
_Avoid_: audit trail, history

**Irreversible action**:
A delegated action whose effect cannot be undone once it happens, such as a disclosure. Held at propose unless the GM lifts that limit for the responsibility.
_Avoid_: destructive action

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

## Agents

**Agent host**:
A general-purpose agent program (Claude Code, Codex) that runs the agents: it loads playbooks and acts on SecondChair only through its tool surface. SecondChair ships no agent loop of its own.
_Avoid_: orchestrator, runtime, client

**Agent**:
One session of an agent host doing delegated work. Agents are interchangeable: what an agent may do is decided per delegated action by its responsibility, never by which agent acts.
_Avoid_: combat agent, NPC agent (as roles with their own rights)

**Playbook**:
A written procedure an agent follows for one kind of work (prep a session, wrap a session, run the monsters), shared by every supported agent host.
_Avoid_: skill (outside host docs), prompt, command

**Job**:
A unit of work that needs a model, with an explicit contract: playbook, inputs, expected output, responsibility. The Core queues jobs; it does not run models itself.
_Avoid_: task, request

**Runner**:
The GM-configured way a queued job gets started in an agent host without the GM present. Without one, jobs wait until the GM starts them.
_Avoid_: worker, scheduler
