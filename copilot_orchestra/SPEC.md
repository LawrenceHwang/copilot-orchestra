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
2. **Reviewer 1** (`reviewer_1`) — independently reviews the assigned files across all dimensions
3. **Reviewer 2** (`reviewer_2`) — independently reviews the same files from a fresh perspective
4. **Reviewer 3** (`reviewer_3`) — independently reviews the same files from a fresh perspective
5. **Synthesizer** — combines all three reviews into a unified final report

Each reviewer covers all five quality dimensions: **Security**, **Correctness**,
**Maintainability**, **Readability**, and **Performance**. All three reviewers receive
identical assignments so their outputs can be directly compared and synthesized. Reviewers
are assigned random `<action>-<animal>` display names per session (e.g. `soaring-whale`).

All agent activity streams in real time to the browser. Token usage, context %, and premium
request counts update live.

## Core Requirements

### Functional

| ID | Requirement |
|----|-------------|
| F1 | User can specify a local codebase path and review task via the web UI |
| F2 | User can choose review scope: full repo or selected paths/files |
| F3 | User can select a model preset (balanced, economy, performance, auto) — each preset shows an explanatory description in the UI |
| F4 | User can override the model for any individual agent role |
| F5 | Orchestrator agent reads the codebase and assigns the same files and focus area to all three reviewers via a `submit_plan` tool call |
| F6 | Three independent reviewer agents run in parallel, each streaming output in real time; their event role identifiers are `reviewer_1`, `reviewer_2`, `reviewer_3` |
| F7 | A synthesizer agent produces a final unified review when all three reviewers finish |
| F8 | In "auto" mode the orchestrator selects the model for each reviewer via `suggested_models` in the `ReviewPlan` |
| F9 | Real-time metrics bar shows aggregate token counts (IN/OUT/TOTAL), aggregate cost, and premium request quota (used / total with % remaining). Per-agent panels each show: context window % bar (input_tokens / 200K), IN/OUT token counts, and per-turn cost. All five agents including orchestrator and synthesizer emit metrics. |
| F10 | BYOK: user can provide their own API key and provider via environment config |
| F11 | All agent tool calls (file reads, searches, diffs) are visible in the UI as activity badges for all agents including the orchestrator |
| F12 | Large-repo support: `.gitignore`-aware directory listing, content search via `grep_codebase`, per-file diffs via `git_diff_file` |
| F13 | Reviewer agents are assigned random `<action>-<animal>` display names per session (e.g. `soaring-whale`); backend roles remain `reviewer_1/2/3`, names are frontend-only |
| F14 | An info popout in the header explains the design philosophy and SDK capabilities to new users |
| F15 | Machine callers can poll `GET /api/reviews/{review_id}` for review status and final synthesis without holding an SSE connection — supports CI/CD and batch workflows |
| F16 | `GET /api/reviews` lists all known reviews (newest first) with status; `synthesis` is omitted from the list response and available only via the individual fetch |

### Non-Functional

| ID | Requirement |
|----|-------------|
| N1 | Security rule 0: file access restricted to explicitly allowed paths only |
| N2 | No path traversal — all file tool paths validated against allowed roots; grep pattern passed as list arg (no shell expansion) |
| N3 | Structured logging on every request, session, and agent event for traceability |
| N4 | Architecture is UI-agnostic — orchestration layer has no FastAPI dependency |
| N5 | TUI-ready: a future `tui/` module can import orchestration directly |
| N10 | Machine-integration-ready: the REST API supports both SSE streaming (browsers/TUIs) and HTTP polling (CI/CD/scripts) without requiring any proprietary client SDK |
| N6 | No premature optimization — simplicity over cleverness |
| N7 | All Python managed via `uv` |
| N8 | TDD: tests written before implementation, unit tests require no real CLI |
| N9 | All five agents (including orchestrator) publish identical event sets: `agent.started`, `agent.done` (with `duration_ms`), `metrics.update`, tool call events |

## User Flows

### Primary: Start a Review (Browser)

```
1. Enter codebase path  (default: /Users/law/workplace/GitHub/global-demographics)
2. Enter task description  (e.g. "Review for security and performance issues")
3. Choose scope: Full Repo | Custom Paths
4. Choose model preset or configure per-agent overrides
5. Optionally enter BYOK config
6. Click "Start Review"
7. Watch three agent panels stream in real time
8. Review synthesized report when complete
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
