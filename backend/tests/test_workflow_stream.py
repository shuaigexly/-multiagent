import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_workflow_stream_generator_stops_after_max_duration(monkeypatch):
    from app.api import workflow

    class FakeSubscription:
        def __init__(self):
            self._items = iter([
                {"event_type": "task.started", "payload": {"stage": "start"}},
                {"event_type": "wave.completed", "payload": {"stage": "next"}},
            ])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._items)
            except StopIteration:
                raise StopAsyncIteration

    def fake_subscribe(_task_record_id: str):
        return FakeSubscription()

    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))

    monkeypatch.setattr(workflow.progress_broker, "subscribe", fake_subscribe)
    monkeypatch.setattr(workflow, "MAX_WORKFLOW_SSE_SECONDS", -1)

    events = [
        item async for item in workflow._workflow_stream_generator("rec_1", request)
    ]

    assert events == []
    request.is_disconnected.assert_awaited_once()


@pytest.mark.asyncio
async def test_progress_broker_preserves_terminal_event_when_subscriber_queue_is_full():
    from app.bitable_workflow import progress_broker

    progress_broker._subscribers.clear()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    await queue.put({"event_type": "agent.token", "payload": {"chunk": "old"}})
    progress_broker._subscribers["rec_1"].append(queue)

    try:
        await progress_broker.publish("rec_1", "task.done", {"stage": "done"})

        msg = queue.get_nowait()
        assert msg["event_type"] == "task.done"
        assert msg["payload"] == {"stage": "done"}
    finally:
        progress_broker._subscribers.clear()
