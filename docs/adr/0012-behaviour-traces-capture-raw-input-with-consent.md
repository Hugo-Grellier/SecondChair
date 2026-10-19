# Behaviour traces capture raw input, locally and only with consent

Without behaviour traces, GM effort sees only interactions with SecondChair, so a baseline at manual measures nearly nothing while the GM does everything by hand in Foundry. SecondChair v4 therefore traces how the GM and players operate Foundry, in every moment. Each user opts in individually in the Foundry module. Consent is off by default, revocable, and filtered in that user's own client, so nothing is emitted before consent. The GM sees who consents but cannot consent for a player. Revoking stops capture and lets the player erase their past traces. Each consenting client records two streams on one clock. The first is semantic Foundry events: windows opened and closed with the document they show, rolls and cancelled roll dialogs, actions, targeting, token moves, turns, undo. The connector library emits these, and the system adapter adds system-specific ones such as strikes and spells. The second is raw input: clicks with position and target element, mouse movement sampled at about 10 Hz while the client has focus (tunable), wheel, drag and drop, and keys outside text fields. Inside a text field only the typing rhythm is kept, never a character. Raw traces are a Source kept on the GM's machine, outside the campaign workspace. Nothing leaves the machine. Deterministic detectors, from a closed list with thresholds tunable per campaign, turn traces into frictions that cite their trace span. GM frictions and manual acts count in GM effort. Player frictions feed table friction, which is never part of GM effort. The workspace keeps only the per-moment friction report.

## Considered Options

- **Semantic events only, no raw input**: rejected. What goes wrong in the VTT (rage clicks, clicks on nothing, stumbling input) lives between the semantic events.
- **Capture typed text**: rejected. It is fiction or private out-of-character talk, and a behaviour trace says nothing about the fiction.
- **GM only**: rejected. Players' struggles with Foundry are a friction worth measuring in their own right.
- **LLM-based friction detection**: rejected. Frictions must be reproducible and cheap. A playbook can read the deterministic report on demand and propose delegation table changes, at propose only.

## Consequences

- Player traces reach the Core through the GM's client (ADR 0010). With no GM client open they are lost, and the gap is noted in the report. There is no buffer in v4.
- The scripted GM produces no traces, so traces count only in real play and in S4 shadow mode, where the recorded session supplies the baseline GM effort. The existing Craig sessions have none, so S4 needs a new session recorded with the module.
- Raw traces never expire automatically in v4. They are deleted by the GM, or by the player for their own.
