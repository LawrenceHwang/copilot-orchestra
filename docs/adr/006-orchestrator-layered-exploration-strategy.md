# ADR 006: Orchestrator layered exploration strategy

## Status
Accepted

## Context

The orchestrator agent's job is to survey a codebase and produce a `ReviewPlan` (a curated
file list + focus statement for three reviewer agents). Observed failure mode: the orchestrator
spent its entire time budget making 40+ `grep_codebase` calls on a single file with
increasingly narrow patterns, never reaching `submit_plan`. The root cause was a flat prompt
structure that said "explore then submit" with no guidance on when to stop exploring.

A secondary timeout issue: the orchestrator's `send_and_wait` was set to 300 s, too short
for large codebases. This was raised to 600 s (see ADR 004).

## Decision

Replace the flat "explore, decide, submit" prompt with a two-phase layered strategy that
mirrors how a senior engineer approaches an unfamiliar codebase:

### Phase 1 — BUILD THE INDEX
Goal: form a 10,000-ft mental map before touching any individual file.

- `list_directory(depth=2)` from the project root.
- List key subdirectories if needed.
- From filenames and directory names alone, classify every module (auth, API, DB, utils, …)
  and build a candidate file list.
- Many tasks can be fully scoped at this stage — no file reading needed.

### Phase 2 — TARGETED DEEP-DIVE (only what the index cannot answer)
Goal: resolve specific uncertainties, then immediately submit.

- `grep_codebase` — one broad grep per concept (e.g. "which file handles JWT validation?").
  Stop after the concept is located.
- `read_file` — only for files whose inclusion/exclusion is genuinely uncertain.
- `git_diff` / `git_diff_file` — only for diff-focused tasks.

After every Phase 2 tool call the agent applies a decision gate:
> "Do I now know the 5-15 most relevant files?" → YES: `submit_plan`. NO: one more call.

Anti-patterns listed explicitly in the prompt:
- Grepping the same file repeatedly with different patterns.
- Exploring files unrelated to the review task.
- Continuing to explore after the relevant files are already known.
- Reading files "just to understand them" without a plan inclusion decision.

## Rationale

- **Index-first mirrors how experts work**: A senior engineer looking at a new codebase reads
  the directory tree first to build a mental map, then dives into the relevant corner. They do
  not start reading random files. The prompt encodes this pattern.
- **Separation of concerns**: Phase 1 (orient) and Phase 2 (target) have distinct objectives.
  Making this explicit in the prompt prevents the agent from conflating discovery and analysis.
- **Decision gate prevents runaway loops**: The original failure mode was an infinite search
  loop with no stopping criterion. The "do I know enough?" question after every tool call
  provides one.
- **Anti-patterns over hard caps**: Hard tool-call limits prevent legitimate exploration on
  complex codebases. Named anti-patterns give the model the reasoning to self-regulate without
  an arbitrary numeric ceiling.

## Consequences

- The orchestrator is expected to call `list_directory` first on every review. This is a small
  fixed cost and worth the structural benefit.
- On small repos where filenames alone reveal the relevant files, Phase 2 may be skipped
  entirely — the agent goes from `list_directory` directly to `submit_plan`.
- The reviewer prompt uses an analogous 4-step workflow (Orient → Read Assigned →
  Pull Dependencies → Write) for consistency, though reviewers start with a curated file list
  rather than an empty slate.
