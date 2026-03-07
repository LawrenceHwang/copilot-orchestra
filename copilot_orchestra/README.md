# Copilot Orchestra

A multi-agent AI code review platform built on the [GitHub Copilot SDK](https://github.com/github/copilot-sdk).
Five Copilot sessions run in parallel to deliver Security, Performance, and Readability reviews
simultaneously, with a Synthesizer that unifies all findings into one report.

Real-time streaming, live token/context/premium-request metrics, and a pluggable Model Router
make this a showcase of what the SDK enables beyond the CLI.

```
┌─ Web UI (React + Vite) ───────────────────────────────────┐
│  Task Input │ Model Router │ Metrics Bar                   │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌────────────┐  │
│  │ Security │ │Performance│ │Readabilty│ │ Synthesis  │  │
│  └──────────┘ └───────────┘ └──────────┘ └────────────┘  │
└───────────────────────── SSE ─────────────────────────────┘
                           │
┌─ FastAPI ─────────────────────────────────────────────────┐
│  POST /api/reviews   GET /api/events/{id}   GET /api/models│
└───────────────────────────────────────────────────────────┘
                           │
┌─ Orchestration Core (UI-agnostic) ────────────────────────┐
│  ModelRouter  │  SessionManager  │  EventBus               │
│  Orchestrator → Security + Performance + Readability (∥)  │
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
| auto | sonnet | *orch picks* | *orch picks* | *orch picks* | *orch picks* |

The `balanced` preset uses `claude-sonnet-4-6` for all roles (hardcoded defaults in
`model_router.py`). Per-role balanced defaults can be configured via environment variables
(`DEFAULT_ORCHESTRATOR_MODEL`, `DEFAULT_SECURITY_MODEL`, etc.) in `config.py`, but they
require wiring into the `ModelRouter` constructor via `default_models`.

Individual models can be overridden per-role in the UI regardless of preset.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full system design.

## Security

- File access is restricted to explicitly registered root paths only
- Path traversal is blocked via `Path.resolve()` + relative-to validation
- No credentials are logged
- BYOK keys are read from environment only, never from request bodies
- See [Security Rule 0](SPEC.md#non-functional) in the spec
