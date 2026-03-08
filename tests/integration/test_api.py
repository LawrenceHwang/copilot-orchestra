"""
Integration tests for the FastAPI endpoints.

These tests mock the SessionManager to avoid requiring a real Copilot CLI.
Tests marked @pytest.mark.integration require a live CLI and are skipped by default.

Run with: uv run pytest tests/integration -v
Skip with: uv run pytest -m "not integration" -v
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from backend.main import create_app
from backend.orchestration.event_bus import EventBus


@pytest.fixture
def mock_session_manager():
    manager = MagicMock()
    manager.list_models = AsyncMock(
        return_value=[
            MagicMock(
                id="claude-sonnet-4-6",
                name="Claude Sonnet 4.6",
                capabilities=MagicMock(
                    to_dict=lambda: {"supports": {"vision": True, "reasoningEffort": False},
                                    "limits": {"maxPromptTokens": 200000}}
                ),
                policy=None,
                billing=None,
            )
        ]
    )
    manager.create_session = AsyncMock()
    return manager


@pytest.fixture
def app(mock_session_manager):
    application = create_app()
    application.state.session_manager = mock_session_manager
    application.state.event_bus = EventBus()
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestModelsEndpoint:
    def test_list_models_returns_list(self, client):
        response = client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert isinstance(data["models"], list)

    def test_list_models_includes_byok_flag(self, client):
        response = client.get("/api/models")
        data = response.json()
        assert "byok_active" in data


class TestReviewEndpoint:
    def test_start_review_returns_review_id(self, client, tmp_codebase):
        response = client.post(
            "/api/reviews",
            json={
                "task": "Review this codebase for security and performance issues",
                "codebase_path": str(tmp_codebase),
                "scope": "full",
                "model_preset": "balanced",
            },
        )
        assert response.status_code == 202
        data = response.json()
        assert "review_id" in data
        assert data["status"] == "started"
        assert "sse_url" in data

    def test_start_review_with_invalid_path_returns_400(self, client):
        response = client.post(
            "/api/reviews",
            json={
                "task": "Review this codebase",
                "codebase_path": "/nonexistent/path/that/does/not/exist",
            },
        )
        assert response.status_code == 400

    def test_start_review_with_too_short_task_returns_422(self, client, tmp_codebase):
        response = client.post(
            "/api/reviews",
            json={
                "task": "short",  # < 10 chars
                "codebase_path": str(tmp_codebase),
            },
        )
        assert response.status_code == 422

    def test_start_review_with_custom_scope_requires_paths(self, client, tmp_codebase):
        response = client.post(
            "/api/reviews",
            json={
                "task": "Review this codebase for issues",
                "codebase_path": str(tmp_codebase),
                "scope": "custom",
                "custom_paths": [],  # empty custom_paths with custom scope
            },
        )
        assert response.status_code == 422

    def test_start_review_with_model_overrides(self, client, tmp_codebase):
        response = client.post(
            "/api/reviews",
            json={
                "task": "Review this codebase for security and performance issues",
                "codebase_path": str(tmp_codebase),
                "model_preset": "balanced",
                "model_overrides": {
                    "security": "claude-opus-4-6",
                    "readability": "claude-haiku-4-5-20251001",
                },
            },
        )
        assert response.status_code == 202

    def test_start_review_returns_sse_url(self, client, tmp_codebase):
        response = client.post(
            "/api/reviews",
            json={
                "task": "Review this codebase for security issues please",
                "codebase_path": str(tmp_codebase),
            },
        )
        data = response.json()
        assert data["sse_url"].startswith("/api/events/")


@pytest.mark.integration
class TestSSEStream:
    """These tests require a real Copilot CLI. Skipped by default."""

    async def test_sse_stream_delivers_events(self, tmp_codebase):
        """Requires live Copilot CLI."""
        pytest.skip("Requires live Copilot CLI")
