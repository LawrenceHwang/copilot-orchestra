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
         ├── ReviewerAgent (reviewer_1: Architecture) ──┐
         ├── ReviewerAgent (reviewer_2: Backend)       ──┤  run in parallel; identical file assignment
         ├── ReviewerAgent (reviewer_3: Frontend)      ──┘
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

- Presets: `balanced`, `economy`, `performance`, `free`, `auto`
- `free` preset is resolved dynamically from SDK model metadata: models with
  `billing.multiplier == 0.0` and enabled policy state are eligible.
  No model IDs are hardcoded.
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

### Frontend Label Mapping And Order

The frontend keeps reviewer identity stable per session using a generated display-name array:

- `reviewer_1 -> reviewerNames[0]`
- `reviewer_2 -> reviewerNames[1]`
- `reviewer_3 -> reviewerNames[2]`

This mapping is used consistently in both reviewer cards and the top metrics strip.
Per-agent metrics are rendered in deterministic role order:

`orchestrator -> reviewer_1 -> reviewer_2 -> reviewer_3 -> synthesizer`

This prevents display drift from object insertion order and keeps header telemetry aligned
with the left-to-right reviewer card layout.

### Frontend Layout & Typography

**Base font size:** `html { font-size: 112.5% }` in `index.css` scales all rem-based Tailwind
values (text, spacing, padding) proportionally. The initial value was 125% (matching the
preferred browser zoom level), but after review the UI felt slightly large; it was trimmed to
112.5% (90% of 125%) for better information density while preserving proportional scaling.

**Sidebar:** Default width 360px, drag range 260–560px (enforced in `App.jsx`). These values
are set in raw pixels because the drag handler uses `clientX` pixel offsets. When changing
the root font size, sidebar pixel dimensions must be recalibrated proportionally (288px at
100% → 360px at 125% → 324px at 112.5%).

**Inline label wrapping:** Short text labels inside flex rows (e.g. scope radio buttons) must
use `whitespace-nowrap` to prevent multi-word labels like "Full repo" from breaking across
lines at larger font sizes.

**Contrast:** Operational metadata (timers, status text, usage labels, and badge text) uses
contrast-safe tokens in both themes. Dark mode must avoid low-contrast `gray-500` style
combinations on dark surfaces for primary runtime signals.

**Orchestrator panel minimum height:** The orchestrator rarely produces `streamText` — it
coordinates through tool calls and `submit_plan`, not free-form output. Without a minimum height
its `flex-1 min-h-0` content area collapses to near-zero, leaving only the header and tool
badges visible. All `AgentPanel` instances carry `min-h-[140px]` on their outer div (applied
when not in expanded/overlay mode). This is small enough to be unnoticeable on reviewer and
synthesis panels (which are tall due to content) while keeping the orchestrator visually
proportionate in the pipeline layout.

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

**Reviewer agents** (`ReviewerAgent`) each wrap a `CopilotSession`. All three share a common
engineering baseline (15+ years industry experience, long-term thinking, tradeoff judgement,
no-hedging behavioral contract), but each receives a **distinct specialization** via its own
system prompt from `SYSTEM_PROMPTS[role]` in `agents/reviewer.py`:

| Role | Specialization | Key focus areas |
| --- | --- | --- |
| `reviewer_1` | Architecture | Service boundaries, coupling, API contracts, scalability ceilings, infrastructure implications, long-term tradeoffs |
| `reviewer_2` | Backend Engineering | Databases, caching, APIs, reliability, security at service boundaries, observability, backend performance |
| `reviewer_3` | Frontend & UX | Accessibility (WCAG), i18n/l10n, UX correctness, render performance, component architecture, visual correctness |

All three receive the same files and focus from the orchestrator so the synthesizer can
triangulate findings across three expert lenses.

**Agent prompt behavioral contract (all agents):** No hedging. No "would you like me to…".
No end-of-response offers or questions. Agents use the tools, form judgment, and write the
output. This is enforced explicitly in every system prompt.

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
(tokens + turns from `ASSISTANT_USAGE`), and `agent.done` (with `duration_ms`).

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

**Critical:** Every `send_and_wait` call **must** pass an explicit `timeout` parameter:

```python
await self._session.send_and_wait({"prompt": prompt}, timeout=AGENT_TOTAL_TIMEOUT_S)
```

Omitting `timeout` causes the SDK to fall back to its internal default (60 seconds), which
is far too short for the synthesizer (which processes three full reviews) and for deep-thinking
reviewer agents. The `SynthesizerAgent` overrides `run()` and must pass `timeout=SYNTH_TOTAL_TIMEOUT_S`
explicitly — it does not inherit the base class call. Always verify this whenever `run()` is
overridden in a subclass.

### Codebase Tools

Five tools registered on every agent session (orchestrator gets all five plus `submit_plan`;
synthesizer gets none — it is a single-turn call):

| Tool | Parameters | Notes |
| ---- | ---------- | ----- |
| `read_file` | `path: str` | 1 MB cap; `path` may be absolute or review-root-relative; validated against allowed root |
| `list_directory` | `path: str='.'`, `max_depth: int (1-5)` | git-aware (respects `.gitignore`); defaults `path` to review root; 300-entry cap with truncation notice |
| `grep_codebase` | `pattern: str`, `glob: str`, `max_results: int` | rg → git grep → Python fallback; 20 KB output cap |
| `git_diff` | `path: str='.'`, `base: str` | full repo diff; defaults `path` to review root; 50 KB cap; base ref validated |
| `git_diff_file` | `path: str='.'`, `file: str`, `base: str` | single-file diff; defaults `path` to review root; `file` may be absolute or root-relative and is path-validated |

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
| `metrics.update` | Token/usage update | `agent`, `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `turns`, `quota` |
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

### Cost Model

The cost estimation uses two distinct strategies depending on the connection mode:

- **Copilot SDK mode**: Cost is derived from premium requests. The backend emits a `turns`
  counter (incremented per `ASSISTANT_USAGE` SDK event). The frontend looks up each model's
  `billing_multiplier` from `GET /api/models` and computes
  `premium_requests = turns × billing_multiplier` per agent, then
  `est_cost = total_premium_requests × $0.04 USD`.
- **BYOK mode**: No dollar cost is shown. The UI displays token counts and a note directing
  users to check their vendor's pricing for the reported token usage.

The `byok_active` flag is provided by `GET /api/models` and stored as React state. It is
passed to `MetricsBar` to toggle between the two display strategies.

### Three layers of usage visibility in the browser UI

### MetricsBar (global)

Sits between the header and main content. Shows aggregated totals across all five agents:

- **IN / OUT / TOTAL** — cumulative token counts from all `metrics.update` events
- **EST. COST** — aggregate estimated cost computed as `premium_requests × $0.04` where each turn costs `billing.multiplier` premium requests (Copilot SDK mode only; hidden in BYOK mode). Shown when > 0.
- **PREMIUM** — quota consumption: `used_requests / entitlement_requests (X% left)` with a
  colour-coded bar (green → amber → red as quota decreases). "∞ unlimited" shown for
  unlimited entitlements.
- **Per-agent strip** — each agent's label with individual IN↑ OUT↓ tokens and per-agent cost.

### AgentUsageRow (per-agent panel)

Displayed below the tool-call badge row in each `AgentPanel` and in `SynthesisPanel`.
The orchestrator is rendered as a full-width `AgentPanel` in the main content area
(above the three reviewer columns), matching the same card design as all other agents.
Usage rows are rendered for every started agent, even before non-zero token usage,
so the operator always has a full per-agent telemetry strip.

### Panel Maximize / Expand

Every agent panel (orchestrator, 3 reviewers, synthesizer) includes an expand button
(SVG expand-arrows icon) co-located with the Copy button in header row 2. Clicking it
renders the panel as a fixed overlay (`z-50`, `80vh`, `max-w-4xl`) with a semi-transparent
backdrop. The expanded panel continues to receive and display streamed data. Clicking
outside the panel or clicking the close icon (SVG ×) returns it to its original inline
size. State is managed via a single `expandedPanel` string in `App.jsx` (one panel
expanded at a time).

- **Context window %** — colour bar (`input_tokens / context_window_tokens * 100`). Sky below
  50 %, amber 50-80 %, red above 80 %.
- **Context window label** — rendered as `CTX <percent>% of <window>` (for example
  `CTX 8.0% of 128k`) so operators can verify what denominator is being used.
- **IN** — `input_tokens` formatted (e.g. `12.3k`).
- **OUT** — `output_tokens` formatted.

`context_window_tokens` is resolved from the model catalog payload (`GET /api/models`,
`capabilities.limits.max_context_window_tokens`) when an agent starts or when a metrics event
includes a model id. If unavailable, the UI falls back to 200K to keep the display stable.

**Context window value source:** `max_context_window_tokens` from `/api/models` is the raw
model limit from the GitHub Copilot model catalog. This represents the full context window
capacity of the model. Note that VS Code's "Context Usage" widget displays a *smaller* value
(an internal effective budget after subtracting a reserved output buffer, approximately 24%).
The Orchestra uses the full catalog limit as the CTX% denominator — this is the correct
measure of actual window utilisation against the model's true capacity.

### State wiring

`App.jsx` holds `metrics: { [agentRole]: { input_tokens, output_tokens, turns, quota, model,
context_window_tokens } }` in the `useReducer` store.

- On `agent.started`, the reducer seeds the metrics entry with zeroed token/turns values and a
  model-derived `context_window_tokens`, ensuring visibility for all agents.
- On `metrics.update`, token/turns/quota values are merged while preserving already-known context
  limits if the event omits them.

**Dispatch pattern (important):** The `handleEvent` callback in `App.jsx` maps SSE event fields
to the reducer action with explicit named properties — it does **not** spread `...event` onto
the dispatch object. Spreading the raw SSE event would overwrite the reducer's `type:
"METRICS_UPDATE"` with the event's `type: "metrics.update"`, causing the reducer to fall
through to `default: return state` and silently drop all token/turns/quota updates. Any future
consumers of SSE events that dispatch to a reducer must apply the same explicit-mapping pattern.

**Streaming vs. final-message deduplication:** The Copilot SDK fires both `ASSISTANT_MESSAGE_DELTA`
(streaming chunks → `agent.stream`) and `ASSISTANT_MESSAGE` (complete text → `agent.message`)
for the same turn. The frontend must not dispatch both to the same agent, or the full text will
appear duplicated at the end of the stream. This is solved with `streamedAgentsRef` (a `useRef
Set`) in `App.jsx`: the `agent.stream` handler registers the agent in the set; the `agent.message`
handler only dispatches if the agent is absent from the set (i.e. no streaming events arrived —
non-streaming model fallback). The ref is cleared on each new review start.

**Stale-closure hazard:** `handleEvent` is `useCallback([models])`, so any `state` captured
inside the closure reflects the initial render value, not the current state. Never use
`state.agents[x].streamText` (or any other live state field) inside this callback — it will
always read the initial empty string. Use refs for cross-event coordination instead.

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
