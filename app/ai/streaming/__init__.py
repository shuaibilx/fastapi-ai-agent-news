"""Streaming response capability, including SSE."""
"""Public primitives for safe AI Server-Sent Events."""

from app.ai.streaming.events import StreamEvent, StreamProtocolError
from app.ai.streaming.sse import SseEventEncoder, iter_sse_events

__all__ = ["StreamEvent", "StreamProtocolError", "SseEventEncoder", "iter_sse_events"]
