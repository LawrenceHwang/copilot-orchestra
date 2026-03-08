"""
Shared pytest fixtures for Copilot Orchestra tests.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def tmp_codebase(tmp_path: Path) -> Path:
    """
    Create a minimal fake codebase for tool tests.

    Returns a SUBDIRECTORY of tmp_path so that tmp_path itself can be used
    as an 'outside' location for symlink-escape tests.
    """
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    (codebase / "src").mkdir()
    (codebase / "src" / "backend").mkdir()
    (codebase / "src" / "backend" / "auth.py").write_text(
        "import os\ndef login(password): return os.system(f'echo {password}')\n"
    )
    (codebase / "src" / "backend" / "main.py").write_text("def add(a, b): return a + b\n" * 50)
    (codebase / "README.md").write_text("# Test Repo\n")
    (codebase / "requirements.txt").write_text("requests==2.28.0\n")
    return codebase


@pytest.fixture
def mock_copilot_session() -> MagicMock:
    """A mock CopilotSession that does nothing."""
    session = MagicMock()
    session.session_id = "test-session-id"
    session.send_and_wait = AsyncMock(return_value=None)
    session.send = AsyncMock(return_value="msg-id")
    session.destroy = AsyncMock()
    session.on = MagicMock(return_value=lambda: None)
    return session


@pytest.fixture
def mock_session_manager(mock_copilot_session: MagicMock) -> MagicMock:
    """A mock SessionManager that returns mock sessions."""
    manager = MagicMock()
    manager.create_session = AsyncMock(return_value=mock_copilot_session)
    manager.list_models = AsyncMock(return_value=[])
    return manager
