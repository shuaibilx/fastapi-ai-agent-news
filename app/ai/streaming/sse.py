"""SSE serialization, heartbeat, and cancellation coordination."""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from app.ai.streaming.events import StreamEvent, StreamProtocolError, validate_stream_event


class SseEventEncoder:
    def __init__(self) -> None:
        self._completed = False

    def encode(self, event: StreamEvent) -> str:
        if self._completed:
            raise StreamProtocolError("done 事件后不能再输出业务事件")
        validate_stream_event(event)
        if event.name == "done":
            self._completed = True
        payload = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
        return f"event: {event.name}\ndata: {payload}\n\n"


async def _never_disconnected() -> bool:
    return False


async def iter_sse_events(
    events: AsyncIterator[StreamEvent],
    *,
    heartbeat_seconds: float = 15.0,
    is_disconnected: Callable[[], Awaitable[bool]] = _never_disconnected,
) -> AsyncIterator[str]:
    """Encode domain events while preserving source cancellation and heartbeat liveness."""
    encoder = SseEventEncoder()
    iterator = events.__aiter__()
    pending: asyncio.Task[StreamEvent] | None = None
    try:
        while True:
            if await is_disconnected():
                return
            if pending is None:
                pending = asyncio.create_task(anext(iterator))
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_seconds)
            if not done:
                if await is_disconnected():
                    return
                yield encoder.encode(StreamEvent.ping())
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            finally:
                pending = None
            if await is_disconnected():
                return
            yield encoder.encode(event)
            if event.name == "done":
                return
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending
        close = getattr(iterator, "aclose", None)
        if close is not None:
            with contextlib.suppress(Exception):
                await close()
