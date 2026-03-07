"""
Base agent — shared logic for all specialist agents.

Each agent wraps a CopilotSession. Events from the session are translated to
Orchestra SSE events and published to the EventBus.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from copilot import CopilotSession
from copilot.generated.session_events import SessionEventType

from backend.logging_config import get_logger
from backend.orchestration.event_bus import EventBus
from backend.orchestration.model_router import AgentRole

if TYPE_CHECKING:
    from copilot.generated.session_events import SessionEvent

logger = get_logger("agent.base")

# Hybrid timeout parameters for reviewer agents.
# - TOTAL: hard ceiling regardless of activity.
# - LIVENESS: if no SDK event (token, tool call, etc.) arrives within this
#   window the agent is considered stuck and cancelled early.
# - POLL: how often the watchdog checks the liveness clock.
AGENT_TOTAL_TIMEOUT_S: float = 600.0    # 10-min hard ceiling
AGENT_LIVENESS_TIMEOUT_S: float = 90.0  # 90 s idle → stuck
WATCHDOG_POLL_S: float = 10.0


class BaseAgent:
    """
    Wraps a CopilotSession and bridges SDK events → Orchestra EventBus events.

    Subclasses implement system_prompt() and build_user_prompt().
    """

    role: AgentRole  # must be set by subclass

    def __init__(
        self,
        session: CopilotSession,
        event_bus: EventBus,
        review_id: str,
        model: str,
    ) -> None:
        self._session = session
        self._event_bus = event_bus
        self._review_id = review_id
        self._model = model
        self._log = get_logger("agent", role=self.role.value, review_id=review_id)
        self._metrics: dict[str, Any] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost": 0.0,
        }

    async def run(self, files: list[str], focus: str) -> str:
        """
        Run the agent: send the review prompt and return the final result text.

        Uses a hybrid timeout: a hard ceiling (AGENT_TOTAL_TIMEOUT_S) combined
        with a liveness watchdog (AGENT_LIVENESS_TIMEOUT_S) that fires if no
        SDK event arrives for a sustained period, catching stuck agents early.

        Events are published to the EventBus throughout execution.
        """
        start_time = time.monotonic()
        self._last_activity = start_time
        self._log.info("Agent starting", files=len(files), focus=focus[:100])

        await self._publish(
            {"type": "agent.started", "agent": self.role.value, "model": self._model}
        )

        # Wire up the event handler
        unsubscribe = self._session.on(self._handle_sdk_event)

        try:
            prompt = self._build_prompt(files, focus)

            async def _run_session() -> Any:
                # Pass the hard-ceiling timeout so the SDK doesn't abort during
                # the silent reasoning phase of deep-thinking models (default is 60 s).
                return await self._session.send_and_wait(
                    {"prompt": prompt}, timeout=AGENT_TOTAL_TIMEOUT_S
                )

            async def _watchdog() -> str:
                """Return 'liveness' or 'total' when a timeout condition fires."""
                deadline = start_time + AGENT_TOTAL_TIMEOUT_S
                while True:
                    await asyncio.sleep(WATCHDOG_POLL_S)
                    now = time.monotonic()
                    if now >= deadline:
                        return "total"
                    if now - self._last_activity > AGENT_LIVENESS_TIMEOUT_S:
                        return "liveness"

            session_task = asyncio.create_task(_run_session())
            watchdog_task = asyncio.create_task(_watchdog())

            done, pending = await asyncio.wait(
                [session_task, watchdog_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

            # If the session didn't finish, the watchdog fired.
            if session_task not in done:
                reason = watchdog_task.result()
                elapsed = int(time.monotonic() - start_time)
                idle = int(time.monotonic() - self._last_activity)
                if reason == "liveness":
                    raise asyncio.TimeoutError(
                        f"No activity for {idle}s (elapsed {elapsed}s) — agent appears stuck"
                    )
                raise asyncio.TimeoutError(
                    f"Exceeded hard timeout of {int(AGENT_TOTAL_TIMEOUT_S)}s"
                )

            event = session_task.result()
            result = ""
            if event and event.data.content:
                result = event.data.content

            duration_ms = int((time.monotonic() - start_time) * 1000)
            self._log.info("Agent done", duration_ms=duration_ms, result_len=len(result))

            await self._publish(
                {"type": "agent.done", "agent": self.role.value, "duration_ms": duration_ms}
            )
            return result

        except asyncio.TimeoutError as exc:
            msg = f"Agent {self.role.value} timed out: {exc}"
            self._log.error(msg)
            await self._publish({"type": "agent.error", "agent": self.role.value, "error": msg})
            return f"[{self.role.value} review timed out]"

        except Exception as exc:
            msg = str(exc)
            self._log.error("Agent failed", error=msg, exc_info=True)
            await self._publish({"type": "agent.error", "agent": self.role.value, "error": msg})
            return f"[{self.role.value} review failed: {msg}]"

        finally:
            unsubscribe()
            await self._session.destroy()

    def _handle_sdk_event(self, event: "SessionEvent") -> None:
        """Translate Copilot SDK events into Orchestra events and publish them."""
        asyncio.get_event_loop().call_soon_threadsafe(
            asyncio.ensure_future,
            self._async_handle_sdk_event(event),
        )

    async def _async_handle_sdk_event(self, event: "SessionEvent") -> None:
        """Async translation of SDK events to Orchestra events."""
        # Any incoming event resets the liveness clock.
        self._last_activity = time.monotonic()
        etype = event.type

        if etype in (
            SessionEventType.ASSISTANT_REASONING,
            SessionEventType.ASSISTANT_REASONING_DELTA,
        ):
            # Deep-thinking models emit reasoning events during their silent
            # thinking phase — these reset the liveness clock so the watchdog
            # does not mistake reasoning for being stuck.
            await self._publish({
                "type": "agent.thinking",
                "agent": self.role.value,
            })

        elif etype == SessionEventType.ASSISTANT_MESSAGE_DELTA:
            if event.data.delta_content:
                await self._publish({
                    "type": "agent.stream",
                    "agent": self.role.value,
                    "content": event.data.delta_content,
                })

        elif etype == SessionEventType.ASSISTANT_MESSAGE:
            if event.data.content:
                await self._publish({
                    "type": "agent.message",
                    "agent": self.role.value,
                    "content": event.data.content,
                })

        elif etype == SessionEventType.TOOL_EXECUTION_START:
            await self._publish({
                "type": "agent.tool_call",
                "agent": self.role.value,
                "tool_name": event.data.tool_name or "unknown",
                "tool_call_id": event.data.tool_call_id or "",
                "args": event.data.arguments,
            })

        elif etype == SessionEventType.TOOL_EXECUTION_COMPLETE:
            await self._publish({
                "type": "agent.tool_result",
                "agent": self.role.value,
                "tool_name": event.data.tool_name or "unknown",
                "tool_call_id": event.data.tool_call_id or "",
                "success": True,
            })

        elif etype == SessionEventType.ASSISTANT_USAGE:
            # Real token counts from the API response
            self._metrics["input_tokens"] += event.data.input_tokens or 0
            self._metrics["output_tokens"] += event.data.output_tokens or 0
            self._metrics["cache_read_tokens"] += event.data.cache_read_tokens or 0
            self._metrics["cache_write_tokens"] += event.data.cache_write_tokens or 0
            self._metrics["cost"] += event.data.cost or 0.0

            quota: dict[str, Any] = {}
            if event.data.quota_snapshots:
                for snap in event.data.quota_snapshots.values():
                    quota = {
                        "used_requests": snap.used_requests,
                        "entitlement_requests": snap.entitlement_requests,
                        "remaining_percentage": snap.remaining_percentage,
                        "is_unlimited": snap.is_unlimited_entitlement,
                    }
                    break  # take first snapshot

            await self._publish({
                "type": "metrics.update",
                "agent": self.role.value,
                "model": event.data.model or self._model,
                **self._metrics,
                "quota": quota,
            })

        elif etype == SessionEventType.SESSION_ERROR:
            error_msg = ""
            if event.data.error:
                error_msg = (
                    event.data.error.message
                    if hasattr(event.data.error, "message")
                    else str(event.data.error)
                )
            self._log.error("SDK session error", error=error_msg)

    async def _publish(self, event: dict[str, Any]) -> None:
        event = {**event, "review_id": self._review_id}
        await self._event_bus.publish(self._review_id, event)

    def _build_prompt(self, files: list[str], focus: str) -> str:
        """Build the review prompt. Override in subclasses for customization."""
        files_list = "\n".join(f"- {f}" for f in files) if files else "- (entire codebase)"
        return (
            f"Review the following files:\n{files_list}\n\n"
            f"Focus area: {focus}\n\n"
            f"Use the read_file and list_directory tools to read the files, "
            f"then provide your structured review."
        )
