"""
GET /api/events/{review_id} — Server-Sent Events stream for a review.

The client opens an EventSource connection. Events are delivered as JSON
objects. The stream closes when a stream.end event is received.
"""

import asyncio
import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.api.dependencies import get_event_bus
from backend.logging_config import get_logger
from backend.orchestration.event_bus import EventBus

router = APIRouter()
logger = get_logger("api.sse")

HEARTBEAT_INTERVAL = 30.0  # seconds between keepalive comments


@router.get("/events/{review_id}")
async def stream_events(
    review_id: str,
    request: Request,
    event_bus: EventBus = Depends(get_event_bus),
) -> StreamingResponse:
    """
    SSE stream for a specific review.

    Delivers all events published to the EventBus for review_id until
    the stream.end sentinel is received or the client disconnects.
    """
    logger.info("SSE connection opened", review_id=review_id)

    return StreamingResponse(
        _event_generator(review_id, event_bus, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


async def _event_generator(
    review_id: str,
    event_bus: EventBus,
    request: Request,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted strings from the EventBus."""
    queue = event_bus.subscribe(review_id)
    logger.debug("SSE generator started", review_id=review_id)

    try:
        while True:
            # Check if client has disconnected
            if await request.is_disconnected():
                logger.info("SSE client disconnected", review_id=review_id)
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                # Send SSE comment as keepalive (transparent to EventSource)
                yield ": heartbeat\n\n"
                continue

            # Serialize and yield
            yield f"data: {json.dumps(event)}\n\n"

            # Close stream on sentinel
            if event.get("type") == "stream.end":
                logger.info("SSE stream ended", review_id=review_id)
                break

    except asyncio.CancelledError:
        logger.info("SSE generator cancelled", review_id=review_id)

    finally:
        event_bus.unsubscribe(review_id, queue)
        logger.debug("SSE generator cleaned up", review_id=review_id)
