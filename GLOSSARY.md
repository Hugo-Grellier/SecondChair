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

**Deadline**:
When a pending call on the GM (proposal, exception, ceiling refusal) must be answered: *now* if it blocks the current turn or scene, otherwise the next break. Set by the Core; the delegation table can force it to now or break per responsibility and moment.
_Avoid_: priority, urgency

**Break**:
A point where held calls are shown to the GM: a pause the GM signals, or the end of the moment.
_Avoid_: pause (as the term), checkpoint

**Safe default**:
What happens to a call left unanswered at its deadline: a proposal is rejected, an exception takes no action; it is logged and shown again at the break. An irreversible action never takes effect by default.
_Avoid_: fallback, timeout behaviour

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

**System adapter**:
The part of a VTT connector that drives one game system inside that VTT (strikes, conditions, turn context). Optional: without it the connector stays generic.
_Avoid_: submodule, plugin, system module

**Surface**:
A way for the GM to interact with SecondChair: conversation, CLI, the Director's Desk, later a GUI. A Surface only displays; what reaches the GM and when is decided by the Core.
_Avoid_: UI, frontend, client

**Director's Desk**:
The minimal Surface inside the VTT, opened as the VTT's GM user: the calls due now, approve or reject with a rejection reason, the active NPC's acting cue, and the pile held for the break.
_Avoid_: dashboard, GM screen, panel (as the name)

**Acting cue**:
What the GM needs to voice an NPC right now: goal, what it knows and does not know, a line in the GM's language.
_Avoid_: NPC card, prompt

## Inputs

**Source**:
A document the user supplies and the tool only reads, never ships: rulebooks, a previous campaign bible, session recordings, VTT exports.
_Avoid_: corpus, import, data

**Observation**:
A timestamped record, captured from the VTT, of live mechanical state or of what happened at the table. Never canon by itself; it becomes canon only through memory.
_Avoid_: fact, event (when meaning canon), log

## Authority

**Canon**:
What is true in the campaign's fiction, held by the Core. Ranked by authority: played, then GM decision, then cited official source, then agent proposal.
_Avoid_: lore, truth (as the store's name)

**Decision**:
A creative call by the GM, recorded with the GM's own words. Outranks everything except what was played.
_Avoid_: ruling, choice

**Desired state**:
What the Core asks the VTT to look like after prep (a scene, its tokens, lights, loot). Realised by reconciliation, which keeps what was played and what the GM retouched.
_Avoid_: export, sync

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

## Measurement

**GM effort**:
The GM's share of the work in a moment: every GM interaction (approval, rejection, edit, undo, answer to an exception), counted and timed.
_Avoid_: prep time, GM time (as wall-clock time)

**Interruption**:
Anything that calls for the GM's attention during a live session without the GM asking for it: a pending proposal, a surfaced exception, a ceiling refusal shown before the break. A call held until the break is not an interruption.
_Avoid_: prompt, notification

**Rejection reason**:
The short reason, picked from a closed list (contradiction, rules, tone, other), that the GM attaches when rejecting or undoing a delegated action.
_Avoid_: comment, feedback

**Gold set**:
Expected results for a scenario, written by hand once (facts a session should yield, answers to probes), against which every later run is scored without a human.
_Avoid_: ground truth, fixture, expected output

**Probe**:
A question with a known answer from a gold set, put to agents to check continuity.
_Avoid_: test question, quiz

**Baseline**:
A scenario's measurements with every responsibility at manual, against which the gains of delegation are stated.
_Avoid_: reference run, control

**Drift ratio**:
The share of narrative decisions initiated by agents rather than by the GM, watched for a rise rather than held to a target.
_Avoid_: creative freedom score

**Test bench**:
The set of replayable scenarios, each scored automatically against its gold set, used to measure SecondChair without the GM present.
_Avoid_: test suite, benchmark, eval

**Scenario**:
One replayable run of the test bench: a starting state, the Sources fed in, a moment, and a gold set to score against.
_Avoid_: test case, fixture

**Scripted GM**:
The stand-in for the GM on the test bench, answering proposals and exceptions from the gold set.
_Avoid_: simulated GM, mock GM

**Shadow mode**:
Replaying a real session's traces while agents act on a copy of the world, so their actions can be compared with what the GM actually did without changing what happened.
_Avoid_: dry run, simulation

**Agreement rate**:
In shadow mode, the share of agent actions that match what the GM actually did.
_Avoid_: accuracy

**Runner configuration**:
The agent host, model and effort a runner uses to start a job.
_Avoid_: model settings, profile
