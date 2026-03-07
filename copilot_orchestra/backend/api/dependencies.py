"""
FastAPI dependency injection helpers.

These functions extract shared application state from app.state
and make it available to route handlers via Depends().
"""

from fastapi import Request

from backend.orchestration.event_bus import EventBus
from backend.orchestration.review_store import ReviewStore
from backend.orchestration.session_manager import SessionManager


def get_session_manager(request: Request) -> SessionManager:
    return request.app.state.session_manager


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_review_store(request: Request) -> ReviewStore:
    return request.app.state.review_store
