# ADR 005: Emit orchestrator.plan event for UI transparency

## Status
Accepted

## Context
The orchestrator calls `submit_plan` to hand off a structured `ReviewPlan` to the three
reviewer agents. Before this change, the plan was an internal backend object only — the UI
showed the orchestrator's raw stream text but gave no insight into what files were assigned
to each reviewer or what focus was chosen.

This made it hard to understand the orchestrator's decision-making and debug mis-scoped
reviews (e.g. if the orchestrator picked the wrong files or wrote a vague focus).

## Decision
After a successful `submit_plan` call, publish an `orchestrator.plan` SSE event containing
the full plan before returning the tool result to the model:

```python
await event_bus.publish(review_id, {
    "type": "orchestrator.plan",
    "review_id": review_id,
    "plan": {
        "reviewer_1": {"files": [...], "focus": "..."},
        "reviewer_2": {"files": [...], "focus": "..."},
        "reviewer_3": {"files": [...], "focus": "..."},
        "rationale": "...",
    },
})
```

The frontend stores this in `state.orchestrator.plan` and renders it as a `ReviewPlanView`
in the orchestrator panel, showing each reviewer's color-coded badge, file count, focus,
and filename chips.

The compact summary bar (shown after the orchestrator finishes) also renders a one-line
plan summary (file count + focus) highlighted in indigo, replacing the raw first line of
stream text.

## Rationale
- **Transparency**: Users can see exactly what the orchestrator decided, not just that it
  "ran". This is the core value of the orchestrator step.
- **Debuggability**: Mis-scoped plans (wrong files, vague focus) are immediately visible
  before reviewer output arrives.
- **Event-driven**: Piggybacking on the existing SSE event bus requires no new endpoints
  or polling — the plan appears the instant it is submitted.
- **Publish before returning**: The event is published inside the tool handler, before
  `ToolResult` is returned to the model. This ensures the UI updates while the model is
  still processing the acknowledgement.

## Frontend state shape

```javascript
// orchestrator state (makeAgentState + plan field)
{
  status: "idle" | "running" | "done" | "error",
  streamText: "",
  streaming: false,
  model: null,
  toolCalls: [],
  error: null,
  plan: null | {
    reviewer_1: { files: string[], focus: string },
    reviewer_2: { files: string[], focus: string },
    reviewer_3: { files: string[], focus: string },
    rationale: string,
  },
}
```

## Consequences
- The `plan` field is present on all agent states (via `makeAgentState`) but only populated
  for the orchestrator. Non-orchestrator agents ignore it.
- The `ReviewPlanView` component in `AgentPanel.jsx` renders only when `state.plan` is set,
  so it never appears on reviewer or synthesizer panels.
- If the orchestrator falls back to `_fallback_plan` (no plan submitted), no
  `orchestrator.plan` event is emitted. The UI shows no plan section in that case.
