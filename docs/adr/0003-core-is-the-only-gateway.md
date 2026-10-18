# The Core is the only gateway, and irreversible approvals need an authenticated GM

The Core runs as a single process (`secondchair serve`) and is the only MCP server agents see. System extensions and VTT connectors are Python packages loaded through entry points; they do not expose tools of their own but register them with the Core, each declaring its responsibility, whether it is a read or a delegated action, and whether it is reversible. The Core wraps every delegated action (level check against the active delegation profile, action log entry, undo), so "the Core is the single authority" (delegation model) holds by construction rather than by agent discipline: no agent ever talks to the VTT directly.

Approvals at *propose* can come from any Surface, but the Core cannot tell a faithful agent relay from an invented one. So an approval relayed by an agent in conversation is accepted for reversible actions only, logged as "via agent" with the GM's quoted words. Irreversible actions (disclosure, a public line) and decisions that enter canon at the "GM decision" authority rank require a Surface where the GM is authenticated: the CLI in an interactive terminal, or the VTT panel as the VTT's GM user. An agent may prepare such an approval; the GM confirms it in one gesture. The v3 tool was bypassed exactly here (a forged GM answer passed validation).

## Considered Options

- **Each block runs its own MCP server**: rejected; delegation would have to be re-enforced in every server.
- **Trust every agent relay**: rejected; canon and disclosure would rest on the agent's honesty.
- **Authenticated Surface for every approval**: rejected; it kills the conversational flow where an undo already exists.
