"""
FastAPI application entry point.

Creates the app, configures middleware, registers routes, and manages
the Copilot client lifecycle via the FastAPI lifespan context manager.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import models as models_router
from backend.api.routes import reviews as reviews_router
from backend.api.routes import sse as sse_router
from backend.config import Settings, get_settings
from backend.logging_config import configure_logging, get_logger
from backend.orchestration.event_bus import EventBus
from backend.orchestration.review_store import ReviewStore
from backend.orchestration.session_manager import SessionManager
from backend.sdk_compat import apply_enterprise_sdk_patches

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and shutdown of the Copilot client."""
    settings: Settings = app.state.settings

    configure_logging(log_level=settings.log_level, debug=settings.debug)
    apply_enterprise_sdk_patches()
    logger.info("Copilot Orchestra starting", **settings.safe_repr())

    session_manager = SessionManager(settings)
    event_bus = EventBus()
    review_store = ReviewStore()

    await session_manager.start()

    app.state.session_manager = session_manager
    app.state.event_bus = event_bus
    app.state.review_store = review_store

    logger.info("Application ready")
    yield

    logger.info("Application shutting down")
    await session_manager.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Factory function — creates and configures the FastAPI application.

    Accepts optional settings for testing (avoids loading .env in tests).
    """
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Copilot Orchestra",
        description="Multi-agent AI code review platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.state.settings = settings

    # CORS — allow the Vite dev server and any configured origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes — all prefixed with /api
    app.include_router(reviews_router.router, prefix="/api", tags=["reviews"])
    app.include_router(models_router.router, prefix="/api", tags=["models"])
    app.include_router(sse_router.router, prefix="/api", tags=["events"])

    return app


# Application instance used by uvicorn
app = create_app()
