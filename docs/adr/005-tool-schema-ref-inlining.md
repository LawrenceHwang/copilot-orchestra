# ADR 005: Inline $ref in Tool parameter schemas

## Status
Accepted

## Context

The `submit_plan` tool passed to `CopilotSession` uses Pydantic v2's `model_json_schema()`
to generate its `parameters` schema from `ReviewPlan`. Pydantic v2 emits schemas with `$defs`
+ `$ref` for reused nested models:

```json
{
  "$defs": {
    "AgentPlan": { ... }
  },
  "properties": {
    "reviewer_1": { "$ref": "#/$defs/AgentPlan" },
    "reviewer_2": { "$ref": "#/$defs/AgentPlan" },
    "reviewer_3": { "$ref": "#/$defs/AgentPlan" }
  }
}
```

The Copilot SDK (and the underlying model APIs it proxies) do not resolve `$ref` pointers in
tool parameter schemas. The model receives an incomplete schema and cannot produce a valid
`submit_plan` call, causing tool execution errors on every invocation.

## Decision

Add `_inline_schema_refs(schema: dict) -> dict` to `orchestrator.py`. It deep-copies the
schema, removes `$defs`, and recursively replaces every `{"$ref": "#/$defs/Foo"}` with the
resolved inline definition. Call it when constructing `Tool(parameters=...)`:

```python
submit_plan_tool = Tool(
    name="submit_plan",
    parameters=_inline_schema_refs(ReviewPlan.model_json_schema()),
    ...
)
```

The resulting schema has all nested objects fully spelled out inline:

```json
{
  "properties": {
    "reviewer_1": {
      "properties": {
        "files": { "items": { "type": "string" }, "type": "array" },
        "focus": { "type": "string" }
      },
      "required": ["focus"],
      "type": "object"
    },
    ...
  }
}
```

## Rationale

- **Root cause is a Pydantic v2 + LLM API incompatibility**: Pydantic v2 optimises schema size
  by deduplicating repeated nested models into `$defs`. LLM tool-calling APIs expect flat,
  self-contained JSON Schema objects. These two conventions conflict.
- **Inlining is the correct fix**: The alternative (flattening `ReviewPlan` into primitive
  fields) would destroy the model structure and make validation harder. Inlining preserves the
  Pydantic model while producing an API-compatible schema.
- **Scope is local**: Only `submit_plan` uses a Pydantic-derived schema. The five codebase
  tools use manually written parameter objects and are unaffected.

## Consequences

- Any future tool whose `parameters` are derived from a Pydantic model with nested sub-models
  must also use `_inline_schema_refs`. Document this at the call site.
- Schema is slightly larger on the wire (repeated definitions), but this is negligible for
  `ReviewPlan` (three identical `AgentPlan` objects).
- The helper is pure (no side effects) and tested implicitly by the `submit_plan` tool
  succeeding in integration.
