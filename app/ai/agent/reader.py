"""Adapters from agent read tools to existing application services."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.retrieval import NewsRetrievalService
from app.services import favorite, history, news


class SqlAgentReader:
    def __init__(self, db: AsyncSession, retrieval: NewsRetrievalService):
        self._db = db
        self._retrieval = retrieval

    async def search_news(self, query: str, limit: int):
        return await self._retrieval.search(query, limit)

    async def get_news_detail(self, news_id: int):
        return await news.get_news_detail(self._db, news_id)

    async def list_favorites(self, user_id: int, page: int, page_size: int):
        return await favorite.get_news_favorite(self._db, user_id, page, page_size)

    async def list_history(self, user_id: int, page: int, page_size: int):
        return await history.get_history_list(self._db, user_id, page, page_size)
