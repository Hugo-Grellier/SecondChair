# Consented live speech feeds a short-lived, GM-only context window; capture still consolidates only at the wrap

Status: accepted 2026-10-21 ([#189](https://github.com/Hugo-Grellier/SecondChair/issues/189), epic [#187](https://github.com/Hugo-Grellier/SecondChair/issues/187))

**Amends [ADR 0008](0008-capture-cited-facts-rank-as-played.md) (its rejected option "capture during the live session") and the row "Live capture and consolidation during play" of [11-out-of-scope.md](../spec/11-out-of-scope.md).** ADR 0008 keeps capture out of play: transcripts are produced offline after the session (CAP-01), consolidated at the wrap, and nothing calls on the GM during play. The live director ([live-director.md](../research/live-director.md)) would be better informed by what the table just said. [ADR 0019](0019-post-v4-live-assistance-and-world-horizon.md) (accepted) sequences this amendment last of the live work, once the director is useful with no microphone, and gives it the strictest review (R2: privacy, Sources). The design is [speech-fusion.md](../research/speech-fusion.md).

We decide that **consented, per-speaker live transcript segments may feed an in-memory, GM-only context window during play, which the director reads and nothing else; capture still produces no candidate fact, no canon write and no call during play, and the wrap re-transcribes the recorded tracks offline as today**.

1. **Consent per participant, per session.** Off by default. Each participant (the GM included) opts in from their own Foundry client at Start session; nothing is remembered silently from a previous session. This is ADR 0012's shape (per user, revocable, filtered in the user's own client, the GM cannot consent for a player) plus a session scope. Revoking from one's own client stops that track within one segment.
2. **No consent, untouched track.** A non-consenting participant's stream is **never opened**, not opened and then discarded. Per-speaker tracks only (CAP-02); no mixed-room capture, so single-track diarization stays out.
3. **Visible status.** While any track is live, every client shows an indicator naming whose tracks are open and whether the engine is local or remote. A remote engine is used only by machine configuration, named per campaign.
4. **GM aside.** A hold-to-mute key on the GM's track keeps private comments out of the window.
5. **The window.** In memory, in the Core process, GM-only, with a TTL (initially, revised by MET-05a: 10 minutes). It holds `(source id, track, t0, t1, text, confidence)` per segment, keyed by `(track, t0)` so a reconnect does not duplicate; a gap stays a visible hole. It is **never written to the workspace**, the action log or `.secondchair/`, and it is gone when `serve` stops.
6. **Reference, not admission.** A card may cite a fragment by its locator. Nothing in the window becomes a candidate fact, a canon write, a `played` rank or a call during play. Audience content still cites fact ids only (CAN-16), so a fragment can never be voiced as a cited fact.
7. **The wrap is unchanged.** It re-transcribes the recorded tracks offline (WhisperX) and consolidates as ADR 0008 says. The live text is discarded, so a live recognition error never reaches canon. Raw audio and full transcripts stay Sources outside the workspace (CAP-15).

The six invariants of ADR 0019 hold: the window advances no plot and writes no canon (1); it adds no call, and what it feeds is shown only through the director's pulls and ADR 0020's cues (2); consent is item 1 (3); no fictional state moves, and transcription is a step outside the Core's MCP server, so the Core calls no model (4); with speech off the director runs on observations alone and the Desk says speech is off (5); leaks and narrative direction stay 0 (6).

## Decisions

The GM's calls on #189, accepted 2026-10-21 on PR #220.

- **(a) Consent scope.** Per participant and per session, asked at Start session. A standing "always yes" is not offered.
- **(b) TTL.** 10 minutes, configurable per campaign downwards only.
- **(c) Audio source.** Either a Discord per-user voice receiver or Foundry's A/V in the GM client, chosen by the first leaf (S4); both open a stream only for a consenting track.
- **(d) Remote engine.** Allowed only by machine configuration, named in the status indicator; never a campaign default.

## Considered Options

- **Keep ADR 0008 as is**: kept until the director has measured value without a microphone (ADR 0019 step 4).
- **Live capture of candidate facts, validated at the break**: rejected, as in ADR 0008. It adds interruptions, and live recognition errors would carry the played rank.
- **Write the live window to `.secondchair/` for crash recovery**: rejected. It would create a second, unreviewed transcript store inside the workspace boundary; the recorded audio already covers recovery.
- **Open every track and filter non-consenting voices downstream**: rejected. Fail-safe means nothing to leak.
- **One mixed room track with diarization**: rejected. It cannot exclude a non-consenting voice.

## Consequences

- ADR 0008's rejected option is replaced by this window; spec 11's row becomes "Live consolidation during play; single-track diarization". CAP entries gain the window's rules; TRC-01's consent shape gains the session scope for speech.
- New pieces (leaves S2–S8): per-session consent and indicator in the Foundry connector, a streaming transcription adapter emitting the transcript format's segments, per-user audio ingest, the in-memory window with TTL, clock alignment, the aside key.
- **Test plan.** Fail-safe tests: no consent opens no stream (asserted at the ingest, not after); revoke mid-session stops the track within one segment; a reconnect replays without duplicates; the aside key keeps a GM comment out; a fragment cannot be passed to `check_audience_content` as a cited fact; no file under the workspace or `.secondchair/` changes while the window is fed; the window is empty after TTL and after `serve` stops; the wrap's candidates are identical with the window on or off on the same recordings. Bench: segment-to-window latency p95 ≤ 2 s on the reference GPU; word error on campaign names against the S3 gold first hour; leaks and narrative direction 0 on S4 with speech on.

## GM answers (2026-10-21)

1. **Partial consent.** Consenting tracks run while others decline; each track opens on its own participant's consent. Unanimity is not required, since one refusal blocking the whole table would put pressure on the one who refuses. Item 2 already keeps a declining track unopened.
2. **GM consent.** Required each session, like every participant: one opt-in at Start session, nothing remembered from a previous session.
3. **Audio source.** Discord per-user receive comes first; Foundry A/V follows. This narrows proposed answer (c). The first leaf (S4) must therefore cover: the bot token is a secret under the [security policy](../policies/security.md) and never enters the workspace; voice receive must work with Discord's end-to-end voice encryption; the bot subscribes only to consenting users' streams, so a declining user's audio is never received (item 2), not received and dropped.
4. **Player access.** The window is GM-only without exception. A player sees the status indicator and can revoke, but reads no fragment, their own included.
