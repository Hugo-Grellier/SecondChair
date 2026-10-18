# No in-house orchestrator; the Core never calls a model

SecondChair v4 ships no agent loop of its own: general-purpose agent hosts (Claude Code and Codex first-class, any MCP host best effort) run the agents, load the playbooks (Agent Skills format) and reach the Core only through its MCP and CLI surface, which never assumes a specific host. The Core itself calls no LLM: work that needs a model is a job with an explicit contract, queued by the Core and started by a GM-configured runner (or by the GM when none is configured). We chose this because the value of SecondChair is delegation and GM-validated canon, which no open project covers, not the agent loop, which the hosts already provide; it keeps the Core deterministic, testable and free of API keys or hidden cost. The price is a dependency on a host subscription and on host behaviour changing between versions.

## Considered Options

- **In-house loop (LangGraph + LiteLLM, BYOK, local models)**: rejected for v4, large scope with no value of its own. It remains possible later as an additional Surface calling the same tools.
- **LLM client inside the Core** for background work (capture consolidation, summaries, embeddings): rejected for v4. The job contract is the seam: an in-Core model client can later become a second executor of the same jobs without changing anything else.

## Consequences

- LangGraph and LiteLLM are not in the v4 stack.
- Local models are available only through a host that supports them.
- The action log records which agent acted, for traceability only; agents hold no rights of their own.
