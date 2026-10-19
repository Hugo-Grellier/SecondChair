# The Core runs locally, and the GM's browser connects to it

SecondChair v4 is a plain Python install (`uv tool install secondchair`, one extra per building block) with no Docker image. A campaign is served by one long-running `secondchair serve <workspace>` on the GM's machine, one active campaign at a time. Agents reach it over MCP Streamable HTTP on 127.0.0.1, with no stdio mode, because several agents (the GM's session, the runners) and the Foundry module must share one Core over one workspace. Foundry never needs to be reachable from the Core. The Foundry module, running in the active GM's browser client, opens a WebSocket to the loopback Core and authenticates with a token the Core generates and keeps in the machine configuration (mode 0600), as in v3. This works the same when Foundry is hosted remotely (The Forge, a homelab), because the browser is the bridge. The price is that the Core sees and acts on Foundry only while a GM client is open, in prep as well as in play. Without one, VTT actions fail cleanly and the desired state waits for reconciliation.

## Considered Options

- **Docker / Compose**: rejected for v4. The agent hosts and WhisperX's GPU live on the GM's machine, and a container only adds friction (workspace mounts, networking, GPU passthrough). It can be added later without changing anything else.
- **Core dialling Foundry (a server-side Foundry connection or a headless GM client)**: rejected. Foundry modules run in the client, and a remote Foundry is often unreachable from the GM's machine.
- **stdio MCP as in v3**: rejected. Each host session would start its own Core on the same workspace.
- **Remote or hosted Core**: deferred, not excluded. `serve` already speaks HTTP and WebSocket, so hosting it means binding beyond the loopback and authenticating the MCP endpoint, with no change to the contracts. A hosted service (such as LoreForge) is a separate effort, open to dual licensing under the CLA (ADR 0006).

## Consequences

- The loopback MCP endpoint is unauthenticated: any local process can call it. That is acceptable because irreversible approvals require an authenticated Surface (ADR 0003).
- The handshake checks the protocol version and that the Foundry world matches the one declared in the workspace, and refuses a mismatch.
- Firefox asks once per site before a page can open a loopback WebSocket, and Chrome may follow. The install docs say so.
- The campaign workspace is the full export: `workspace.yaml` carries the schema version, the derived index lives in an ignored `.secondchair/`, and `secondchair check` rebuilds everything from the directory alone. An older schema blocks `serve` until `secondchair upgrade` migrates it in place as a reviewable diff, and a newer one is refused.
