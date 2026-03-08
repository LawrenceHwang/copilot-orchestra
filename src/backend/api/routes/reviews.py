"""
POST /api/reviews          — start a new review.
GET  /api/reviews          — list all known reviews (status only, no synthesis).
GET  /api/reviews/{id}     — get full review status + synthesis result.
"""

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from backend.api.dependencies import get_event_bus, get_review_store, get_session_manager
from backend.api.schemas import ReviewRequest, ReviewResponse, ReviewStatusResponse
from backend.logging_config import get_logger
from backend.orchestration.event_bus import EventBus
from backend.orchestration.model_router import AgentRole, ModelPreset, ModelRouter
from backend.orchestration.orchestrator import ReviewRequest as OrchestratorRequest
from backend.orchestration.orchestrator import run_review
from backend.orchestration.review_store import ReviewStore
from backend.orchestration.session_manager import SessionManager

router = APIRouter()
logger = get_logger("api.reviews")


@router.post("/reviews", response_model=ReviewResponse, status_code=202)
async def start_review(
    request_body: ReviewRequest,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
    event_bus: EventBus = Depends(get_event_bus),
    review_store: ReviewStore = Depends(get_review_store),
) -> ReviewResponse:
    """
    Start a new multi-agent code review.

    Returns immediately with a review_id. Use GET /api/events/{review_id} for
    real-time SSE streaming, or poll GET /api/reviews/{review_id} for status.
    """
    # Validate codebase path exists and is a directory
    codebase = Path(request_body.codebase_path)
    if not codebase.exists():
        raise HTTPException(
            status_code=400, detail=f"Path does not exist: {request_body.codebase_path}"
        )
    if not codebase.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Path is not a directory: {request_body.codebase_path}"
        )

    review_id = str(uuid.uuid4())
    logger.info(
        "Review requested",
        review_id=review_id,
        task=request_body.task[:80],
        codebase_path=request_body.codebase_path,
        scope=request_body.scope,
        model_preset=request_body.model_preset,
    )

    # Register in store immediately so GET /api/reviews/{review_id} returns 200 right away
    review_store.create(
        review_id=review_id,
        task=request_body.task,
        codebase_path=request_body.codebase_path,
        scope=request_body.scope,
        model_preset=request_body.model_preset,
    )

    # Build model router from request params
    preset = ModelPreset(request_body.model_preset)
    overrides = request_body.model_overrides.to_role_dict() if request_body.model_overrides else {}
    available_models = None
    if preset == ModelPreset.FREE:
        try:
            # list_models is metadata discovery only (non-generative, no model call).
            available_models = await session_manager.list_models()
        except Exception as exc:
            logger.warning("Failed to discover models for FREE preset", error=str(exc))
            raise HTTPException(
                status_code=503,
                detail="Unable to discover available models for FREE preset",
            ) from exc

    model_router = ModelRouter(
        preset=preset,
        overrides=overrides,
        available_models=available_models,
    )

    if preset == ModelPreset.FREE and not model_router.has_free_models():
        raise HTTPException(
            status_code=400,
            detail="No free (0x) models are currently available for this account",
        )

    # Build orchestration request
    orch_request = OrchestratorRequest(
        task=request_body.task,
        codebase_path=request_body.codebase_path,
        scope=request_body.scope,
        custom_paths=request_body.custom_paths or [],
        model_preset=request_body.model_preset,
        model_overrides={k.value: v for k, v in overrides.items()},
    )

    # Kick off review as background task
    background_tasks.add_task(
        run_review,
        review_id=review_id,
        request=orch_request,
        event_bus=event_bus,
        session_manager=session_manager,
        model_router=model_router,
        review_store=review_store,
    )

    return ReviewResponse(
        review_id=review_id,
        status="started",
        sse_url=f"/api/events/{review_id}",
    )


@router.get("/reviews", response_model=list[ReviewStatusResponse])
async def list_reviews(
    review_store: ReviewStore = Depends(get_review_store),
) -> list[ReviewStatusResponse]:
    """
    List all known reviews (running, complete, or errored), newest first.

    The `synthesis` field is omitted from this listing to keep responses compact.
    Fetch GET /api/reviews/{review_id} to retrieve the full synthesis text.
    """
    return [
        ReviewStatusResponse(
            review_id=s.review_id,
            status=s.status,
            task=s.task,
            codebase_path=s.codebase_path,
            scope=s.scope,
            model_preset=s.model_preset,
            started_at=s.started_at,
            completed_at=s.completed_at,
            duration_ms=s.duration_ms,
            synthesis=None,  # omitted from list; fetch individual review for full text
            error=s.error,
            sse_url=f"/api/events/{s.review_id}",
        )
        for s in review_store.list_all()
    ]


@router.get("/reviews/{review_id}", response_model=ReviewStatusResponse)
async def get_review(
    review_id: str,
    review_store: ReviewStore = Depends(get_review_store),
) -> ReviewStatusResponse:
    """
    Get the status and result of a specific review.

    - `status: "running"` — review is in progress; poll again or subscribe to SSE.
    - `status: "complete"` — `synthesis` contains the full final report.
    - `status: "error"` — `error` contains the failure message.

    The SSE stream (`sse_url`) remains available for the process lifetime regardless
    of status, but will return an empty stream if the review has already ended.
    """
    state = review_store.get(review_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Review not found: {review_id}")

    return ReviewStatusResponse(
        review_id=state.review_id,
        status=state.status,
        task=state.task,
        codebase_path=state.codebase_path,
        scope=state.scope,
        model_preset=state.model_preset,
        started_at=state.started_at,
        completed_at=state.completed_at,
        duration_ms=state.duration_ms,
        synthesis=state.synthesis,
        error=state.error,
        sse_url=f"/api/events/{review_id}",
    )
