"""Application service for cached, single-news summaries."""

from dataclasses import dataclass

from app.ai.summarization import build_content_hash, build_summary_cache_key
from app.ai.summarization.cache import CacheStatus, SummaryCache
from app.ai.summarization.gateway import SummaryGateway, SummaryProviderUnavailable


@dataclass(frozen=True)
class NewsSummaryResult:
    summary: str
    cache_status: CacheStatus


class NewsSummaryService:
    def __init__(self, *, cache: SummaryCache, gateway: SummaryGateway):
        self._cache = cache
        self._gateway = gateway

    async def summarize(self, news_id: int, title: str, content: str) -> NewsSummaryResult:
        content_hash = build_content_hash(title, content)
        cache_key = build_summary_cache_key(news_id, content_hash)
        lookup = await self._cache.get(cache_key)
        if lookup.status == "hit":
            return NewsSummaryResult(summary=lookup.summary or "", cache_status="hit")

        try:
            summary = await self._gateway.summarize(title, content)
        except SummaryProviderUnavailable:
            raise
        except Exception as exc:
            raise SummaryProviderUnavailable("模型服务暂时不可用") from exc

        if not isinstance(summary, str) or not summary.strip():
            raise SummaryProviderUnavailable("模型返回了空摘要")
        summary = summary.strip()

        cache_written = await self._cache.set(cache_key, summary)
        cache_status: CacheStatus = "miss" if lookup.status == "miss" and cache_written else "unavailable"
        return NewsSummaryResult(summary=summary, cache_status=cache_status)
