# Copilot Orchestra — Machine Integration Guide

This guide is for **programmatic (machine) callers**: CI/CD pipelines, shell scripts,
batch tools, and custom clients. If you are building a browser UI, see the SSE
streaming pattern in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## API Quick Reference

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/health` | Liveness check |
| `GET`  | `/api/models` | List available Copilot models |
| `POST` | `/api/reviews` | Start a review; returns `review_id` |
| `GET`  | `/api/reviews` | List all reviews (newest first) |
| `GET`  | `/api/reviews/{review_id}` | Poll status + fetch synthesis result |
| `GET`  | `/api/events/{review_id}` | SSE stream (real-time; optional for machines) |

Interactive docs (Swagger UI) are available at **`/api/docs`** when the server is running.

---

## Two Integration Patterns

### Pattern A — Polling (recommended for CI/CD)

Fire the review and poll until it finishes. No persistent connection required.

```
POST /api/reviews
  └─ receive review_id

loop:
  GET /api/reviews/{review_id}
  └─ status == "running"  → wait, retry
  └─ status == "complete" → read synthesis ✓
  └─ status == "error"    → read error, fail build ✗
```

### Pattern B — SSE streaming (recommended for dashboards / TUIs)

Subscribe to the event stream for real-time progress. The stream closes automatically
when `stream.end` is received.

```
POST /api/reviews
  └─ receive review_id + sse_url

EventSource(sse_url)
  └─ listen to events until type == "stream.end"
  └─ collect type == "review.complete" → read synthesis
```

---

## Pattern A — Polling Examples

### curl

```bash
BASE=http://localhost:8000

# 1. Start the review
RESPONSE=$(curl -s -X POST "$BASE/api/reviews" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Review for security vulnerabilities and SQL injection risks",
    "codebase_path": "/path/to/your/repo",
    "scope": "full",
    "model_preset": "balanced"
  }')

REVIEW_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['review_id'])")
echo "Review started: $REVIEW_ID"

# 2. Poll until done
while true; do
  STATUS_RESP=$(curl -s "$BASE/api/reviews/$REVIEW_ID")
  STATUS=$(echo "$STATUS_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")

  echo "Status: $STATUS"

  if [ "$STATUS" = "complete" ]; then
    echo "$STATUS_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['synthesis'])"
    break
  elif [ "$STATUS" = "error" ]; then
    echo "Review failed:" $(echo "$STATUS_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['error'])")
    exit 1
  fi

  sleep 15
done
```

---

### Python (requests)

```python
import time
import requests

BASE = "http://localhost:8000"

# 1. Health check
health = requests.get(f"{BASE}/api/health").json()
assert health["status"] == "ok", f"Server not ready: {health}"
assert health["copilot_connected"], "Copilot client not connected"

# 2. Start review
resp = requests.post(f"{BASE}/api/reviews", json={
    "task": "Review authentication and authorisation logic for security issues",
    "codebase_path": "/path/to/your/repo",
    "scope": "full",
    "model_preset": "balanced",
})
resp.raise_for_status()
review_id = resp.json()["review_id"]
print(f"Review started: {review_id}")

# 3. Poll until complete
poll_interval = 15  # seconds
while True:
    result = requests.get(f"{BASE}/api/reviews/{review_id}").json()
    status = result["status"]
    print(f"  Status: {status}")

    if status == "complete":
        print("\n--- SYNTHESIS ---")
        print(result["synthesis"])
        print(f"\nDuration: {result['duration_ms']}ms")
        break
    elif status == "error":
        raise RuntimeError(f"Review failed: {result['error']}")

    time.sleep(poll_interval)
```

---

### Python (async + httpx)

```python
import asyncio
import httpx

BASE = "http://localhost:8000"

async def run_review(task: str, codebase_path: str) -> str:
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        # Start
        resp = await client.post("/api/reviews", json={
            "task": task,
            "codebase_path": codebase_path,
            "scope": "full",
            "model_preset": "balanced",
        })
        resp.raise_for_status()
        review_id = resp.json()["review_id"]

        # Poll
        while True:
            result = (await client.get(f"/api/reviews/{review_id}")).json()
            if result["status"] == "complete":
                return result["synthesis"]
            if result["status"] == "error":
                raise RuntimeError(result["error"])
            await asyncio.sleep(15)

synthesis = asyncio.run(run_review(
    task="Check for performance bottlenecks in database queries",
    codebase_path="/path/to/your/repo",
))
print(synthesis)
```

---

## Pattern B — SSE Streaming Examples

### Python (sseclient-py)

```bash
pip install sseclient-py requests
```

```python
import json
import requests
import sseclient

BASE = "http://localhost:8000"

# Start review
resp = requests.post(f"{BASE}/api/reviews", json={
    "task": "Review for code quality and maintainability",
    "codebase_path": "/path/to/your/repo",
    "scope": "full",
    "model_preset": "balanced",
})
resp.raise_for_status()
review_id = resp.json()["review_id"]

# Stream events
stream_resp = requests.get(
    f"{BASE}/api/events/{review_id}",
    stream=True,
    headers={"Accept": "text/event-stream"},
)

client = sseclient.SSEClient(stream_resp)
for event in client.events():
    data = json.loads(event.data)
    event_type = data["type"]

    if event_type == "agent.started":
        print(f"[{data['agent']}] started on {data['model']}")

    elif event_type == "agent.stream":
        print(data["content"], end="", flush=True)

    elif event_type == "agent.tool_call":
        print(f"\n[{data['agent']}] → {data['tool_name']}({data.get('args', {})})")

    elif event_type == "agent.done":
        print(f"\n[{data['agent']}] done in {data['duration_ms']}ms")

    elif event_type == "review.complete":
        print("\n\n=== FINAL REPORT ===")
        print(data["synthesis"])
        print(f"\nTotal duration: {data['duration_ms']}ms")

    elif event_type == "review.error":
        raise RuntimeError(f"Review failed: {data['error']}")

    elif event_type == "stream.end":
        break
```

---

### curl (raw SSE)

```bash
curl -N -H "Accept: text/event-stream" \
  "http://localhost:8000/api/events/$REVIEW_ID"
```

---

## Request Reference

### POST /api/reviews

**Minimal request:**
```json
{
  "task": "Review for security vulnerabilities",
  "codebase_path": "/absolute/path/to/repo"
}

### Tool Invocation Compatibility Notes

Agent-side codebase tools accept both absolute and repository-root-relative paths.
For example, `read_file` can be called with either `/repo/src/app.py` or `src/app.py`.
Tools with a repository `path` parameter (`list_directory`, `git_diff`, `git_diff_file`)
also default to the review root when omitted. This improves cross-model reliability
without relaxing path-safety constraints.
```

**Full request with all options:**
```json
{
  "task": "Focus on authentication, session management, and SQL injection risks",
  "codebase_path": "/absolute/path/to/repo",
  "scope": "custom",
  "custom_paths": ["src/auth", "src/api/routes.py", "db/migrations"],
  "model_preset": "performance",
  "model_overrides": {
    "orchestrator": "claude-sonnet-4-6",
    "reviewer_1": "claude-opus-4-6",
    "reviewer_2": "claude-opus-4-6",
    "reviewer_3": "claude-sonnet-4-6",
    "synthesizer": "claude-sonnet-4-6"
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task` | string (10–2000 chars) | required | What to review and look for |
| `codebase_path` | string (absolute path) | required | Local directory to review |
| `scope` | `"full"` \| `"custom"` | `"full"` | `full` = entire codebase; `custom` = only `custom_paths` |
| `custom_paths` | string[] | — | Required when `scope="custom"`. Relative paths within `codebase_path` |
| `model_preset` | `"balanced"` \| `"economy"` \| `"performance"` \| `"auto"` | `"balanced"` | See model presets below |
| `model_overrides` | object | — | Override the model for specific agent roles |

#### Model Presets

| Preset | Orchestrator | Reviewers | Synthesizer | Use when |
|--------|-------------|-----------|-------------|----------|
| `balanced` | claude-sonnet-4-6 | claude-sonnet-4-6 | claude-sonnet-4-6 | Default; good quality + cost |
| `economy` | claude-haiku-4-5 | claude-haiku-4-5 | claude-haiku-4-5 | Fast feedback, lower quota usage |
| `performance` | claude-opus-4-6 | claude-opus-4-6 | claude-opus-4-6 | Deepest analysis, highest cost |
| `auto` | claude-sonnet-4-6 | orchestrator decides per reviewer | orchestrator decides | Let the orchestrator pick per file complexity |

#### Model Overrides (highest priority)

Override any individual role, regardless of preset:
```json
{
  "model_overrides": {
    "reviewer_1": "claude-opus-4-6",
    "synthesizer": "claude-sonnet-4-6"
  }
}
```
Roles: `orchestrator`, `reviewer_1`, `reviewer_2`, `reviewer_3`, `synthesizer`.

---

### GET /api/reviews/{review_id}

**Response when running:**
```json
{
  "review_id": "f47ac10b-...",
  "status": "running",
  "task": "Review for security vulnerabilities",
  "codebase_path": "/path/to/repo",
  "scope": "full",
  "model_preset": "balanced",
  "started_at": 1700000000000,
  "completed_at": null,
  "duration_ms": null,
  "synthesis": null,
  "error": null,
  "sse_url": "/api/events/f47ac10b-..."
}
```

**Response when complete:**
```json
{
  "review_id": "f47ac10b-...",
  "status": "complete",
  "task": "Review for security vulnerabilities",
  "codebase_path": "/path/to/repo",
  "scope": "full",
  "model_preset": "balanced",
  "started_at": 1700000000000,
  "completed_at": 1700000045000,
  "duration_ms": 45000,
  "synthesis": "# Code Review: Final Report\n\n## Verdict\n**Ship it**...",
  "error": null,
  "sse_url": "/api/events/f47ac10b-..."
}
```

**Response when errored:**
```json
{
  "review_id": "f47ac10b-...",
  "status": "error",
  "synthesis": null,
  "error": "CopilotClient failed to start: CLI not found",
  ...
}
```

Returns `404` if the `review_id` is unknown (not created in this server process).

---

### GET /api/reviews

Lists all reviews (newest first). The `synthesis` field is always `null` in this
response — fetch the individual review to get the full text.

```json
[
  {
    "review_id": "f47ac10b-...",
    "status": "complete",
    "task": "Review for security vulnerabilities",
    "started_at": 1700000000000,
    "completed_at": 1700000045000,
    "duration_ms": 45000,
    "synthesis": null,
    "error": null,
    "sse_url": "/api/events/f47ac10b-..."
  },
  {
    "review_id": "a1b2c3d4-...",
    "status": "running",
    "task": "Check performance of database queries",
    "started_at": 1700000050000,
    "completed_at": null,
    "synthesis": null,
    "error": null,
    "sse_url": "/api/events/a1b2c3d4-..."
  }
]
```

---

## GitHub Actions Integration

```yaml
name: AI Code Review

on:
  pull_request:
    branches: [main]

jobs:
  ai-review:
    runs-on: ubuntu-latest
    # Requires: self-hosted runner with Copilot CLI + this server running,
    # OR a deployed instance accessible from GitHub Actions.
    steps:
      - uses: actions/checkout@v4
        with:
          path: repo

      - name: Start review
        id: review
        run: |
          RESPONSE=$(curl -sf -X POST "${{ vars.COPILOT_ORCHESTRA_URL }}/api/reviews" \
            -H "Content-Type: application/json" \
            -d "$(jq -n \
              --arg task "Review this PR for security issues, correctness, and maintainability" \
              --arg path "${{ github.workspace }}/repo" \
              '{task: $task, codebase_path: $path, scope: "full", model_preset: "balanced"}'
            )")
          echo "review_id=$(echo $RESPONSE | jq -r .review_id)" >> $GITHUB_OUTPUT

      - name: Wait for review
        run: |
          REVIEW_ID="${{ steps.review.outputs.review_id }}"
          URL="${{ vars.COPILOT_ORCHESTRA_URL }}/api/reviews/$REVIEW_ID"

          for i in $(seq 1 40); do
            RESULT=$(curl -sf "$URL")
            STATUS=$(echo "$RESULT" | jq -r .status)
            echo "Attempt $i: $STATUS"

            if [ "$STATUS" = "complete" ]; then
              echo "$RESULT" | jq -r .synthesis > review_output.md
              exit 0
            elif [ "$STATUS" = "error" ]; then
              echo "Review failed: $(echo $RESULT | jq -r .error)"
              exit 1
            fi
            sleep 30
          done
          echo "Timed out waiting for review"
          exit 1

      - name: Post review as PR comment
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const body = fs.readFileSync('review_output.md', 'utf8');
            await github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: `## AI Code Review\n\n${body}`,
            });
```

---

## Error Handling Reference

| Scenario | How to detect | Recommended action |
|----------|---------------|--------------------|
| Server not running | `GET /api/health` returns connection error | Fail fast; check server |
| Copilot CLI not connected | `health.copilot_connected == false` | Fail fast; check `gh copilot` auth |
| Invalid request | `POST /api/reviews` returns 400/422 | Fix request body (path, task length) |
| Review not found | `GET /api/reviews/{id}` returns 404 | Review ID from a previous process run; restart |
| One agent failed | `agent.error` event in SSE stream | Pipeline continues; synthesis may be partial |
| Full pipeline failed | `review.status == "error"` | Read `error` field; retry or investigate |
| Review timed out | `agent.error` with "No activity for 90s" | Agent-level timeout; pipeline continues with other reviewers |

### Partial results

If one reviewer agent fails (timeout, model error), the pipeline publishes an
`agent.error` SSE event and continues. The synthesizer receives whatever results
are available and notes any missing reviewers in its report. Always check the
synthesis text for `[reviewer_N review unavailable: ...]` markers.

---

## Timing Guidance

Typical review durations (local laptop, `balanced` preset):

| Codebase size | Scope | Approximate duration |
|--------------|-------|---------------------|
| Small (< 5 files) | custom | 30–90 s |
| Medium (10–50 files) | full | 2–5 min |
| Large (100+ files) | full | 5–12 min |

Reviews beyond 10 minutes are likely hitting a timeout. Use `scope: "custom"` with
`custom_paths` to narrow the review on large codebases.

Recommended poll interval: **15 seconds**. The server applies no rate limiting,
but polling more frequently than every 5 s is unnecessary.

---

## Listing Available Models

```bash
curl http://localhost:8000/api/models
```

```json
{
  "models": [
    {
      "id": "claude-opus-4-6",
      "name": "Claude Opus 4.6",
      "capabilities": { ... },
      "policy": { ... }
    },
    ...
  ],
  "byok_active": false
}
```

Use model `id` values directly in `model_overrides`.

---

## BYOK (Bring Your Own Key)

The server is configured server-side only (no API key in the request body).
Set environment variables before starting the server:

```bash
BYOK_PROVIDER_TYPE=anthropic   # "openai" | "anthropic" | "azure"
BYOK_API_KEY=sk-ant-...
# BYOK_BASE_URL=https://...    # optional; for Azure or custom endpoints
```

When `byok_active` is `true` in `GET /api/models`, all sessions use your key.
The `model_preset` and `model_overrides` fields work the same way.

---

## Notes for Library / SDK Authors

- The API is a plain HTTP+JSON + SSE interface. No proprietary SDK is required.
- The `review_id` is a UUID4 string — store it if you need to re-fetch results.
- Review state is **in-memory only**. After a server restart, all review IDs are gone.
  If durability is required, integrate a persistent store at `ReviewStore` in
  `backend/orchestration/review_store.py`.
- CORS: by default the server allows `http://localhost:5173` and `http://localhost:3000`.
  Add origins via the `CORS_ORIGINS` env var (comma-separated).
- The interactive OpenAPI spec is served at `/api/openapi.json` (machine-readable)
  and `/api/docs` (Swagger UI).
