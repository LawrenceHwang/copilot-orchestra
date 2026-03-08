# Copilot Orchestra — Product Specification

## Overview

Copilot Orchestra is a multi-agent AI code review platform built on the GitHub Copilot SDK.
It demonstrates capabilities that are impossible with the Copilot CLI alone: parallel agent
orchestration, real-time event streaming, programmatic tool registration, and live usage metrics.

## Problem Statement

GitHub Copilot CLI is a black box. Developers cannot:

- Run multiple review perspectives simultaneously
- See tool calls, reasoning, and token usage in real time
- Route different tasks to the most cost-effective model
- Integrate AI review into custom workflows programmatically (CI/CD, scripts, batch tools)

## Solution

A self-hosted web application that orchestrates five Copilot sessions simultaneously:

1. **Orchestrator** — reads the codebase and creates a focused review plan, then assigns the
   same set of files and the same focus area to all three reviewers
2. **Reviewer 1** (`reviewer_1`) — **Architecture guru**: service boundaries, coupling, API
   contracts, scalability ceilings, infrastructure implications, and long-term design tradeoffs
3. **Reviewer 2** (`reviewer_2`) — **Backend guru**: databases, caching, APIs, reliability,
   security at service boundaries, observability, and backend performance
4. **Reviewer 3** (`reviewer_3`) — **Frontend guru**: accessibility (WCAG 2.1 AA), i18n/l10n,
   UX correctness, render performance, component architecture, and visual correctness
5. **Synthesizer** — combines all three reviews into a unified final report

All three reviewers share a common baseline: 15+ years of practical industry experience,
long-term thinking, and the ability to make proper tradeoffs in context. Each brings a
distinct vertical specialization. They receive identical file assignments so the synthesizer
can triangulate findings across three expert lenses.

Reviewers are assigned random `<action>-<animal>` display names per session (e.g. `soaring-whale`).

All agent activity streams in real time to the browser. Token usage, context %, and premium
request counts update live.

## Core Requirements

### Functional

| ID | Requirement |
|----|-------------|
| F1 | User can specify a local codebase path and review task via the web UI |
| F2 | User can choose review scope: full repo or selected paths/files |
| F3 | User can select a model preset (balanced, economy, performance, free, auto) — each preset shows an explanatory description in the UI |
| F4 | User can override the model for any individual agent role |
| F5 | Orchestrator agent reads the codebase and assigns the same files and focus area to all three reviewers via a `submit_plan` tool call |
| F6 | Three independent reviewer agents run in parallel, each streaming output in real time; their event role identifiers are `reviewer_1` (Architecture), `reviewer_2` (Backend), `reviewer_3` (Frontend) |
| F7 | A synthesizer agent produces a final unified review when all three reviewers finish |
| F8 | In "auto" mode the orchestrator selects the model for each reviewer via `suggested_models` in the `ReviewPlan` |
| F9 | Real-time metrics bar shows aggregate token counts (IN/OUT/TOTAL), estimated cost (premium requests × $0.04), and premium request quota (used / total with % remaining). In BYOK mode, no dollar cost is shown — the UI displays a note to check vendor pricing for token usage. Per-agent panels show context window %, IN/OUT token counts. Context window % must use model-specific limits from `/api/models` (`capabilities.limits.max_context_window_tokens`) with a 200K fallback when missing, usage rows must appear for all started agents (including 0-token cases), and CTX labels should render as `CTX <percent>% of <window>`. Per-agent metrics labels must render in fixed role order (`orchestrator`, `reviewer_1`, `reviewer_2`, `reviewer_3`, `synthesizer`) and reviewer labels must match the same session-generated reviewer display names shown in reviewer panels. |
| F10 | BYOK: user can provide their own API key and provider via environment config |
| F11 | All agent tool calls (file reads, searches, diffs) are visible in the UI as activity badges for all agents including the orchestrator |
| F12 | Large-repo support: `.gitignore`-aware directory listing, content search via `grep_codebase`, per-file diffs via `git_diff_file` |
| F13 | Reviewer agents are assigned random `<action>-<animal>` display names per session (e.g. `soaring-whale`); backend roles remain `reviewer_1/2/3`, names are frontend-only |
| F14 | An info popout in the header explains the design philosophy and SDK capabilities to new users |
| F15 | Machine callers can poll `GET /api/reviews/{review_id}` for review status and final synthesis without holding an SSE connection — supports CI/CD and batch workflows |
| F16 | `GET /api/reviews` lists all known reviews (newest first) with status; `synthesis` is omitted from the list response and available only via the individual fetch |
| F17 | Codebase tools must accept both absolute and codebase-root-relative paths; tools with a `path` argument should default to the review root when omitted |
| F18 | FREE preset must select only SDK-discovered models with `billing.multiplier == 0.0` (0x); no hardcoded free-model IDs |
| F19 | Cost model: Copilot SDK mode estimates cost as `premium_requests × $0.04 USD`, where each model turn consumes `billing.multiplier` premium requests. BYOK mode shows token counts only with a note to check vendor pricing — no dollar estimate is displayed. |
| F20 | The orchestrator panel is displayed as a full-width horizontal bar above the three reviewer panels in the main content area (not in the sidebar). This makes the 5-agent pipeline visually clear: Orchestrator → 3 Reviewers → Synthesizer, all flowing top-to-bottom. |
| F21 | Every agent panel (orchestrator, 3 reviewers, synthesizer) has a maximize button (expand-arrows SVG icon) placed next to the copy button in the header action group. Clicking it expands the panel into a centered overlay (80vh × max-w-4xl) with a backdrop. The expanded panel continues to receive streamed data. Clicking outside the panel or clicking the close icon (× SVG) returns it to its original size. |

### Non-Functional

| ID | Requirement |
|----|-------------|
| N1 | Security rule 0: file access restricted to explicitly allowed paths only |
| N2 | No path traversal — all file tool paths validated against allowed roots; grep pattern passed as list arg (no shell expansion) |
| N3 | Structured logging on every request, session, and agent event for traceability |
| N4 | Architecture is UI-agnostic — orchestration layer has no FastAPI dependency |
| N5 | TUI-ready: a future `tui/` module can import orchestration directly |
| N10 | Machine-integration-ready: the REST API supports both SSE streaming (browsers/TUIs) and HTTP polling (CI/CD/scripts) without requiring any proprietary client SDK |
| N11 | FREE preset model discovery must use non-generative metadata calls (`list_models`) and must not trigger billable model inference |
| N6 | No premature optimization — simplicity over cleverness |
| N7 | All Python managed via `uv` |
| N8 | TDD: tests written before implementation, unit tests require no real CLI |
| N9 | All five agents (including orchestrator) publish identical event sets: `agent.started`, `agent.done` (with `duration_ms`), `metrics.update`, tool call events |
| N12 | UI text contrast must keep operational metadata (timers, status chips, usage-row labels, badge text) clearly readable in both dark and light themes; avoid low-contrast gray-on-gray combinations for critical runtime information |
| N13 | The main content area layout flows top-to-bottom: Orchestrator (full-width) → 3 Reviewers (grid) → Synthesizer (full-width). The sidebar contains only task input and model router controls. |
| N14 | Base font size is set to 112.5% on the `html` element (`src/frontend/src/styles/index.css`), scaling all rem-based Tailwind sizes proportionally. This balances information density with readability. The sidebar default width is 360px; drag range is 260–560px. Radio labels in the scope selector use `whitespace-nowrap` to prevent mid-word wrapping. |
| N15 | All agent system prompts follow a no-hedging behavioral contract: agents never ask "Would you like me to…", never offer to look at additional things, and never end with questions or prompts. They read the code, form judgment, and write the output. Full stop. |
| N16 | Agent prompt design targets FAANG principal/staff-engineer calibre: direct, opinionated, severity-calibrated, mentor-voiced. Each reviewer has a distinct vertical specialization (Architecture, Backend, Frontend) on top of a shared engineering baseline. |
| N17 | Every `send_and_wait` call must pass an explicit `timeout` parameter. The SDK's internal default (60 s) is too short for the synthesizer and deep-thinking models; omitting it causes silent mid-stream truncation that looks like a streaming failure. |
| N18 | The `handleEvent` SSE callback in `App.jsx` is `useCallback([models])` — `state` inside is always the initial value (stale closure). Cross-event coordination (e.g. detecting whether streaming already occurred for an agent) must use `useRef`, never stale `state` fields. |

## User Flows

### Primary: Start a Review (Browser)

```
1. Enter codebase path  (e.g. /path/to/your/repo)
2. Enter task description  (e.g. "Review for security and performance issues")
3. Choose scope: Full Repo | Custom Paths
4. Choose model preset or configure per-agent overrides
5. Optionally enter BYOK config
6. Click "Start Review"
7. Watch orchestrator plan, then three reviewer panels stream in real time
8. Maximize any panel (expand icon) for expanded viewing; click outside or close icon to collapse
9. Review synthesized report when complete
```

### Secondary: Machine / CI Integration (Polling)

```
1. POST /api/reviews  { task, codebase_path, scope, model_preset }
2. Receive review_id from the 202 response
3. Loop: GET /api/reviews/{review_id} every ~15 s
   - status == "running"  → wait and retry
   - status == "complete" → read synthesis field ✓
   - status == "error"    → read error field, fail the pipeline ✗
```

See docs/INTEGRATION_GUIDE.md for curl, Python, async, and GitHub Actions examples.

### Tertiary: BYOK Configuration

```
1. Set environment variables in .env:
   BYOK_PROVIDER_TYPE=anthropic
   BYOK_API_KEY=sk-ant-...
   BYOK_BASE_URL=https://api.anthropic.com  (optional)
2. Restart the server — BYOK is active for all sessions
3. UI shows "(BYOK)" badge next to model names
```

## Out of Scope (v1)

- Authentication / multi-user support
- Persistent review history (database — in-memory store only; lost on server restart)
- GitHub PR integration / webhooks
- Review diffing / comparison across runs
- TUI implementation (architecture supports it, not built in v1)
