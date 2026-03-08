# ADR 001: Use SSE instead of WebSocket for real-time streaming

## Status
Accepted

## Context
The web UI needs real-time updates from agent sessions. Two primary options: Server-Sent Events
(SSE) or WebSocket.

## Decision
Use SSE (`text/event-stream`) via FastAPI's `StreamingResponse`.

## Rationale
- **Read-only push**: The browser only receives events; it never sends data on the stream.
  SSE is designed exactly for this pattern.
- **Simplicity**: No upgrade handshake, no connection state management, built-in reconnection
  via `EventSource` browser API.
- **FastAPI native**: `StreamingResponse` with an async generator works out of the box.
- **TUI compatible**: A TUI can subscribe to the same `EventBus` directly (asyncio queue),
  bypassing SSE entirely. No WebSocket client needed in the TUI.
- **Proxy friendly**: SSE works through standard HTTP proxies. WebSocket needs proxy support
  and often requires special configuration.

## Consequences
- The browser cannot send events back on the same connection. All control actions (start,
  abort) use standard REST POST endpoints.
- Each SSE connection holds an open HTTP connection. For a local single-user tool this is
  fine. For multi-user production use, consider a message broker.
