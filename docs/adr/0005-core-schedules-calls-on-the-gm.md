# The Core schedules every call on the GM; Surfaces only display

Interruptions are what the GM pays for delegation during a live session. The Director's Desk prototype (a throwaway, deleted before publication) showed that a Surface cannot lower their count: it can only hide noise or batch what it is given. So the Core gives every pending call (proposal, exception, ceiling refusal) a deadline: *now* when it blocks the current turn or scene, otherwise the next break. The GM can force a deadline to now or break per responsibility and moment in the delegation table. A call unanswered at its deadline takes its safe default (reject, no action) and is shown again at the break. An irreversible action never takes effect by default. Interruptions are measured at the Core, the same on the test bench and with any Surface.

Because irreversible approvals need an authenticated Surface (ADR 0003) and the GM sits in Foundry during play, v4 ships a minimal VTT Surface, the Director's Desk, in the Foundry connector: calls due now, approve/reject with reason, the active NPC's acting cue, the break pile. No tabs; the action log, staging and living world stay in conversation and the CLI.

## Considered Options

- **Conversation only**: rejected; every live disclosure would need a terminal round-trip, and action-log noise lands in the stream the GM reads.
- **Full tabbed desk (Now / Staging / Living world / Decisions)**: rejected for v4; the extra tabs serve between-session work, where conversation already suffices.
- **Deferral as a Surface choice**: rejected; it would make the interruption count depend on which Surface the GM uses.
