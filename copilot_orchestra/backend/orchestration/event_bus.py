"""
EventBus — asyncio-based fan-out event bus for real-time SSE streaming.

Multiple SSE connections can subscribe to the same review_id and all receive
every published event. The EventBus is a singleton shared across all reviews.

The TUI layer can also subscribe directly to the EventBus — no HTTP required.
"""

import asyncio
import time
from typing import Any

from backend.logging_config import get_logger

logger = get_logger("event_bus")


class EventBus:
    """
    Thread-safe, asyncio-native fan-out event bus.

    Each review_id has an independent set of subscriber queues.
    Publishing to a review_id delivers the event to all its subscribers.
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, review_id: str) -> asyncio.Queue:
        """
        Subscribe to events for a review. Returns a new asyncio.Queue.

        The caller is responsible for calling unsubscribe() when done to
        prevent memory leaks.
        """
        queue: asyncio.Queue = asyncio.Queue()
        if review_id not in self._queues:
            self._queues[review_id] = []
        self._queues[review_id].append(queue)
        logger.debug(
            "EventBus subscriber added",
            review_id=review_id,
            total_subscribers=len(self._queues[review_id]),
        )
        return queue

    def unsubscribe(self, review_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue. Safe to call if queue is not subscribed."""
        if review_id not in self._queues:
            return
        try:
            self._queues[review_id].remove(queue)
        except ValueError:
            pass
        if not self._queues[review_id]:
            del self._queues[review_id]
        logger.debug("EventBus subscriber removed", review_id=review_id)

    async def publish(self, review_id: str, event: dict[str, Any]) -> None:
        """
        Publish an event to all subscribers of the given review_id.

        This is a non-blocking put (put_nowait) — subscribers must consume
        events promptly to avoid queue growth. For SSE, events are small and
        consumption is immediate.
        """
        subscribers = self._queues.get(review_id, [])
        if not subscribers:
            logger.debug(
                "EventBus publish with no subscribers",
                review_id=review_id,
                event_type=event.get("type"),
            )
            return

        # Stamp the event with a server timestamp if not already present
        if "ts" not in event:
            event = {**event, "ts": int(time.time() * 1000)}

        for queue in list(subscribers):  # snapshot to avoid mutation during iteration
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "EventBus queue full — dropping event",
                    review_id=review_id,
                    event_type=event.get("type"),
                )

    def subscriber_count(self, review_id: str) -> int:
        """Return the number of active subscribers for a review."""
        return len(self._queues.get(review_id, []))
