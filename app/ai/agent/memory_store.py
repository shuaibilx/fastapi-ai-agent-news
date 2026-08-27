"""Redis-backed storage for bounded agent conversation turns."""

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Protocol

from app.ai.agent.memory import ConversationTurn


logger = logging.getLogger(__name__)


class MemoryStatus(str, Enum):
    LOADED = "loaded"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class MemoryLoadResult:
    turns: list[ConversationTurn]
    status: MemoryStatus


class RedisMemoryClient(Protocol):
    async def lrange(self, key: str, start: int, end: int) -> list[str]: ...
    async def expire(self, key: str, seconds: int) -> bool: ...
    def pipeline(self, transaction: bool = True): ...


class ConversationMemoryStore:
    def __init__(
        self,
        redis_client: RedisMemoryClient,
        *,
        ttl_seconds: int,
        max_rounds: int = 5,
    ):
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._max_rounds = max_rounds

    @staticmethod
    def key(user_id: int, conversation_id: str) -> str:
        return f"ai:agent:memory:v1:{user_id}:{conversation_id}"

    async def load(self, user_id: int, conversation_id: str) -> MemoryLoadResult:
        key = self.key(user_id, conversation_id)
        try:
            values = await self._redis.lrange(key, 0, -1)
            if not values:
                return MemoryLoadResult(turns=[], status=MemoryStatus.EMPTY)
            await self._redis.expire(key, self._ttl_seconds)
            turns = [ConversationTurn(**json.loads(value)) for value in values]
            return MemoryLoadResult(turns=turns, status=MemoryStatus.LOADED)
        except Exception:
            logger.exception("Agent conversation memory load failed")
            return MemoryLoadResult(turns=[], status=MemoryStatus.UNAVAILABLE)

    async def append(
        self,
        user_id: int,
        conversation_id: str,
        turn: ConversationTurn,
    ) -> MemoryStatus:
        key = self.key(user_id, conversation_id)
        payload = json.dumps(asdict(turn), ensure_ascii=False)
        try:
            pipeline = self._redis.pipeline(transaction=True)
            pipeline.rpush(key, payload)
            pipeline.ltrim(key, -self._max_rounds, -1)
            pipeline.expire(key, self._ttl_seconds)
            await pipeline.execute()
            return MemoryStatus.LOADED
        except Exception:
            logger.exception("Agent conversation memory append failed")
            return MemoryStatus.UNAVAILABLE
