"""Application facade around LangGraph's persisted short-term state."""

import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.ai.agent.checkpointer import AgentThreadIdFactory
from app.ai.agent.memory_store import MemoryStatus


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentMemorySession:
    status: MemoryStatus
    config: dict[str, Any]
    checkpointer: Any | None = None


class CheckpointerMemoryRuntime:
    """Load status and config without accepting client-supplied history."""

    def __init__(self, checkpointer_provider: Callable[[], Any | None]):
        self._checkpointer_provider = checkpointer_provider

    async def prepare(self, user_id: int, conversation_id: str) -> AgentMemorySession:
        checkpointer = self._checkpointer_provider()
        if checkpointer is None:
            return AgentMemorySession(MemoryStatus.UNAVAILABLE, {}, None)

        config = AgentThreadIdFactory.config(user_id, conversation_id)
        try:
            checkpoint = await checkpointer.aget_tuple(config)
        except Exception:
            logger.exception("Agent checkpointer read failed")
            return AgentMemorySession(MemoryStatus.UNAVAILABLE, {}, None)

        status = MemoryStatus.LOADED if checkpoint is not None else MemoryStatus.EMPTY
        return AgentMemorySession(status, config, checkpointer)

    async def verify_saved(self, session: AgentMemorySession) -> MemoryStatus:
        if session.status is MemoryStatus.UNAVAILABLE or session.checkpointer is None:
            return MemoryStatus.UNAVAILABLE
        try:
            checkpoint = await session.checkpointer.aget_tuple(session.config)
        except Exception:
            logger.exception("Agent checkpointer write verification failed")
            return MemoryStatus.UNAVAILABLE
        return MemoryStatus.LOADED if checkpoint is not None else MemoryStatus.UNAVAILABLE
