"""LangGraph Redis checkpointer lifecycle and server-side thread isolation."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from langgraph.checkpoint.redis.aio import AsyncRedisSaver


logger = logging.getLogger(__name__)


class AgentThreadIdFactory:
    """Derive an internal LangGraph thread id from trusted identity data."""

    _PREFIX = "news-agent:v2"

    @classmethod
    def derive(cls, user_id: int, conversation_id: str) -> str:
        conversation_uuid = UUID(str(conversation_id))
        return f"{cls._PREFIX}:user:{int(user_id)}:conversation:{conversation_uuid}"

    @classmethod
    def config(cls, user_id: int, conversation_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": cls.derive(user_id, conversation_id)}}


class RedisCheckpointManager:
    """Own and health-check one application-wide async Redis checkpointer."""

    def __init__(
        self,
        redis_url: str,
        *,
        ttl_seconds: int,
        saver_factory: Callable[[str, int], Any] | None = None,
    ):
        self._redis_url = redis_url
        self._ttl_seconds = ttl_seconds
        self._saver_factory = saver_factory or self._default_saver_factory
        self._checkpointer: Any | None = None
        self._available = False
        self._initialized = False
        self._lock = asyncio.Lock()

    @staticmethod
    def _default_saver_factory(redis_url: str, ttl_seconds: int) -> AsyncRedisSaver:
        return AsyncRedisSaver(
            redis_url,
            connection_args={
                "socket_connect_timeout": 1,
                "socket_timeout": 1,
                "retry_on_timeout": False,
            },
            ttl={
                "default_ttl": ttl_seconds / 60,
                "refresh_on_read": True,
            },
        )

    @property
    def available(self) -> bool:
        return self._available

    @property
    def checkpointer(self) -> Any | None:
        return self._checkpointer if self._available else None

    async def initialize(self) -> bool:
        """Initialize indexes exactly once; failures produce stateless mode."""
        async with self._lock:
            if self._initialized:
                return self._available

            self._initialized = True
            try:
                saver = self._saver_factory(self._redis_url, self._ttl_seconds)
                self._checkpointer = await saver.__aenter__()
                self._available = True
                return True
            except Exception:
                logger.exception("Agent Redis checkpointer initialization failed")
                self._checkpointer = None
                self._available = False
                return False

    async def close(self) -> None:
        async with self._lock:
            if self._checkpointer is None:
                return
            try:
                await self._checkpointer.__aexit__(None, None, None)
            finally:
                self._checkpointer = None
                self._available = False

    async def delete_thread(self, user_id: int, conversation_id: str) -> bool:
        """Delete one authenticated user's thread through the public saver API."""
        checkpointer = self.checkpointer
        if checkpointer is None:
            return False
        try:
            await checkpointer.adelete_thread(
                AgentThreadIdFactory.derive(user_id, conversation_id),
            )
            return True
        except Exception:
            logger.exception("Agent checkpointer thread deletion failed")
            return False
