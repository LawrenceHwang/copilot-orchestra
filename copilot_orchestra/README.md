# Copilot Orchestra

A multi-agent AI code review platform built on the [GitHub Copilot SDK](https://github.com/github/copilot-sdk).
Five Copilot sessions run in parallel to deliver Architecture, Backend, and Frontend reviews
simultaneously, with a Synthesizer that unifies all findings into one report.

Real-time streaming, live token/context/premium-request metrics (per-agent context window %,
IN/OUT tokens, estimated cost via premium request pricing, and quota consumed), and a pluggable Model Router make this a showcase
of what the SDK enables beyond the CLI.

Context-window telemetry is model-aware: the frontend resolves each agent's context limit from
`GET /api/models` (`capabilities.limits.max_context_window_tokens`) and computes `CTX%` against
that limit. If a model limit is unavailable, the UI falls back to 200K for display continuity.
Usage rows are initialized when each agent starts, so all five agents always show a context row,
including runs where a provider omits `assistant.usage` events.
The UI renders this explicitly as `CTX <percent>% of <window>` (for example `CTX 8.0% of 128k`).
Per-agent labels in the top metrics strip are deterministic and role-ordered:
`orchestrator`, `reviewer_1`, `reviewer_2`, `reviewer_3`, `synthesizer`.
Reviewer labels in that strip mirror the same random `<action>-<animal>` names shown on the three reviewer cards,
so the header and panels always match for faster scanning.

Recent UI accessibility tuning also raised contrast for secondary metadata text (timers, status chips,
badge labels, and usage-row details) in both light and dark themes.

The main content area arranges all five agents in a clear top-to-bottom pipeline:
Orchestrator (full-width) → 3 Reviewer columns → Synthesizer (full-width).
Every agent panel includes an expand icon (placed alongside Copy in the header action group)
that expands it into a centered overlay for comfortable reading; clicking outside or the
close icon returns it to inline size.

> **Note on context window values:** `max_context_window_tokens` is the raw model limit from the
> GitHub Copilot model catalog — it represents the full context window capacity of the model.
> VS Code's "Context Usage" widget shows a *smaller* number (the effective token budget) because
> VS Code internally subtracts a reserved output buffer (roughly 24%). Both values are accurate for
> their purpose: the Orchestra uses the full catalog limit as the CTX% denominator, which is the
> correct denominator for measuring how much of the model's window is occupied.

```
┌─ Web UI (React + Vite) ───────────────────────────────────┐
│  Task Input │ Model Router │ Metrics Bar                   │
│  ┌────────────────────────────────────────────────────────┐│
│  │                   Orchestrator                        ││
│  └────────────────────────────────────────────────────────┘│
│  ┌────────────┐ ┌─────────┐ ┌──────────┐                  │
│  │Architecture│ │ Backend │ │ Frontend │  ← 3 reviewers   │
│  └────────────┘ └─────────┘ └──────────┘                  │
│  ┌────────────────────────────────────────────────────────┐│
│  │                  Synthesis Report                     ││
│  └────────────────────────────────────────────────────────┘│
│  Each panel has a ⤢ maximize button for expanded viewing  │
└───────────────────────── SSE ─────────────────────────────┘
                           │
┌─ FastAPI ─────────────────────────────────────────────────┐
│  POST /api/reviews   GET /api/events/{id}   GET /api/models│
└───────────────────────────────────────────────────────────┘
                           │
┌─ Orchestration Core (UI-agnostic) ────────────────────────┐
│  ModelRouter  │  SessionManager  │  EventBus               │
│  Orchestrator → Architecture + Backend + Frontend (∥)     │
│  → Synthesizer                                            │
└──────────────────── Copilot SDK ──────────────────────────┘
```

## Prerequisites

- Python 3.13+ with [uv](https://docs.astral.sh/uv/)
- Node.js 20+ with npm
- GitHub Copilot CLI installed and authenticated (`copilot auth status`)
- OR a BYOK API key (see [BYOK Configuration](#byok-configuration))

## Quick Start

```bash
# Clone and enter the project
cd copilot_orchestra

# Install Python dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env as needed (defaults work if Copilot CLI is authenticated)

# Start backend
uv run uvicorn backend.main:app --reload --port 8000

# In another terminal, start frontend
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

## BYOK Configuration

To use your own API key instead of GitHub Copilot auth, set these in `.env`:

```env
BYOK_PROVIDER_TYPE=anthropic          # openai | anthropic | azure
BYOK_API_KEY=sk-ant-...
BYOK_BASE_URL=                        # optional; uses provider default
```

## Project Structure

```
copilot_orchestra/
├── SPEC.md                     # Product specification
├── docs/
│   ├── ARCHITECTURE.md         # System architecture
│   ├── API_SPEC.yaml           # OpenAPI 3.0 spec
│   ├── EVENT_SCHEMA.md         # SSE event schema reference
│   └── adr/                    # Architecture Decision Records
├── backend/
│   ├── main.py                 # FastAPI entry point
│   ├── config.py               # Settings via pydantic-settings
│   ├── logging_config.py       # Structured logging setup
│   ├── api/                    # HTTP layer (routes, schemas, dependencies)
│   ├── orchestration/          # UI-agnostic orchestration core
│   │   ├── model_router.py     # Model selection logic
│   │   ├── event_bus.py        # asyncio fan-out event bus
│   │   ├── session_manager.py  # CopilotClient lifecycle
│   │   ├── orchestrator.py     # Top-level review flow
│   │   └── agents/             # One module per agent role
│   └── tools/
│       └── codebase.py         # File-system tools (path-safe)
├── tests/
│   ├── unit/                   # Fast, no CLI dependency
│   └── integration/            # Requires running CLI (skipped by default)
└── frontend/
    └── src/
        ├── components/         # AgentPanel, MetricsBar, etc.
        └── hooks/useSSE.js     # EventSource hook
```

## Running Tests

```bash
# Unit tests only (fast, no CLI required)
uv run pytest tests/unit -v

# All tests including integration (requires Copilot CLI)
uv run pytest -v -m "not integration"

# With coverage
uv run pytest tests/unit --cov=backend --cov-report=term-missing
```

## Model Presets

| Preset | Orchestrator | Reviewer 1 | Reviewer 2 | Reviewer 3 | Synthesizer |
|--------|-------------|------------|------------|------------|-------------|
| balanced | sonnet | sonnet | sonnet | sonnet | sonnet |
| economy | haiku | haiku | haiku | haiku | haiku |
| performance | opus | opus | opus | opus | opus |
| free | discovered 0x model | discovered 0x model | discovered 0x model | discovered 0x model | discovered 0x model |
| auto | sonnet | *orch picks* | *orch picks* | *orch picks* | *orch picks* |

The `balanced` preset uses `claude-sonnet-4-6` for all roles (hardcoded defaults in
`model_router.py`). Per-role balanced defaults can be configured via environment variables
(`DEFAULT_ORCHESTRATOR_MODEL`, `DEFAULT_SECURITY_MODEL`, etc.) in `config.py`, but they
require wiring into the `ModelRouter` constructor via `default_models`.

Individual models can be overridden per-role in the UI regardless of preset.

`free` preset behavior:

- Uses SDK model discovery (`list_models`) to find models with `billing.multiplier == 0.0`
- Selects only those 0x models (no hardcoded model IDs)
- Fails fast if no free models are available for the current account

## Cost Model

**Copilot SDK mode** (default): Cost is estimated from premium requests. Each model turn
consumes `billing.multiplier` premium requests (e.g. 1.0× for most models, 0.0× for free
tier). The UI shows `EST. COST = total_premium_requests × $0.04 USD`. This matches
GitHub Copilot's billing model where each premium request costs $0.04.

**BYOK mode**: No dollar cost is displayed. The UI shows token counts (IN/OUT/TOTAL) and a
note: *"Cost: see vendor pricing for token usage"*. Users can calculate cost by applying
their vendor's per-token rates to the reported token counts.

The backend emits a `turns` counter (incremented per `ASSISTANT_USAGE` SDK event) instead
of a dollar cost. The frontend resolves each model's `billing_multiplier` from
`GET /api/models` and computes `premium_requests = turns × billing_multiplier` per agent.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full system design.

## Security

- File access is restricted to explicitly registered root paths only
- Path traversal is blocked via `Path.resolve()` + relative-to validation
- No credentials are logged
- BYOK keys are read from environment only, never from request bodies
- See [Security Rule 0](SPEC.md#non-functional) in the spec

## Tool Path Compatibility

To improve reliability across different model families, codebase tools accept both:

- Absolute paths (for example `/Users/me/repo/src/app.py`)
- Review-root-relative paths (for example `src/app.py`)

Additionally, path-bearing tools like `list_directory` and `git_diff` default to the
review root when `path` is omitted. This reduces tool invocation errors from models
that provide partial arguments while preserving the same path-safety guarantees.
