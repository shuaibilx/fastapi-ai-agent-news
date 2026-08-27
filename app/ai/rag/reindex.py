"""Explicit, repeatable full rebuild of the news semantic index."""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.retrieval import NewsRecord
from app.ai.rag.vector_store import NewsVectorDocument, RedisNewsVectorStore
from app.core.cache import redis_client
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, async_engine
from app.models.news import News


class NewsIndexRebuildUnavailable(RuntimeError):
    """A full rebuild could not produce a coherent news index."""


class NewsIndexSource(Protocol):
    async def list_news(self, offset: int, limit: int) -> list[NewsRecord]: ...


class EmbeddingService(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class NewsVectorStore(Protocol):
    async def replace_documents(self, documents: list[NewsVectorDocument]) -> None: ...


@dataclass(frozen=True)
class NewsIndexRebuildResult:
    scanned_news: int
    indexed_news: int


def build_news_embedding_text(news: NewsRecord) -> str:
    return "\n".join(filter(None, [
        f"标题：{news.title}",
        f"简介：{news.description}" if news.description else None,
        f"正文：{news.content}" if news.content else None,
    ]))


class NewsIndexRebuilder:
    def __init__(
        self,
        *,
        source: NewsIndexSource,
        embedding_service: EmbeddingService,
        vector_store: NewsVectorStore,
        batch_size: int,
    ):
        self._source = source
        self._embedding_service = embedding_service
        self._vector_store = vector_store
        self._batch_size = batch_size

    async def rebuild(self) -> NewsIndexRebuildResult:
        offset = 0
        documents: list[NewsVectorDocument] = []
        while True:
            news_batch = await self._source.list_news(offset, self._batch_size)
            if not news_batch:
                break
            texts = [build_news_embedding_text(news) for news in news_batch]
            embeddings = await self._embedding_service.embed(texts)
            if len(embeddings) != len(news_batch):
                raise NewsIndexRebuildUnavailable("Embedding 结果无法与新闻记录一一对应")
            documents.extend(
                NewsVectorDocument(
                    news_id=news.id,
                    title=news.title,
                    description=news.description,
                    content=news.content,
                    views=news.views,
                    embedding=embedding,
                )
                for news, embedding in zip(news_batch, embeddings, strict=True)
            )
            offset += len(news_batch)
            if len(news_batch) < self._batch_size:
                break

        await self._vector_store.replace_documents(documents)
        return NewsIndexRebuildResult(
            scanned_news=len(documents),
            indexed_news=len(documents),
        )


class SqlNewsIndexSource:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_news(self, offset: int, limit: int) -> list[News]:
        result = await self._db.execute(
            select(News).order_by(News.id).offset(offset).limit(limit)
        )
        return list(result.scalars().all())


async def rebuild_news_index() -> NewsIndexRebuildResult:
    from app.ai.embeddings import TeiEmbeddingClient

    settings = get_settings()
    async with AsyncSessionLocal() as db:
        rebuilder = NewsIndexRebuilder(
            source=SqlNewsIndexSource(db),
            embedding_service=TeiEmbeddingClient(
                base_url=settings.embedding_base_url,
                timeout_seconds=settings.embedding_timeout_seconds,
                vector_dimensions=settings.ai_semantic_vector_dimensions,
            ),
            vector_store=RedisNewsVectorStore(
                redis_client=redis_client,
                index_name=settings.ai_semantic_index_name,
                key_prefix=settings.ai_semantic_key_prefix,
                vector_dimensions=settings.ai_semantic_vector_dimensions,
            ),
            batch_size=settings.ai_semantic_batch_size,
        )
        return await rebuilder.rebuild()


def main() -> None:
    result = asyncio.run(run_rebuild_command())
    print(f"新闻向量索引构建完成：扫描 {result.scanned_news} 篇，写入 {result.indexed_news} 篇。")


async def run_rebuild_command() -> NewsIndexRebuildResult:
    try:
        return await rebuild_news_index()
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    main()
