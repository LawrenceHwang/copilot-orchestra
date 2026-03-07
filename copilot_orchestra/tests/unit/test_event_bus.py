"""
Unit tests for EventBus — written BEFORE the implementation (TDD).
"""

import asyncio

import pytest

from backend.orchestration.event_bus import EventBus


class TestEventBusSubscription:
    async def test_subscribe_returns_queue(self):
        bus = EventBus()
        queue = bus.subscribe("review-1")
        assert isinstance(queue, asyncio.Queue)

    async def test_multiple_subscribers_get_separate_queues(self):
        bus = EventBus()
        q1 = bus.subscribe("review-1")
        q2 = bus.subscribe("review-1")
        assert q1 is not q2

    async def test_unsubscribe_removes_queue(self):
        bus = EventBus()
        queue = bus.subscribe("review-1")
        bus.unsubscribe("review-1", queue)
        await bus.publish("review-1", {"type": "test"})
        assert queue.empty()

    async def test_unsubscribe_nonexistent_queue_is_safe(self):
        bus = EventBus()
        queue = asyncio.Queue()
        # Should not raise
        bus.unsubscribe("nonexistent-review", queue)

    async def test_unsubscribe_wrong_review_id_is_safe(self):
        bus = EventBus()
        queue = bus.subscribe("review-1")
        bus.unsubscribe("review-99", queue)
        # Queue should still receive events for review-1
        await bus.publish("review-1", {"type": "test"})
        event = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert event["type"] == "test"


class TestEventBusPublishing:
    async def test_publish_delivers_to_subscriber(self):
        bus = EventBus()
        queue = bus.subscribe("review-1")
        await bus.publish("review-1", {"type": "agent.stream", "content": "hello"})
        event = await asyncio.wait_for(queue.get(), timeout=0.5)
        assert event["type"] == "agent.stream"
        assert event["content"] == "hello"

    async def test_publish_delivers_to_all_subscribers(self):
        bus = EventBus()
        q1 = bus.subscribe("review-1")
        q2 = bus.subscribe("review-1")
        q3 = bus.subscribe("review-1")
        await bus.publish("review-1", {"type": "test"})
        for q in [q1, q2, q3]:
            event = await asyncio.wait_for(q.get(), timeout=0.5)
            assert event["type"] == "test"

    async def test_publish_does_not_deliver_to_other_review(self):
        bus = EventBus()
        q1 = bus.subscribe("review-1")
        q2 = bus.subscribe("review-2")
        await bus.publish("review-1", {"type": "test"})
        event = await asyncio.wait_for(q1.get(), timeout=0.5)
        assert event["type"] == "test"
        assert q2.empty()

    async def test_publish_to_unknown_review_is_safe(self):
        bus = EventBus()
        # Should not raise even if no subscribers
        await bus.publish("nonexistent-review", {"type": "test"})

    async def test_multiple_events_are_ordered(self):
        bus = EventBus()
        queue = bus.subscribe("review-1")
        events = [{"type": "test", "seq": i} for i in range(5)]
        for e in events:
            await bus.publish("review-1", e)
        received = []
        for _ in range(5):
            received.append(await asyncio.wait_for(queue.get(), timeout=0.5))
        assert [e["seq"] for e in received] == list(range(5))


class TestEventBusIsolation:
    async def test_separate_review_ids_are_isolated(self):
        bus = EventBus()
        queues = {f"review-{i}": bus.subscribe(f"review-{i}") for i in range(3)}
        await bus.publish("review-1", {"type": "only-review-1"})
        event = await asyncio.wait_for(queues["review-1"].get(), timeout=0.5)
        assert event["type"] == "only-review-1"
        assert queues["review-0"].empty()
        assert queues["review-2"].empty()

    async def test_subscriber_count_is_tracked(self):
        bus = EventBus()
        assert bus.subscriber_count("review-1") == 0
        q = bus.subscribe("review-1")
        assert bus.subscriber_count("review-1") == 1
        bus.unsubscribe("review-1", q)
        assert bus.subscriber_count("review-1") == 0
