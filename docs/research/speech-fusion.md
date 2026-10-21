# Consented live speech and Foundry event fusion

Research for [#189](https://github.com/Hugo-Grellier/SecondChair/issues/189), parent [#187](https://github.com/Hugo-Grellier/SecondChair/issues/187). Post-v4: it amends [ADR 0008](../adr/0008-capture-cited-facts-rank-as-played.md) and a row of [11-out-of-scope.md](../spec/11-out-of-scope.md), sequenced last of the live work by [ADR 0019](../adr/0019-post-v4-live-assistance-and-world-horizon.md) (proposed). No code.

## Goal and non-goals

Fresh, timestamped, **non-authoritative** context for the live director ([live-director.md](live-director.md)) from what the table says, aligned with Foundry observations. Not: live capture of facts, live consolidation, speaker guessing on a mixed track, anything a player did not consent to. The director must stay useful with no microphone.

## What exists

- Offline transcription: `secondchair transcribe` (`src/secondchair/transcribe.py`) runs WhisperX per speaker track with the campaign vocabulary as hotwords, writes the transcript format ([transcript.schema.json](../contracts/transcript.schema.json)), keeps audio and transcript as Sources outside the workspace, records only id and hash (CAP-01, CAP-15).
- The transcript format already "accepts a live stream of segments" (CAP-01, ADR 0008).
- Per-speaker tracks are required (CAP-02); the speaker table maps Discord user → player → PC and marks the GM.
- Consent model for behaviour traces (ADR 0012, TRC-01): opt-in per user, off by default, revocable, filtered in the user's own client, GM cannot consent for a player.
- Observations carry the event envelope (timestamp, scene, actor, kind, visibility) (ARC-16).

## Consent and privacy

| Rule | Why |
|---|---|
| Opt-in **per participant, per session**, off by default; asked at Start session, not remembered silently | A table changes week to week; ADR 0012 consent is per user but sessionless |
| A non-consenting participant's track is **never opened**, not opened-then-discarded | Fail-safe; nothing to leak |
| Per-speaker tracks only; no mixed-room capture | A mixed track cannot exclude a non-consenting voice (CAP-02 already) |
| Visible status for everyone: a Foundry indicator in every client while any track is live | No covert listening (#189, #198) |
| Revoke at any time from the participant's own client stops their track within one segment | Revocation must bind the next capture, not the next session |
| GM **aside**: a hold-to-mute key on the GM track | Private GM comments are the likeliest spoiler source |
| Local processing by default; a remote engine only by machine configuration, named per campaign, shown in the status | Off-device processing must be explicit (#189) |
| Live window held in memory with a TTL (default 10 min), never written to the workspace | The live text is a working view, not a Source of record |
| The recorded audio and the offline transcript keep today's rules (CAP-15) | No new retention class |

## Pipeline options (local first; to benchmark, not chosen)

| Option | Shape | Notes |
|---|---|---|
| WhisperX (current) | Batch, alignment, VAD | Stays the wrap's engine: most accurate, not streaming |
| faster-whisper with VAD chunking (e.g. whisper_streaming, WhisperLive) | Near-streaming, local-agreement commits | Same model family as the wrap; latency set by chunk length and GPU |
| whisper.cpp streaming | CPU/Metal friendly | The no-GPU fallback; smaller models, lower accuracy |
| Cache-aware streaming ASR (NeMo FastConformer / Parakeet class) | True streaming | Lowest latency on a GPU; multilingual coverage to check for the campaign language |
| Hosted streaming APIs | Remote | Optional, permissioned, off by default |

**Audio source.** Per-user streams come from a Discord voice-receive bot (the Craig recordings S3/S4 already use are per-user tracks) or Foundry's A/V (WebRTC or LiveKit) in the GM client. Either way the stream is opened by the participant's consent, never by the GM alone.

**Targets to measure.** Segment end → available in the live window p95 ≤ 2 s on the reference GPU; word error on campaign names (hotwords) against the S3 gold first hour; behaviour on overlap, music, gaps.

## Fusion with observations

- **Clock.** Every segment carries the GM machine's wall time and a monotonic time; the offset between them and each client's observation timestamps is measured at Start session and on reconnect. A segment is placed on the observation timeline by monotonic time; a jump is logged, never smoothed silently.
- **Reference, not admission.** The live window stores `(source id, track, t0, t1, text, confidence)`. Cards cite fragments by that locator; nothing becomes a candidate fact until the wrap.
- **Uncertainty stays.** Low-confidence or overlapping segments are marked; there is no speaker guessing because tracks are per speaker.
- **Duplicates and gaps.** Segments are keyed by `(track, t0)`; a reconnect replays without duplicating. A gap is a visible hole in the window.
- **Wrap.** The wrap re-transcribes the recorded tracks offline (WhisperX) and consolidates as today; the live text is discarded, so live ASR errors never reach canon.

## What must change in ADR 0008 (the amendment)

1. Replace the rejected option "capture during the live session" with: consented live segments may feed a GM-only, in-memory context window during play.
2. Keep: capture never calls on the GM during play; no candidate fact, no canon write, no `played` rank from live text; consolidation only at the wrap from the recorded Sources.
3. Add: per-participant, per-session consent with client-side filtering (ADR 0012 shape), visible status, revoke within one segment, GM aside.
4. Add: the window's TTL and that it is never written to the workspace; audience content still cites fact ids only (CAN-16), so a transcript fragment can never be voiced as a cited fact.
5. Spec 11: the row "Live capture and consolidation during play" becomes "Live consolidation during play" (capture into the live window allowed by this amendment); single-track diarization stays out.

## Proposed leaf issues

Risk as in [live-director.md](live-director.md#proposed-leaf-issues).

| # | Title | Scope | Risk | Deps |
|---|---|---|---|---|
| S1 | ADR: live context window | The ADR 0008 amendment above | R2 | ADR 0019 accepted |
| S2 | Per-session speech consent and status | Opt-in at Start session in each client, indicator in every client, revoke | R2 | S1 |
| S3 | Local streaming transcription adapter | One engine behind the transcript format's segment stream, hotwords from campaign vocabulary | R1 | S1 |
| S4 | Per-user audio ingest | Discord or Foundry A/V per-user streams, opened only for consenting tracks | R2 | S2 |
| S5 | Live window with TTL | In-memory, GM-only, fragment locators, never in the workspace | R2 | S3 |
| S6 | Clock alignment and replay measurement | Offset policy, segment latency and max context age on an S4 replay, reconnect and duplicate cases | R1 | S3 |
| S7 | GM aside key | Hold-to-mute on the GM track | R1 | S4 |
| S8 | Fail-safe tests | No consent, revoke mid-session, reconnect, duplicate delivery, accidental GM comment | R1 | S2–S5 |
| S9 | Engine and hardware survey | WER on campaign names and latency per option on the reference GPU and CPU | R0 | — |
