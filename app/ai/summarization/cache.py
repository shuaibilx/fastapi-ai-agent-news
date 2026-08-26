"""Redis persistence for generated news summaries."""

import json
import logging
from dataclasses import dataclass
from typing import Literal, Protocol


logger = logging.getLogger(__name__)

CacheStatus = Literal["hit", "miss", "unavailable"]


class AsyncRedisClient(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def setex(self, key: str, expire: int, value: str) -> object: ...


@dataclass(frozen=True)
class CacheLookup:
    status: CacheStatus
    summary: str | None = None


class SummaryCache:
    """A cache adapter that makes cache failures explicit to the caller."""

    def __init__(self, redis_client: AsyncRedisClient, ttl_seconds: int):
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    async def get(self, key: str) -> CacheLookup:
        try:
            value = await self._redis.get(key)
            if value is None:
                return CacheLookup(status="miss")
            payload = json.loads(value)
            summary = payload.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError("cached summary is missing or empty")
            return CacheLookup(status="hit", summary=summary)
        except Exception:
            logger.warning("AI summary cache read failed", exc_info=True)
            return CacheLookup(status="unavailable")

    async def set(self, key: str, summary: str) -> bool:
        try:
            await self._redis.setex(
                key,
                self._ttl_seconds,
                json.dumps({"summary": summary}, ensure_ascii=False),
            )
            return True
        except Exception:
            logger.warning("AI summary cache write failed", exc_info=True)
            return False
