# ADR 004: Copilot SDK Tool API — ToolInvocation and ToolResult are dataclasses

## Status
Accepted

## Context
The orchestrator registers a custom `submit_plan` tool using the Copilot SDK's `Tool` dataclass.
The tool handler receives a `ToolInvocation` and must return a `ToolResult`.

An early implementation treated both as plain dicts (e.g. `invocation["arguments"]` and
`return {"textResultForLlm": ..., "resultType": ...}`), following a camelCase JSON intuition.
This caused every `submit_plan` call to raise `TypeError: 'ToolInvocation' object is not
subscriptable`, which was silently caught by the handler's except block and returned as a
failure. The orchestrator retried repeatedly, gave up, and the fallback plan (empty file list)
was used instead.

## Decision
Access `ToolInvocation` fields as dataclass attributes and construct `ToolResult` as a dataclass:

```python
# WRONG — dict-style access on a dataclass
plan = ReviewPlan.model_validate(invocation["arguments"])
return {"textResultForLlm": "ok", "resultType": "success"}

# CORRECT — dataclass attribute access
plan = ReviewPlan.model_validate(invocation.arguments)
return ToolResult(text_result_for_llm="ok", result_type="success")
```

## SDK types (from `copilot.types`):

```python
@dataclass
class ToolInvocation:
    session_id: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: Any = None          # already parsed — pass directly to model_validate()

@dataclass
class ToolResult:
    text_result_for_llm: str = ""
    result_type: ToolResultType = "success"   # "success" | "failure" | "rejected" | "denied"
    error: str | None = None
    binary_results_for_llm: list[ToolBinaryResult] | None = None
    session_log: str | None = None
    tool_telemetry: dict[str, Any] | None = None
```

`ToolHandler = Callable[[ToolInvocation], ToolResult | Awaitable[ToolResult]]`

## Rationale
- The SDK exposes clean Python dataclasses, not JSON dicts. Fields use snake_case.
- `invocation.arguments` is already a parsed object (dict/list/scalar) — no `json.loads()`
  needed before passing to Pydantic's `model_validate()`.
- `ToolResult` fields are snake_case (`text_result_for_llm`, `result_type`), not camelCase.
- Silent exception swallowing in tool handlers is dangerous: always log the error before
  returning a failure result so the root cause is visible.

## Consequences
- All custom tool handlers in this project must use dataclass access, not dict access.
- `ToolResult` must be instantiated, not returned as a plain dict.
- Pydantic's `model_validate()` can receive `invocation.arguments` directly when the SDK
  delivers a parsed dict (which it always does for structured tool calls).
