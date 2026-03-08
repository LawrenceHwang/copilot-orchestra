"""
API request/response schemas (Pydantic models).

These are the contract between the HTTP layer and the orchestration core.
Validation happens here — the orchestration layer receives clean data.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ModelOverrides(BaseModel):
    """Per-role model overrides. Any omitted role uses the preset default."""

    orchestrator: str | None = None
    reviewer_1: str | None = None
    reviewer_2: str | None = None
    reviewer_3: str | None = None
    synthesizer: str | None = None

    def to_role_dict(self) -> dict:
        """Return only the roles that have overrides."""
        from backend.orchestration.model_router import AgentRole

        result = {}
        for field_name, value in self.model_dump().items():
            if value is not None:
                try:
                    result[AgentRole(field_name)] = value
                except ValueError:
                    pass
        return result


class ReviewRequest(BaseModel):
    """Request body for POST /api/reviews."""

    task: str = Field(
        description="What to review and what to look for",
        min_length=10,
        max_length=2000,
    )
    codebase_path: str = Field(
        description="Absolute path to the local codebase directory",
        examples=["/Users/law/workplace/GitHub/global-demographics"],
    )
    scope: Literal["full", "custom"] = Field(
        default="full",
        description="full=entire codebase, custom=only custom_paths",
    )
    custom_paths: list[str] | None = Field(
        default=None,
        description="Required when scope=custom. Specific file/dir paths within codebase_path.",
    )
    model_preset: Literal["balanced", "economy", "performance", "free", "auto"] = Field(
        default="balanced",
    )
    model_overrides: ModelOverrides | None = None

    @model_validator(mode="after")
    def validate_custom_scope(self) -> "ReviewRequest":
        if self.scope == "custom" and not self.custom_paths:
            raise ValueError("custom_paths must be non-empty when scope is 'custom'")
        return self

    @field_validator("codebase_path")
    @classmethod
    def validate_path_is_absolute(cls, v: str) -> str:
        from pathlib import Path

        p = Path(v)
        if not p.is_absolute():
            raise ValueError("codebase_path must be an absolute path")
        return v


class ReviewResponse(BaseModel):
    """Response for POST /api/reviews."""

    review_id: str
    status: str
    sse_url: str


class ModelInfoResponse(BaseModel):
    """Single model info for the models list."""

    id: str
    name: str
    capabilities: dict | None = None
    policy: dict | None = None
    billing_multiplier: float | None = None


class ModelListResponse(BaseModel):
    """Response for GET /api/models."""

    models: list[ModelInfoResponse]
    byok_active: bool


class HealthResponse(BaseModel):
    """Response for GET /api/health."""

    status: str
    copilot_connected: bool


class ReviewStatusResponse(BaseModel):
    """Response for GET /api/reviews/{review_id} and GET /api/reviews."""

    review_id: str
    status: Literal["running", "complete", "error"]
    task: str
    codebase_path: str
    scope: str
    model_preset: str
    started_at: int  # unix ms
    completed_at: Optional[int] = None  # unix ms
    duration_ms: Optional[int] = None
    synthesis: Optional[str] = None  # populated when status == "complete"
    error: Optional[str] = None  # populated when status == "error"
    sse_url: str  # convenience: always /api/events/{review_id}
