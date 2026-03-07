"""
In-memory store for review state.

Allows machine callers to poll GET /api/reviews/{review_id} for status and the
final synthesis result without requiring a persistent SSE connection.

Design notes:
- Plain dict + dataclass; no locking needed (asyncio is single-threaded).
- Reviews are kept for the lifetime of the process. In production a TTL eviction
  policy (or external store) would be added, but for a local tool this is fine.
- The store is updated by run_review() directly — no EventBus subscription needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal


@dataclass
class ReviewState:
    review_id: str
    status: Literal["running", "complete", "error"]
    task: str
    codebase_path: str
    scope: str
    model_preset: str
    started_at: int          # unix ms
    completed_at: int | None = None
    duration_ms: int | None = None
    synthesis: str | None = None
    error: str | None = None


class ReviewStore:
    """Append-only in-memory store of review states."""

    def __init__(self) -> None:
        self._reviews: dict[str, ReviewState] = {}

    def create(
        self,
        review_id: str,
        task: str,
        codebase_path: str,
        scope: str,
        model_preset: str,
    ) -> ReviewState:
        """Register a new review as 'running'. Called before run_review() starts."""
        state = ReviewState(
            review_id=review_id,
            status="running",
            task=task,
            codebase_path=codebase_path,
            scope=scope,
            model_preset=model_preset,
            started_at=int(time.time() * 1000),
        )
        self._reviews[review_id] = state
        return state

    def get(self, review_id: str) -> ReviewState | None:
        """Return state for a review, or None if unknown."""
        return self._reviews.get(review_id)

    def list_all(self) -> list[ReviewState]:
        """Return all known reviews, newest first."""
        return sorted(
            self._reviews.values(),
            key=lambda s: s.started_at,
            reverse=True,
        )

    def set_complete(self, review_id: str, synthesis: str, duration_ms: int) -> None:
        """Mark a review as successfully complete."""
        if state := self._reviews.get(review_id):
            state.status = "complete"
            state.synthesis = synthesis
            state.duration_ms = duration_ms
            state.completed_at = int(time.time() * 1000)

    def set_error(self, review_id: str, error: str) -> None:
        """Mark a review as failed."""
        if state := self._reviews.get(review_id):
            state.status = "error"
            state.error = error
            state.completed_at = int(time.time() * 1000)
