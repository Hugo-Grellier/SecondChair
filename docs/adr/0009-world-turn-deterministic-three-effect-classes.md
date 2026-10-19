# The world-turn is a deterministic Core step, never live, and splits its effects into three classes

The living world advances only through the world-turn: a deterministic Core computation over the fictional interval since its cursor, scheduling the due ticks, agenda steps and deadlines of fronts and situations, each an occurrence with a key used only once. Fictional time moves only through the wrap or a GM gesture, so the world-turn runs between sessions or in prep, never during a live session. Creative work (settling an `unless` condition, proposing consequences) is a job the world-turn queues, since the Core calls no model (ADR 0001). Its effects fall into three classes, and the class, not the agent, decides which responsibility governs them:

1. **Rule effects**, which the GM already wrote (a tick with no condition, a dated or threshold agenda step, the expiry of a situation the party has not engaged), apply at the living world's delegation level and keep the rank of the GM decision that wrote the rule.
2. **Derived consequences** (an NPC moving along its agenda, knowledge spreading to NPCs and factions, an `unless` settled by citing fact ids) apply at the living world's level, at the agent-proposal rank.
3. **New narrative** (a new front or situation, a changed agenda, the deadline of a situation the party is engaged in, the death or exit of a named NPC) belongs to narrative direction, capped at propose in v4.

The living world never discloses: anything reaching the party goes through disclosure.

## Considered Options

- **World-turn during the live session**: rejected for v4. It would add interruptions and let the world move under the GM's feet mid-scene.
- **A single living-world class at one delegation level**: rejected. Either the GM approves every scheduled tick they already wrote, or an agent may invent fronts and kill NPCs at act-then-review.
- **Simulating factions as agents**: rejected for v4. A faction acts through the fronts it carries.

## Consequences

- An occurrence that contradicts a fact at the played rank is never applied, even a rule effect: it becomes a call on the GM (reschedule, reject or retcon), and by default it stays queued.
- An unsettled `unless` is put to the GM at the next break; left unanswered, the tick does not happen and stays queued.
- Undoing an effect undoes its cascade and returns the keys to the queue; once the moment is frozen, only a correction or a retcon changes it.
- Only the front's carrier and the named participants know an offscreen event; anyone else learns it through a derived consequence.
- The v3 contracts carry over as Core unit tests: anchored rates, pause without catch-up, grouped catch-up beyond six ticks, rescheduling through a linked key, a late-accepted effect dated at its original date.
