# ADR 002: One CopilotClient, many sessions

## Status
Accepted

## Context
Each Copilot agent (orchestrator, security, performance, readability, synthesizer) needs its
own independent conversation history. A `CopilotClient` spawns a CLI process. Sessions are
created through a client.

Options:
1. One `CopilotClient` per agent (5 CLI processes per review)
2. One `CopilotClient` per review (1 CLI process per review, 5 sessions)
3. One global `CopilotClient` (1 CLI process total, N sessions across all reviews)

## Decision
One global `CopilotClient` shared across all reviews, created in FastAPI `lifespan`.

## Rationale
- **Resource efficiency**: Spawning a CLI process is expensive. One process handles all
  sessions concurrently — this is how the SDK is designed.
- **SDK design**: The SDK docs show `CopilotClient` as the long-lived connection and
  `CopilotSession` as the per-conversation unit. We align with this.
- **Simplicity**: `SessionManager` is a thin wrapper with `start()`/`stop()` in the
  FastAPI lifespan, no pooling logic needed.

## Consequences
- If the CLI process crashes, all in-flight reviews fail. The SDK's `auto_restart=True`
  default mitigates this.
- Sessions from concurrent reviews share the same CLI process. The SDK handles session
  isolation at the protocol level.
