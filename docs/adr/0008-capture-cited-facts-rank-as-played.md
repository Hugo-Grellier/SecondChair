# Captured facts that cite the table rank as played; capture never calls on the GM during play

Session capture turns Sources (per-speaker voice transcripts, VTT observations, the GM's notes) into candidate facts, and the wrap consolidates them into canon between sessions. A candidate fact must quote its Source verbatim: no quote, no fact. A candidate whose quote is what was said or done at the table enters canon at the **played** rank, with the observation and quote as its origin, even though an agent extracted it. ADR 0007 keeps approved agent proposals at the agent-proposal rank because an agent wrote them; here the agent only transcribed play, so the quote, not the agent, is the authority. Anything an agent infers beyond the quote stays at the agent-proposal rank. Transcription itself is a CLI step outside the Core's MCP server (WhisperX by default, any engine producing the transcript format accepted), so the Core still calls no model (ADR 0001).

## Considered Options

- **Every captured fact at the agent-proposal rank**: rejected. Play would never outrank an agent's invention, and the GM would have to promote each played fact by hand.
- **Capture during the live session, validated from the break pile**: rejected for v4. It would add interruptions for no gain at the table. The transcript format accepts a live stream so a Foundry or Discord capture can be added later, still consolidated at the wrap.

## Consequences

- An extraction error now carries the played rank, so the wrap guards against it: the campaign vocabulary is fed to the transcription engine, a name close to a known entity becomes a blocking question, and a new entity is created only when it is attested twice or confirmed by the VTT.
- A contradiction with earlier play or a higher rank, and a blocking ambiguity, always become a call on the GM, whatever the memory delegation level. The agent never resolves a contradiction.
- Where Sources disagree, the VTT wins on mechanics, voice on narrative, and the GM's notes over the transcript.
- Raw audio and full transcripts stay Sources outside the campaign workspace; only the short quotes attached to facts are kept.
