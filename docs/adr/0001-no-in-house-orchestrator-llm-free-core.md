# No in-house orchestrator; the Core never calls a model

SecondChair v4 ships no agent loop of its own: general-purpose agent hosts (Claude Code and Codex first-class, any MCP host best effort) run the agents, load the playbooks (Agent Skills format) and reach the Core only through its MCP and CLI surface, which never assumes a specific host. The Core itself calls no LLM: work that needs a model is a job with an explicit contract, queued by the Core and started by a GM-configured runner (or by the GM when none is configured). We chose this because the value of SecondChair is delegation and GM-validated canon, which no open project covers, not the agent loop, which the hosts already provide; it keeps the Core deterministic, testable and free of API keys or hidden cost. The price is a dependency on a host subscription and on host behaviour changing between versions.

## Considered Options

- **In-house loop (LangGraph + LiteLLM, BYOK, local models)**: rejected for v4, large scope with no value of its own. It remains possible later as an additional Surface calling the same tools.
- **LLM client inside the Core** for background work (capture consolidation, summaries): rejected for v4. Embeddings were first rejected too, then admitted by the amendment below. The job contract is the seam: an in-Core model client can later become a second executor of the same jobs without changing anything else.

## Consequences

- LangGraph and LiteLLM are not in the v4 stack.
- Local models are available only through a host that supports them.
- The action log records which agent acted, for traceability only; agents hold no rights of their own.

## Amendment (2026-10-20): the Core may compute embeddings on the GM's Ollama

The reference library (spec 12) indexes whole rulebook collections (several hundred PDFs) for cited retrieval. Embedding is a deterministic function of text, needs no host session, and is needed at indexing and at every query, so routing it through a job would make every search wait on an agent host. The Core therefore calls an embedding model, and only that, on the GM's own Ollama server (`ollama_url`, loopback by default; `semantic_model`, `qwen3-embedding:0.6b` by default). It still calls no generative model: extraction of entities, relations or summaries from sources stays a job, and multi-hop reasoning over sources stays with the agent host, which chains `search_campaign_library` calls.

- Search and indexing fail clearly when Ollama or the model is missing; nothing falls back to a hosted service.
- Source text sent for embedding reaches only the configured Ollama server, which the GM operates.
