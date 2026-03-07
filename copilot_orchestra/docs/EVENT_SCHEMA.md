# SSE Event Schema — Copilot Orchestra

All events are delivered as Server-Sent Events (SSE) on `GET /api/events/{review_id}`.

## Envelope

Every event is a JSON object with at minimum:

```json
{
  "type": "<event-type>",
  "review_id": "<uuid>",
  "ts": 1700000000000
}
```

Additional fields depend on `type`.

## Event Types

`agent` values: `orchestrator` | `reviewer_1` | `reviewer_2` | `reviewer_3` | `synthesizer`

### `review.started`

Emitted immediately when the orchestration pipeline begins.

```json
{
  "type": "review.started",
  "review_id": "abc123",
  "ts": 1700000000000,
  "request": {
    "task": "Review for security and performance",
    "codebase_path": "/path/to/repo",
    "scope": "full",
    "model_preset": "balanced"
  }
}
```

### `agent.started`

Emitted when an agent session begins, before any streaming output.

```json
{
  "type": "agent.started",
  "review_id": "abc123",
  "ts": 1700000000050,
  "agent": "reviewer_1",
  "model": "claude-sonnet-4-6"
}
```

### `agent.stream`

A streaming text chunk from an agent. Emitted for every `assistant.message_delta`.

```json
{
  "type": "agent.stream",
  "review_id": "abc123",
  "ts": 1700000000100,
  "agent": "reviewer_1",
  "content": "Looking at the authentication module..."
}
```

### `agent.thinking`

Emitted during the silent reasoning phase of deep-thinking models
(`ASSISTANT_REASONING` / `ASSISTANT_REASONING_DELTA` SDK events). Has no content —
its purpose is to reset the liveness watchdog so the agent is not considered stuck.

```json
{
  "type": "agent.thinking",
  "review_id": "abc123",
  "ts": 1700000000150,
  "agent": "reviewer_1"
}
```

### `agent.message`

The complete final message from an agent (after `ASSISTANT_MESSAGE` SDK event).

```json
{
  "type": "agent.message",
  "review_id": "abc123",
  "ts": 1700000000500,
  "agent": "reviewer_1",
  "content": "## Review\n\n### Critical Issues\n..."
}
```

### `agent.tool_call`

An agent invoked a tool.

```json
{
  "type": "agent.tool_call",
  "review_id": "abc123",
  "ts": 1700000000200,
  "agent": "reviewer_1",
  "tool_name": "read_file",
  "tool_call_id": "tc_xyz",
  "args": { "path": "src/auth.py" }
}
```

### `agent.tool_result`

A tool call completed.

```json
{
  "type": "agent.tool_result",
  "review_id": "abc123",
  "ts": 1700000000300,
  "agent": "reviewer_1",
  "tool_name": "read_file",
  "tool_call_id": "tc_xyz",
  "success": true
}
```

### `agent.done`

An agent has finished its work. `duration_ms` is wall-clock time from `agent.started`
to completion.

```json
{
  "type": "agent.done",
  "review_id": "abc123",
  "ts": 1700000001000,
  "agent": "reviewer_1",
  "duration_ms": 42300
}
```

### `agent.error`

An agent encountered an error. The pipeline continues with remaining agents.

```json
{
  "type": "agent.error",
  "review_id": "abc123",
  "ts": 1700000001000,
  "agent": "reviewer_2",
  "error": "No activity for 90s (elapsed 95s) — agent appears stuck"
}
```

### `model.selected`

The orchestrator selected a model for a reviewer (auto mode only). Emitted after the
orchestrator's `submit_plan` tool call, before the reviewers start.

```json
{
  "type": "model.selected",
  "review_id": "abc123",
  "ts": 1700000000050,
  "agent": "reviewer_1",
  "model": "claude-opus-4-6",
  "reason": "orchestrator auto-selection"
}
```

### `metrics.update`

Token and usage metrics update, emitted after each `assistant.usage` SDK event.

```json
{
  "type": "metrics.update",
  "review_id": "abc123",
  "ts": 1700000000800,
  "agent": "reviewer_1",
  "input_tokens": 4200,
  "output_tokens": 890,
  "cache_read_tokens": 1200,
  "cache_write_tokens": 300,
  "cost": 0.0042,
  "model": "claude-opus-4-6",
  "quota": {
    "used_requests": 12,
    "entitlement_requests": 300,
    "remaining_percentage": 96.0,
    "is_unlimited": false
  }
}
```

### `review.complete`

All agents have finished and the synthesizer has produced its report.

```json
{
  "type": "review.complete",
  "review_id": "abc123",
  "ts": 1700000005000,
  "synthesis": "# Code Review: Final Report\n\n## Verdict\n**Ship it**...",
  "duration_ms": 45000
}
```

Note: aggregate token/cost totals are not included in this event. Clients should
accumulate `metrics.update` events per agent to compute totals.

### `review.error`

The entire review pipeline failed (unrecoverable).

```json
{
  "type": "review.error",
  "review_id": "abc123",
  "ts": 1700000001000,
  "error": "CopilotClient failed to start: CLI not found"
}
```

### `stream.end`

Signals the SSE stream is closing. The client should close the EventSource.

```json
{
  "type": "stream.end",
  "review_id": "abc123",
  "ts": 1700000005001
}
```

## Heartbeat

A SSE comment line (`: heartbeat`) is sent every 30 seconds of inactivity to keep the
connection alive through proxies. This is not a JSON event.
