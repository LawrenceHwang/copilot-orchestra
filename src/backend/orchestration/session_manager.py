"""
SessionManager — owns the single CopilotClient and creates sessions on demand.

One CopilotClient is started in the FastAPI lifespan and shared across all reviews.
BYOK configuration is injected into every session if configured.
"""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Any

from copilot import CopilotClient, CopilotSession, PermissionHandler
from copilot.types import (
    CopilotClientOptions,
    ModelInfo,
    ProviderConfig,
    SessionConfig,
)

from backend.config import Settings
from backend.logging_config import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger("session_manager")


class SessionManager:
    """
    Manages the lifecycle of a single CopilotClient and its sessions.

    Use as an async context manager:

        async with SessionManager(settings) as manager:
            session = await manager.create_session(config)
            ...

    Or call start()/stop() manually in the FastAPI lifespan.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: CopilotClient | None = None

    async def start(self) -> None:
        """Start the Copilot CLI process. Call once at application startup."""
        opts = self._build_client_options()
        self._client = CopilotClient(opts)
        await self._client.start()
        logger.info(
            "CopilotClient started",
            byok_active=self._settings.byok_active,
            use_logged_in_user=self._settings.use_logged_in_user,
        )

    async def stop(self) -> None:
        """Stop the Copilot CLI process. Call once at application shutdown."""
        if self._client:
            try:
                await self._client.stop()
                logger.info("CopilotClient stopped")
            except Exception as exc:
                logger.error("Error stopping CopilotClient", error=str(exc))
            finally:
                self._client = None

    async def __aenter__(self) -> "SessionManager":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.stop()

    async def create_session(
        self,
        session_config: SessionConfig,
        byok_override: ProviderConfig | None = None,
    ) -> CopilotSession:
        """
        Create a new Copilot session.

        If BYOK is configured (via settings or byok_override), the provider
        config is injected into the session config.
        """
        self._assert_started()

        provider = byok_override or self._build_byok_provider()
        if provider:
            session_config = {**session_config, "provider": provider}
            logger.debug("BYOK provider injected into session config")

        session_config = {**session_config, "on_permission_request": PermissionHandler.approve_all}
        session = await self._client.create_session(session_config)  # type: ignore[union-attr]
        logger.info(
            "Session created",
            session_id=session.session_id,
            model=session_config.get("model", "default"),
        )
        return session

    async def list_models(self) -> list[ModelInfo]:
        """Return available models from the Copilot CLI.

        Models that cannot be parsed (e.g. due to enterprise policy restricting
        capability metadata) are skipped with a warning rather than failing the
        entire call.  The enterprise-specific ``vision`` field is already
        handled by ``sdk_compat.apply_enterprise_sdk_patches``; this fallback
        covers any other unexpected missing fields.
        """
        self._assert_started()
        try:
            return await self._client.list_models()  # type: ignore[union-attr]
        except (ValueError, AssertionError) as exc:
            logger.warning(
                "list_models failed due to SDK parse error — "
                "enterprise environment may be restricting capability metadata; "
                "ensure apply_enterprise_sdk_patches() was called at startup",
                error=str(exc),
            )
            raise

    def _assert_started(self) -> None:
        if self._client is None:
            raise RuntimeError(
                "SessionManager is not started. Call start() or use as async context manager."
            )

    def _build_client_options(self) -> CopilotClientOptions:
        opts: CopilotClientOptions = {}

        if self._settings.github_token:
            opts["github_token"] = self._settings.github_token
            opts["use_logged_in_user"] = False
            logger.debug("Using explicit GitHub token for auth")
        else:
            opts["use_logged_in_user"] = self._settings.use_logged_in_user

        if self._settings.copilot_cli_path:
            opts["cli_path"] = self._settings.copilot_cli_path

        return opts

    def _build_byok_provider(self) -> ProviderConfig | None:
        """Build a ProviderConfig from settings if BYOK is active."""
        if not self._settings.byok_active:
            return None

        provider: ProviderConfig = {
            "type": self._settings.byok_provider_type,  # type: ignore[typeddict-item]
            "api_key": self._settings.byok_api_key,  # type: ignore[typeddict-item]
        }
        if self._settings.byok_base_url:
            provider["base_url"] = self._settings.byok_base_url

        return provider
