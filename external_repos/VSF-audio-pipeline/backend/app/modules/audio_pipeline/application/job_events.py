from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from typing import Any

from app.modules.audio_pipeline.api.schemas import JobRead, StageTimingItem
from app.modules.audio_pipeline.domain.models import PipelineJob, PipelineStageTiming


class JobEventBroker:
    def __init__(self) -> None:
        self._subscribers: set[tuple[asyncio.Queue[str], asyncio.AbstractEventLoop]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> tuple[asyncio.Queue[str], asyncio.AbstractEventLoop]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subscribers.add((queue, loop))
        return queue, loop

    def unsubscribe(self, queue: asyncio.Queue[str], loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._subscribers.discard((queue, loop))

    def publish(self, payload: dict[str, Any]) -> None:
        message = f"event: job\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        with self._lock:
            subscribers = list(self._subscribers)
        for queue, loop in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, message)

    async def stream(self) -> AsyncIterator[str]:
        queue, loop = self.subscribe()
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self.unsubscribe(queue, loop)


job_event_broker = JobEventBroker()


def publish_job_event(event_type: str, job: PipelineJob) -> None:
    payload = {
        "type": event_type,
        "job": JobRead.model_validate(job).model_dump(mode="json"),
    }
    job_event_broker.publish(payload)


def publish_timing_event(timing: PipelineStageTiming) -> None:
    # Đẩy một dòng timing live qua cùng stream /jobs/events (type=stage_timing).
    payload = {
        "type": "stage_timing",
        "timing": StageTimingItem.model_validate(timing).model_dump(mode="json"),
    }
    job_event_broker.publish(payload)
