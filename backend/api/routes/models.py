"""
GET /api/models — list available Copilot models.
GET /api/health — health check.
"""

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_session_manager
from backend.api.schemas import HealthResponse, ModelInfoResponse, ModelListResponse
from backend.config import get_settings
from backend.logging_config import get_logger
from backend.orchestration.session_manager import SessionManager

router = APIRouter()
logger = get_logger("api.models")


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    session_manager: SessionManager = Depends(get_session_manager),
) -> ModelListResponse:
    """Return available Copilot models and BYOK status."""
    settings = get_settings()
    try:
        raw_models = await session_manager.list_models()
        models = [
            ModelInfoResponse(
                id=m.id,
                name=m.name,
                capabilities=m.capabilities.to_dict() if m.capabilities else None,
                policy=m.policy.to_dict() if m.policy else None,
                billing_multiplier=m.billing.multiplier if m.billing else None,
            )
            for m in raw_models
        ]
        logger.debug("Models listed", count=len(models))
    except Exception as exc:
        logger.warning("Failed to list models", error=str(exc))
        models = []

    return ModelListResponse(models=models, byok_active=settings.byok_active)


@router.get("/health", response_model=HealthResponse)
async def health_check(
    session_manager: SessionManager = Depends(get_session_manager),
) -> HealthResponse:
    """Health check endpoint."""
    connected = session_manager._client is not None
    return HealthResponse(status="ok", copilot_connected=connected)
