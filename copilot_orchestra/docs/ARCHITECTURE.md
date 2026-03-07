# Architecture — Copilot Orchestra

## System Overview

```
Browser (React) / Machine Callers (curl, Python, CI)
    │  REST + SSE
    ▼
FastAPI Application
    │
    ├── POST /api/reviews        — start a review, returns review_id
    ├── GET  /api/reviews        — list all reviews (status, no synthesis)
    ├── GET  /api/reviews/{id}   — poll status + fetch synthesis result
    ├── GET  /api/events/{id}    — SSE stream for a review (real-time)
    ├── GET  /api/models         — list available Copilot models
    └── GET  /api/health         — liveness check
    │
    ▼
Orchestration Core  (pure Python, no FastAPI dependency)
    │
    ├── ModelRouter              — resolves model per agent role
    ├── EventBus                 — asyncio.Queue fan-out to SSE listeners
    ├── ReviewStore              — in-memory review state (enables polling)
    ├── SessionManager           — owns the single CopilotClient
    └── Orchestrator             — runs the full review pipeline
         │
         ├── OrchestratorAgent         — reads codebase, submits ReviewPlan
         ├── ReviewerAgent (reviewer_1) ──┐
         ├── ReviewerAgent (reviewer_2) ──┤  run in parallel; identical assignment
         ├── ReviewerAgent (reviewer_3) ──┘
         └── SynthesizerAgent          — consumes all three review texts
    │
    ▼
github-copilot-sdk  (JSON-RPC over stdio to Copilot CLI)
```

## Component Responsibilities

### ModelRouter

Single source of truth for model selection. Priority chain:

```
User Override  >  Orchestrator Choice  >  Config Preset  >  Hardcoded Default
```

- Presets: `balanced`, `economy`, `performance`, `auto`
- In `auto` mode, the orchestrator includes a `suggested_models` dict in its `ReviewPlan`
  JSON (via the `submit_plan` tool). The pipeline then calls
  `router.set_orchestrator_choice(role, model)` for each suggestion. These choices are
  lower priority than user overrides.
- Stateless per review — a new `ModelRouter` instance is created per `ReviewRequest`.

### ReviewStore

```python
ReviewStore
  create(review_id, task, codebase_path, scope, model_preset) → ReviewState
  get(review_id) → ReviewState | None
  list_all() → list[ReviewState]          # newest first
  set_complete(review_id, synthesis, duration_ms)
  set_error(review_id, error)
```

In-memory store that enables the polling pattern for machine callers.
`run_review()` calls `set_complete` / `set_error` at the end of the pipeline.
The store is created in FastAPI `lifespan` and injected via `get_review_store` dependency.
State is lost on server restart (in-memory only; swap `ReviewStore` for a persistent
backend if durability is required).

### EventBus

```python
EventBus
  subscribe(review_id) → asyncio.Queue   # SSE handler calls this
  publish(review_id, event: dict)        # agents call this
  unsubscribe(review_id, queue)          # SSE handler cleanup
```

Fan-out: multiple SSE connections can subscribe to the same `review_id`.
All agent sessions share one `EventBus` instance (app singleton).
A `{"type": "stream.end"}` sentinel closes the SSE stream.

### SessionManager

Owns one `CopilotClient` per application lifetime (started in FastAPI `lifespan`).
All Copilot sessions for all reviews are created through this single client.
This matches how the SDK is designed (one CLI process, many sessions).

BYOK support: if `BYOK_PROVIDER_TYPE` + `BYOK_API_KEY` are set, a `ProviderConfig` is
injected into every `create_session` call.

### Orchestrator

The top-level review pipeline:

```
1. publish review.started
2. build codebase tools (path-safe, root = request.codebase_path)
3. run orchestrator agent → ReviewPlan (via submit_plan tool call)
   - ReviewPlan assigns the SAME files + focus to all three reviewers
   - If orchestrator fails to submit a plan, a fallback plan is used
     (empty files list, task description as focus)
4. if auto mode: apply orchestrator model choices to ModelRouter
   → publish model.selected events per reviewer role
5. asyncio.gather(reviewer_1, reviewer_2, reviewer_3)
6. run synthesizer agent(all three review texts)
7. publish review.complete (includes synthesis text + duration_ms)
8. publish stream.end  (SSE closes)
```

Errors in individual reviewer agents are caught, published as `agent.error` events,
and the pipeline continues with available results (best-effort synthesis).
Unrecoverable pipeline errors are published as `review.error`.

### Agents

**Reviewer agents** (`ReviewerAgent`) each wrap a `CopilotSession`. All three reviewers use
an identical multi-dimensional system prompt covering Security, Correctness, Maintainability,
Readability, and Performance. They receive the same files and focus from the orchestrator so
their outputs can be directly compared by the synthesizer.

**Orchestrator** is implemented inline in `orchestrator.py` (not a `BaseAgent` subclass)
because it uses a custom `submit_plan` tool that captures the `ReviewPlan`.

**Synthesizer** (`SynthesizerAgent`) receives the three review texts (not file paths) and
produces the final report. It has no file tools — it is a single-turn call.

Session creation pattern (reviewer agents):

```python
session = await session_manager.create_session({
    "model": model_router.get_model(role),
    "tools": [read_file, list_directory, grep_codebase, git_diff, git_diff_file],
    "system_message": {"mode": "replace", "content": REVIEWER_SYSTEM_PROMPT},
    "streaming": True,
})
agent = ReviewerAgent(role=role, session=session, event_bus=event_bus,
                      review_id=review_id, model=model)
result = await agent.run(plan.files, plan.focus)
```

The orchestrator additionally sets `"working_directory": request.codebase_path` in its
session config so relative tool paths resolve correctly.

All five agents publish identical event sets: `agent.started` (with `model`),
`agent.stream` (text deltas), `agent.tool_call`, `agent.tool_result`, `metrics.update`
(tokens + cost from `ASSISTANT_USAGE`), and `agent.done` (with `duration_ms`).

#### Timeout / Watchdog

`BaseAgent` uses a **hybrid timeout** strategy:

| Constant | Value | Purpose |
|----------|-------|---------|
| `AGENT_TOTAL_TIMEOUT_S` | 600 s | Hard ceiling for reviewer agents |
| `AGENT_LIVENESS_TIMEOUT_S` | 90 s | Cancel if no SDK event for this long |
| `SYNTH_TOTAL_TIMEOUT_S` | 300 s | Hard ceiling for synthesizer |
| `SYNTH_LIVENESS_TIMEOUT_S` | 60 s | Synthesizer liveness |
| `WATCHDOG_POLL_S` | 10 s | How often the watchdog checks |

Any incoming SDK event (token, tool call, even `agent.thinking` from a reasoning model)
resets the liveness clock. A `TimeoutError` is caught and published as `agent.error`;
the pipeline continues with the remaining reviewers.

### Codebase Tools

Five tools registered on every agent session (orchestrator gets all five plus `submit_plan`;
synthesizer gets none — it is a single-turn call):

| Tool | Parameters | Notes |
| ---- | ---------- | ----- |
| `read_file` | `path: str` | 1 MB cap; path validated against allowed root |
| `list_directory` | `path: str`, `max_depth: int (1-5)` | git-aware (respects `.gitignore`); 300-entry cap with truncation notice |
| `grep_codebase` | `pattern: str`, `glob: str`, `max_results: int` | rg → git grep → Python fallback; 20 KB output cap |
| `git_diff` | `path: str`, `base: str` | full repo diff; 50 KB cap; base ref validated |
| `git_diff_file` | `path: str`, `file: str`, `base: str` | single-file diff; `file` param path-validated |

Allowed roots are set per-review to `[request.codebase_path]`. No other paths accessible.

#### Large-repo strategy

`list_directory` uses `git ls-files --cached --others --exclude-standard` when inside a git
repo, so `.gitignore` is respected automatically. Non-git fallback skips `_SKIP_DIRS`
(`node_modules`, `__pycache__`, `dist`, `build`, `.venv`, `vendor`, etc.). Both paths enforce
a 300-entry cap and append a truncation notice mentioning `grep_codebase` when hit.

`grep_codebase` enables content-based file discovery, which the orchestrator uses instead of
browsing directories on large repos. Tool call order is: `rg` (fastest, `.gitignore`-aware) →
`git grep` → pure-Python fallback.

## Data Flow

### ReviewPlan

The orchestrator calls `submit_plan` with a `ReviewPlan` JSON object:

```python
class AgentPlan(BaseModel):
    files: list[str]   # file paths to review (5-15 recommended)
    focus: str         # what to focus on (derived from the review task)

class ReviewPlan(BaseModel):
    reviewer_1: AgentPlan    # all three get identical assignments
    reviewer_2: AgentPlan
    reviewer_3: AgentPlan
    rationale: str           # orchestrator's explanation
    suggested_models: dict[str, str] | None  # auto mode only
```

All three `AgentPlan` objects receive the same `files` and `focus`. The three-way
independent review exists so the synthesizer can triangulate findings.

### Starting a Review

```
POST /api/reviews
  body: { task, codebase_path, scope, model_preset, model_overrides }
  → validates codebase_path exists and is a directory
  → validates codebase_path is absolute
  → review_store.create(review_id, ...)   ← registered immediately as "running"
  → creates ModelRouter from request preset + overrides
  → generates review_id (UUID4)
  → spawns asyncio background task: run_review(review_id, request, ..., review_store)
  → returns { review_id, status: "started", sse_url: "/api/events/{review_id}" }

Option A — Machine polling:
  GET /api/reviews/{review_id}   (repeat until status != "running")
  → review_store.get(review_id) → ReviewState
  → returns full status + synthesis when complete

Option B — Browser / TUI streaming:
  Client opens EventSource("/api/events/{review_id}")
  → SSE stream created, queue subscribed to EventBus
  → events flow until stream.end sentinel
```

### SSE Event Flow

```
Agent session fires event
  → on() handler in agent code
  → translates to OrchestraEvent dict
  → event_bus.publish(review_id, event)
  → all subscribed queues receive event
  → SSE handler yields "data: {json}\n\n"
  → browser receives event, updates UI
```

## SSE Event Schema

See [EVENT_SCHEMA.md](EVENT_SCHEMA.md) for the full event schema.

Key events:

| Type | When | Key Fields |
|------|------|------------|
| `review.started` | Review begins | `review_id`, `request` |
| `agent.started` | Agent session begins | `agent`, `model` |
| `agent.stream` | Streaming text chunk | `agent`, `content` |
| `agent.thinking` | Deep-thinking reasoning phase | `agent` |
| `agent.message` | Complete final message | `agent`, `content` |
| `agent.tool_call` | Tool invoked | `agent`, `tool_name`, `tool_call_id`, `args` |
| `agent.tool_result` | Tool completed | `agent`, `tool_name`, `tool_call_id`, `success` |
| `agent.done` | Agent finished | `agent`, `duration_ms` |
| `agent.error` | Agent failed | `agent`, `error` |
| `model.selected` | Auto mode selection | `agent`, `model`, `reason` |
| `metrics.update` | Token/usage update | `agent`, `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost`, `quota` |
| `review.complete` | All done | `synthesis`, `duration_ms` |
| `review.error` | Pipeline failed (unrecoverable) | `error` |
| `stream.end` | SSE closes | — |

`agent` values: `orchestrator` \| `reviewer_1` \| `reviewer_2` \| `reviewer_3` \| `synthesizer`

## Machine Integration

See [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) for the complete machine API user guide
including curl, Python, async, and GitHub Actions examples.

The two integration patterns:

| Pattern   | Transport                                          | Best for                      |
|-----------|----------------------------------------------------|-------------------------------|
| Polling   | `POST /api/reviews` + `GET /api/reviews/{id}`      | CI/CD, batch, shell scripts   |
| Streaming | `POST /api/reviews` + `GET /api/events/{id}` (SSE) | Browsers, TUIs, dashboards    |

## Extensibility: TUI

The `backend/orchestration/` package has zero FastAPI imports. A future TUI (`tui/app.py`)
can import `SessionManager`, `EventBus`, `ModelRouter`, `ReviewStore`, and `run_review`
directly, subscribe to the `EventBus` with its own queue, and render events using Textual
or Rich.

## Security Architecture

1. **Path validation** (`tools/codebase.py`): every tool call resolves the path with
   `Path.resolve()` and checks it is `relative_to()` an allowed root. Symlinks that escape
   the root are blocked automatically.

2. **No shell expansion**: `git diff` and other subprocess calls use list-form args, never
   `shell=True`.

3. **No credential logging**: `structlog` processors strip any key named `*key*`, `*token*`,
   `*secret*`, `*password*` from log records.

4. **BYOK isolation**: API keys come from environment only. The `/api/reviews` request body
   has no `api_key` field — BYOK is server-side configuration only.

5. **File size limit**: `read_file` refuses files > 1 MB to prevent agent context overflow
   and accidental binary reads.

6. **Large-repo directory safety**: `list_directory` caps output at 300 entries and skips
   generated/vendor directories to prevent flooding agent context windows. The git-aware
   path (`git ls-files`) is preferred when available, as it enforces `.gitignore` at the
   source.

7. **grep pattern safety**: `grep_codebase` passes the user-supplied pattern as a subprocess
   list argument — never via shell interpolation — so arbitrary regex content is safe.

## Frontend: Usage Display

Three layers of usage visibility in the browser UI:

### MetricsBar (global)

Sits between the header and main content. Shows aggregated totals across all five agents:

- **IN / OUT / TOTAL** — cumulative token counts from all `metrics.update` events
- **EST. COST** — aggregate cost (shown when > 0)
- **PREMIUM** — quota consumption: `used_requests / entitlement_requests (X% left)` with a
  colour-coded bar (green → amber → red as quota decreases). "∞ unlimited" shown for
  unlimited entitlements.
- **Per-agent strip** — each agent's label with individual IN↑ OUT↓ tokens and cost.

### AgentUsageRow (per-agent panel)

Displayed below the tool-call badge row in each `AgentPanel` (including orchestrator in sidebar)
and in `SynthesisPanel`. Only rendered when token data is non-zero (idle panels stay clean).

- **Context window %** — colour bar (`input_tokens / 200_000 * 100`). Sky below 50 %, amber 50-80 %, red above 80 %.
- **IN** — `input_tokens` formatted (e.g. `12.3k`).
- **OUT** — `output_tokens` formatted.
- **Cost** — per-agent USD cost (shown when non-zero).

Context window size is hardcoded to 200K tokens — the context limit for all current Claude models
(Opus 4.6, Sonnet 4.6, Haiku 4.5). The constant `CONTEXT_WINDOW = 200_000` lives in
`AgentPanel.jsx` and `SynthesisPanel.jsx`.

### State wiring

`App.jsx` holds `metrics: { [agentRole]: { input_tokens, output_tokens, cost, quota } }` in
the `useReducer` store, updated by `METRICS_UPDATE` actions from `metrics.update` SSE events.
The metrics slice is passed down as the `metrics` prop to `AgentPanel` (for each reviewer role)
and `SynthesisPanel`.

## Technology Choices

See [adr/](adr/) for individual Architecture Decision Records.

| Concern | Choice | Reason |
|---------|--------|--------|
| Transport | SSE (not WebSocket) | Read-only server push; simpler, FastAPI native |
| Async | asyncio | SDK is async-first |
| Config | pydantic-settings | Type-safe, .env support, secret masking |
| Logging | structlog | Structured JSON, easy processor pipeline |
| Testing | pytest + pytest-asyncio | Standard, asyncio support |
| Frontend | React + Vite | Fast DX, component model fits agent panels |
| Styling | Tailwind CSS | Rapid UI without design system overhead |
