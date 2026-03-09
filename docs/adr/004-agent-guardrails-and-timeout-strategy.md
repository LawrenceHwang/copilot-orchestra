# ADR 004: Agent guardrails and timeout strategy

## Status
Accepted

## Context

In production we observed two failure modes in reviewer agents:

1. **Timeout before completion**: The orchestrator hit its 300 s `send_and_wait` limit while
   still actively calling tools. The SDK raised `TimeoutError: Timeout after 300.0s waiting for
   session.idle`, aborting the review.

2. **Rabbit-hole exploration**: Reviewer 3 (and occasionally the orchestrator) made 40+ tool
   calls on a single file, following dependency chains multiple levels deep, and timed out at
   the 600 s ceiling without producing output.

The original single-phase approach — one `send_and_wait` with a hard ceiling + a liveness
watchdog — only handles the "completely stuck" case. It has no mechanism to redirect an agent
that is actively (but unproductively) exploring.

Key SDK capability discovered: `CopilotSession.abort()` stops the current in-flight message
and leaves the session valid for new messages. `send_and_wait` can be called multiple times on
the same session object. This enables mid-run phase injection.

## Decision

### 1. Multi-phase timeout injection in `BaseAgent`

Replace the single-phase `send_and_wait` + watchdog with a three-phase approach in
`_run_with_phase_injection`:

| Phase | Boundary | Action on expiry |
|-------|----------|-----------------|
| 1 | 0 – 70% of total (0 – 420 s) | Normal execution |
| 2 | 70 – 90% (420 – 540 s) | `session.abort()` + inject soft warning: "start writing with what you have" |
| 3 | 90 – 100% (540 – 600 s) | `session.abort()` + inject hard trigger: "stop tool calls and write immediately" |

A liveness watchdog (`_phase_watchdog`) runs throughout all phases and cancels early if
no SDK event arrives for `AGENT_LIVENESS_TIMEOUT_S` (90 s). The watchdog returns one of:
`"phase"` (boundary reached), `"liveness"` (stuck), or `"total"` (hard ceiling).

### 2. Per-agent tool instances

`build_codebase_tools(codebase_path, start_time)` is called **once per agent** (not once per
review). This gives each agent isolated tracking state. Previously one shared tool list was
reused across the orchestrator and all three reviewers, making per-agent tracking impossible.

### 3. Tool-level guardrail annotations

Every tool result is annotated with:
- `⏱ Elapsed: Xs` — elapsed time since the agent started, enabling the model to self-regulate.
- Soft warning after 20 distinct files read via `read_file`.
- Nudge after 15 total tool calls across all tools.

These are appended as a `---` footer and do not interfere with the structured result content.

### 4. Reviewer prompt structured workflow

The reviewer prompt now enforces a 4-step reading workflow:

1. **ORIENT** — `list_directory` once if needed. Skip if file list is sufficient.
2. **READ ASSIGNED** — `read_file` on each assigned file. Primary job.
3. **PULL IN DEPENDENCIES** — at most 5 additional files, 1 import level deep. Gate:
   "will this change a specific finding?" If not, skip.
4. **WRITE** — immediately after reading assigned files. Do not delay.

Anti-patterns are listed explicitly in the prompt (same-file repeated grep, deep dependency
chains, reading unrelated files, waiting before writing).

### 5. Orchestrator timeout raised to 600 s

The orchestrator's `send_and_wait` timeout was raised from 300 s to 600 s to match the
reviewer ceiling. 300 s was too short for large or complex codebases.

## Rationale

- **Why phase injection over hard limits**: Hard tool-call caps prevent legitimate deep dives
  reviewers need to make accurate findings. Phase injection preserves the agent's freedom to
  explore while ensuring output is always produced within budget.
- **Why `abort()` + new `send_and_wait` turn**: The SDK supports multi-turn sessions. Injecting
  a new message after `abort()` gives the agent full context of what it has already read — the
  session history is preserved. It can write an informed (if incomplete) review rather than
  producing nothing.
- **Why elapsed time in tool results**: This is the cheapest self-regulation mechanism. The
  model reads its own tool outputs; an elapsed time signal lets it apply its own judgment about
  whether to continue or write. No orchestration changes needed.

## New constants

```python
# base.py
AGENT_TOTAL_TIMEOUT_S: float = 600.0
AGENT_LIVENESS_TIMEOUT_S: float = 90.0
WATCHDOG_POLL_S: float = 10.0
AGENT_SOFT_WARN_RATIO: float = 0.70   # 420 s
AGENT_HARD_WARN_RATIO: float = 0.90   # 540 s

# codebase.py
_TOOL_CALL_NUDGE_AT = 15
_FILE_READ_WARN_AT = 20
```

## New SSE event

`agent.phase_timeout` is published when a phase boundary is crossed and a warning prompt is
injected. Useful for observability and debugging runaway agents.

```json
{
  "type": "agent.phase_timeout",
  "review_id": "...",
  "agent": "reviewer_3",
  "phase": 0,
  "elapsed_s": 421
}
```

## Consequences

- An agent that would previously time out silently now produces a partial review at the 70%
  and 90% marks, which the synthesizer can incorporate.
- Phase transitions are logged as warnings and published as events, making runaway behaviour
  observable in the UI and logs.
- The synthesizer is intentionally excluded from this mechanism — it is a single-turn call
  with no tools; its timeout strategy is unchanged (300 s total, 60 s liveness).
- Calling `session.abort()` mid-phase cancels CLI-side processing. The session remains valid
  but the aborted turn's partial output is discarded. This is acceptable because the review
  text accumulates across phases via `result` — the final non-empty value is returned.
