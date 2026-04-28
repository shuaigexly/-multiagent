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
