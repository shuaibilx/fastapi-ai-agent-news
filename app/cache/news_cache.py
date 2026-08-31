"""Versioned Redis Cache-Aside support for news reads."""

import json
import logging
import random
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from app.core.cache import redis_client
from app.core.config import get_settings
from app.schemas.news import NewsPageCachePayload


logger = logging.getLogger(__name__)


class NewsCache:
    """Own the generation keys and versioned payloads for public news reads."""

    def __init__(
        self,
        client: Any,
        *,
        category_ttl_seconds: int = 7200,
        page_ttl_seconds: int = 1800,
        empty_page_ttl_seconds: int = 60,
        ttl_jitter_seconds: int = 180,
        ttl_jitter: Callable[[int], int] | None = None,
    ) -> None:
        self._client = client
        self._category_ttl_seconds = category_ttl_seconds
        self._page_ttl_seconds = page_ttl_seconds
        self._empty_page_ttl_seconds = empty_page_ttl_seconds
        self._ttl_jitter_seconds = ttl_jitter_seconds
        self._ttl_jitter = ttl_jitter or self._jitter_ttl

    def _jitter_ttl(self, ttl_seconds: int) -> int:
        return ttl_seconds + random.randint(0, self._ttl_jitter_seconds)

    @staticmethod
    def news_generation_key(category_id: int) -> str:
        return f"news:cache:category:{category_id}:generation"

    @staticmethod
    def category_generation_key() -> str:
        return "news:cache:categories:generation"

    @staticmethod
    def news_page_key(category_id: int, generation: int, page: int, page_size: int) -> str:
        return f"news:list:v2:{category_id}:g{generation}:p{page}:s{page_size}"

    @staticmethod
    def categories_key(generation: int, skip: int, limit: int) -> str:
        return f"news:categories:v2:g{generation}:skip{skip}:limit{limit}"

    async def news_generation(self, category_id: int) -> int | None:
        return await self._generation(self.news_generation_key(category_id))

    async def categories_generation(self) -> int | None:
        return await self._generation(self.category_generation_key())

    async def _generation(self, key: str) -> int | None:
        try:
            value = await self._client.get(key)
            if value is None:
                await self._client.set(key, "1", nx=True)
                value = await self._client.get(key)
            return int(value or 1)
        except Exception:
            logger.warning("News cache generation read failed", exc_info=True)
            return None

    async def invalidate_news_categories(self, category_ids: Iterable[int]) -> dict[int, int] | None:
        try:
            return {
                category_id: int(await self._client.incr(self.news_generation_key(category_id)))
                for category_id in set(category_ids)
            }
        except Exception:
            logger.warning("News page cache invalidation failed", exc_info=True)
            return None

    async def invalidate_categories(self) -> int | None:
        try:
            return int(await self._client.incr(self.category_generation_key()))
        except Exception:
            logger.warning("News category cache invalidation failed", exc_info=True)
            return None

    async def get_categories(
        self, generation: int, skip: int, limit: int,
    ) -> list[dict[str, Any]] | None:
        try:
            raw = await self._client.get(self.categories_key(generation, skip, limit))
            if not raw:
                return None
            payload = json.loads(raw)
            return payload if isinstance(payload, list) else None
        except Exception:
            logger.warning("News category cache read failed", exc_info=True)
            return None

    async def set_categories(
        self, generation: int, skip: int, limit: int, categories: list[dict[str, Any]],
    ) -> bool:
        try:
            await self._client.setex(
                self.categories_key(generation, skip, limit),
                self._ttl_jitter(self._category_ttl_seconds),
                json.dumps(categories, ensure_ascii=False),
            )
            return True
        except Exception:
            logger.warning("News category cache write failed", exc_info=True)
            return False

    async def get_news_page(
        self, category_id: int, generation: int, page: int, page_size: int,
    ) -> NewsPageCachePayload | None:
        try:
            raw = await self._client.get(self.news_page_key(category_id, generation, page, page_size))
            if not raw:
                return None
            return NewsPageCachePayload.model_validate(json.loads(raw))
        except Exception:
            logger.warning("News page cache read failed", exc_info=True)
            return None

    async def set_news_page(
        self,
        category_id: int,
        generation: int,
        page: int,
        page_size: int,
        payload: NewsPageCachePayload,
    ) -> bool:
        ttl = self._empty_page_ttl_seconds if not payload.list else self._page_ttl_seconds
        try:
            await self._client.setex(
                self.news_page_key(category_id, generation, page, page_size),
                self._ttl_jitter(ttl),
                payload.model_dump_json(by_alias=True),
            )
            return True
        except Exception:
            logger.warning("News page cache write failed", exc_info=True)
            return False


class NewsCacheInvalidator:
    """Post-commit cache coordination boundary for news and category writes."""

    def __init__(self, cache: NewsCache) -> None:
        self._cache = cache

    async def after_news_commit(
        self,
        *,
        previous_category_id: int | None,
        current_category_id: int | None,
    ) -> dict[int, int] | None:
        category_ids = {
            category_id
            for category_id in (previous_category_id, current_category_id)
            if category_id is not None
        }
        if not category_ids:
            return {}
        return await self._cache.invalidate_news_categories(category_ids)

    async def after_category_commit(self) -> int | None:
        return await self._cache.invalidate_categories()

    async def commit_news_write(
        self,
        db: Any,
        write: Callable[[], Awaitable[Any]],
        *,
        previous_category_id: int | None,
        current_category_id: int | None,
    ) -> Any:
        """Commit a future news write before exposing its cache invalidation."""
        try:
            result = await write()
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        await self.after_news_commit(
            previous_category_id=previous_category_id,
            current_category_id=current_category_id,
        )
        return result


def get_news_cache() -> NewsCache:
    settings = get_settings()
    return NewsCache(
        redis_client,
        category_ttl_seconds=settings.news_category_cache_ttl_seconds,
        page_ttl_seconds=settings.news_list_cache_ttl_seconds,
        empty_page_ttl_seconds=settings.news_list_empty_cache_ttl_seconds,
        ttl_jitter_seconds=settings.news_cache_ttl_jitter_seconds,
    )
