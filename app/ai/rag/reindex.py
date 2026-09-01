"""Explicit, build-isolated rebuild of the news Chunk vector index."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import sys
from typing import Protocol, TextIO
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.chunking import BgeTokenCounter, NewsChunk, NewsChunker
from app.ai.rag.retrieval import NewsRecord
from app.ai.rag.vector_store import NewsVectorDocument, RedisNewsVectorStore
from app.core.cache import redis_client
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, async_engine
from app.models.news import News


class NewsIndexRebuildUnavailable(RuntimeError):
    """A rebuild could not produce a complete candidate Chunk index."""


class NewsIndexSource(Protocol):
    async def list_news(self, offset: int, limit: int) -> list[NewsRecord]: ...


class EmbeddingService(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class Chunker(Protocol):
    def split(
        self,
        *,
        news_id: int,
        title: str,
        description: str | None,
        content: str,
    ) -> list[NewsChunk]: ...


class NewsVectorStore(Protocol):
    async def prepare_build(self, build_id: str) -> str: ...
    async def write_documents(
        self,
        build_id: str,
        documents: list[NewsVectorDocument],
    ) -> int: ...
    async def validate_build(
        self,
        build_id: str,
        *,
        expected_documents: int,
        probe_embedding: list[float] | None = None,
    ) -> None: ...
    async def activate_build(self, build_id: str) -> str: ...
    async def discard_build(self, build_id: str) -> None: ...


@dataclass(frozen=True)
class NewsIndexRebuildResult:
    build_id: str
    index_name: str
    scanned_news: int
    generated_chunks: int
    indexed_chunks: int


def _default_build_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


class NewsIndexRebuilder:
    def __init__(
        self,
        *,
        source: NewsIndexSource,
        embedding_service: EmbeddingService,
        vector_store: NewsVectorStore,
        chunker: Chunker,
        batch_size: int,
        build_id_factory: Callable[[], str] = _default_build_id,
    ):
        if batch_size < 1:
            raise ValueError("batch_size 必须大于 0")
        self._source = source
        self._embedding_service = embedding_service
        self._vector_store = vector_store
        self._chunker = chunker
        self._batch_size = batch_size
        self._build_id_factory = build_id_factory

    async def rebuild(self) -> NewsIndexRebuildResult:
        build_id = self._build_id_factory()
        prepared = False
        scanned_news = 0
        generated_chunks = 0
        indexed_chunks = 0
        probe_embedding: list[float] | None = None
        try:
            index_name = await self._vector_store.prepare_build(build_id)
            prepared = True
            offset = 0
            while True:
                news_batch = await self._source.list_news(offset, self._batch_size)
                if not news_batch:
                    break
                scanned_news += len(news_batch)
                chunks = [
                    chunk
                    for news in news_batch
                    for chunk in self._chunker.split(
                        news_id=news.id,
                        title=news.title,
                        description=news.description,
                        content=news.content or "",
                    )
                ]
                generated_chunks += len(chunks)
                news_by_id = {news.id: news for news in news_batch}
                for start in range(0, len(chunks), self._batch_size):
                    chunk_batch = chunks[start:start + self._batch_size]
                    embeddings = await self._embedding_service.embed(
                        [chunk.embedding_text for chunk in chunk_batch]
                    )
                    if len(embeddings) != len(chunk_batch):
                        raise NewsIndexRebuildUnavailable(
                            "Embedding 结果无法与新闻 Chunk 一一对应"
                        )
                    if probe_embedding is None and embeddings:
                        probe_embedding = embeddings[0]
                    documents = [
                        self._to_document(
                            chunk,
                            news_by_id[chunk.news_id],
                            embedding,
                        )
                        for chunk, embedding in zip(chunk_batch, embeddings, strict=True)
                    ]
                    indexed_chunks += await self._vector_store.write_documents(
                        build_id,
                        documents,
                    )
                offset += len(news_batch)
                if len(news_batch) < self._batch_size:
                    break

            if indexed_chunks != generated_chunks:
                raise NewsIndexRebuildUnavailable(
                    "写入的新闻 Chunk 数量与生成数量不一致"
                )
            await self._vector_store.validate_build(
                build_id,
                expected_documents=generated_chunks,
                probe_embedding=probe_embedding,
            )
            index_name = await self._vector_store.activate_build(build_id)
            return NewsIndexRebuildResult(
                build_id=build_id,
                index_name=index_name,
                scanned_news=scanned_news,
                generated_chunks=generated_chunks,
                indexed_chunks=indexed_chunks,
            )
        except Exception as exc:
            if prepared:
                try:
                    await self._vector_store.discard_build(build_id)
                except Exception as cleanup_exc:
                    exc.add_note(f"候选索引清理失败: {cleanup_exc}")
            if isinstance(exc, NewsIndexRebuildUnavailable):
                raise
            raise NewsIndexRebuildUnavailable("新闻 Chunk 索引构建失败") from exc

    @staticmethod
    def _to_document(
        chunk: NewsChunk,
        news: NewsRecord,
        embedding: list[float],
    ) -> NewsVectorDocument:
        publish_time = getattr(news, "publish_time", None)
        return NewsVectorDocument(
            news_id=chunk.news_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            start_index=chunk.start_index,
            end_index=chunk.end_index,
            title=chunk.title,
            description=chunk.description,
            chunk_text=chunk.chunk_text,
            content_hash=chunk.content_hash,
            category_id=int(getattr(news, "category_id", 0)),
            publish_time=(
                publish_time.isoformat()
                if hasattr(publish_time, "isoformat")
                else str(publish_time or "")
            ),
            views=news.views,
            embedding=embedding,
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
    token_counter = BgeTokenCounter(settings.embedding_tokenizer_path)
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
                index_alias=settings.ai_semantic_index_alias,
                index_prefix=settings.ai_semantic_index_prefix,
                key_prefix=settings.ai_semantic_chunk_key_prefix,
                vector_dimensions=settings.ai_semantic_vector_dimensions,
            ),
            chunker=NewsChunker(
                token_counter=token_counter,
                chunk_size_tokens=settings.ai_semantic_chunk_size_tokens,
                chunk_overlap_tokens=settings.ai_semantic_chunk_overlap_tokens,
                embedding_input_max_tokens=settings.ai_semantic_embedding_input_max_tokens,
            ),
            batch_size=settings.ai_semantic_batch_size,
        )
        return await rebuilder.rebuild()


async def run_rebuild_command() -> NewsIndexRebuildResult:
    try:
        return await rebuild_news_index()
    finally:
        await async_engine.dispose()


def run_cli(
    *,
    rebuild: Callable[[], Awaitable[NewsIndexRebuildResult]] = run_rebuild_command,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    try:
        result = asyncio.run(rebuild())
    except Exception as exc:
        print(
            f"新闻 Chunk 索引构建失败，活动索引保持不变：{exc}",
            file=stderr,
        )
        return 1
    print(
        "新闻 Chunk 索引构建完成："
        f"build={result.build_id}，索引={result.index_name}，"
        f"扫描 {result.scanned_news} 篇新闻，"
        f"生成 {result.generated_chunks} 个 Chunk，"
        f"写入 {result.indexed_chunks} 个 Chunk。",
        file=stdout,
    )
    return 0


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
