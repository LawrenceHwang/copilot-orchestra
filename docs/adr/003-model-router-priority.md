# ADR 003: Model Router priority chain

## Status
Accepted

## Context
Three sources can specify which model an agent uses:
1. The user (via UI per-role override)
2. The orchestrator agent (in "auto" preset mode, via tool call)
3. The preset configuration (balanced/economy/performance)

## Decision
Priority chain (highest to lowest):

```
User Override  >  Orchestrator Choice  >  Preset Default  >  Hardcoded Fallback
```

`ModelRouter` is instantiated fresh per review with the request's preset and overrides.
Orchestrator choices are set at runtime via `router.set_orchestrator_choice(role, model)`.

## Rationale
- **User sovereignty**: A user who explicitly picks a model should always get it.
- **Orchestrator intelligence**: In auto mode, the orchestrator can pick the right model
  for each job (opus for security depth, haiku for readability speed). This is the
  "auto" preset's value proposition.
- **Preset as sensible default**: When neither user nor orchestrator specifies, the preset
  (balanced/economy/performance) applies.
- **Hardcoded fallback**: Prevents crashes if a preset config is incomplete.

## Consequences
- Orchestrator model choices do not override explicit user overrides. This is intentional
  (user intent > AI suggestion).
- In non-auto presets, `set_orchestrator_choice` is never called, so orchestrator tool
  calls for model selection are not registered as available tools.

## Model ID Format (operational note)

Copilot SDK model IDs use dot notation for version numbers: `claude-sonnet-4.6`,
`claude-haiku-4.5`, `claude-opus-4.6`. Hardcoded fallback constants (`_HARDCODED_DEFAULTS`,
`_ECONOMY_MODEL`, `_PERFORMANCE_MODEL` in `model_router.py`) must use this exact format.
Dash-style IDs (e.g. `claude-sonnet-4-6`) are not valid and will cause session creation
failures. Always cross-check against `GET /api/models` when updating SDK versions.
