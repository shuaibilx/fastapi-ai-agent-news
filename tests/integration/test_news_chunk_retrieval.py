import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import redis.asyncio as redis

from app.ai.embeddings import TeiEmbeddingClient
from app.ai.rag.chunking import BgeTokenCounter, NewsChunker
from app.ai.rag.context import RetrievalContextBuilder
from app.ai.rag.reindex import NewsIndexRebuilder
from app.ai.rag.retrieval import NewsRetrievalService, RedisSemanticNewsSearch
from app.ai.rag.service import QaService
from app.ai.rag.vector_store import RedisNewsVectorStore
from app.core.config import get_settings


pytestmark = pytest.mark.skipif(
    not {
        "AI_RETRIEVAL_TEST_REDIS_URL",
        "AI_RETRIEVAL_TEST_EMBEDDING_URL",
    }.issubset(os.environ),
    reason="需要显式配置隔离 Redis Stack 与 TEI 才运行集成测试",
)


class _FixtureSource:
    def __init__(self, rows):
        self._rows = rows

    async def list_news(self, offset: int, limit: int):
        return self._rows[offset:offset + limit]


class _UnusedKeywordSearch:
    async def search_news(self, question: str, limit: int):
        return []


class _CapturingGateway:
    def __init__(self):
        self.context = ""

    async def answer(self, question: str, context: str) -> str:
        self.context = context
        return "液冷技术使整体能耗下降了百分之十七。"


async def _run_tail_fact_round_trip() -> None:
    settings = get_settings()
    fixture = json.loads(
        Path("tests/fixtures/news_chunk_eval.json").read_text(encoding="utf-8")
    )
    rows = [SimpleNamespace(**item) for item in fixture["articles"]]
    tail_article = next(item for item in rows if item.id == 101)
    tail_prefix = tail_article.content.split("报告在正文后部确认", 1)[0]
    tokens = BgeTokenCounter(settings.embedding_tokenizer_path)
    assert tokens.count(tail_prefix) > 512

    run_id = uuid4().hex[:12]
    index_alias = f"idx:test:news:chunk:{run_id}:active"
    index_prefix = f"idx:test:news:chunk:{run_id}"
    key_prefix = f"test:ai:news:chunk:{run_id}"
    client = redis.Redis.from_url(
        os.environ["AI_RETRIEVAL_TEST_REDIS_URL"],
        decode_responses=True,
    )
    vector_store = RedisNewsVectorStore(
        redis_client=client,
        index_alias=index_alias,
        index_prefix=index_prefix,
        key_prefix=key_prefix,
        vector_dimensions=settings.ai_semantic_vector_dimensions,
    )
    embeddings = TeiEmbeddingClient(
        base_url=os.environ["AI_RETRIEVAL_TEST_EMBEDDING_URL"],
        timeout_seconds=settings.embedding_timeout_seconds,
        vector_dimensions=settings.ai_semantic_vector_dimensions,
    )
    build_id = "integration"

    try:
        result = await NewsIndexRebuilder(
            source=_FixtureSource(rows),
            embedding_service=embeddings,
            vector_store=vector_store,
            chunker=NewsChunker(
                token_counter=tokens,
                chunk_size_tokens=settings.ai_semantic_chunk_size_tokens,
                chunk_overlap_tokens=settings.ai_semantic_chunk_overlap_tokens,
                embedding_input_max_tokens=(
                    settings.ai_semantic_embedding_input_max_tokens
                ),
            ),
            batch_size=settings.ai_semantic_batch_size,
            build_id_factory=lambda: build_id,
        ).rebuild()
        assert result.scanned_news == 5
        assert result.generated_chunks > result.scanned_news

        semantic_search = RedisSemanticNewsSearch(
            embedding_service=embeddings,
            vector_store=vector_store,
            minimum_score=settings.ai_semantic_score_threshold,
            candidate_chunk_limit=settings.ai_semantic_candidate_chunk_limit,
            max_chunks_per_news=settings.ai_semantic_max_chunks_per_news,
        )
        retrieval = NewsRetrievalService(
            _UnusedKeywordSearch(),
            default_limit=settings.ai_qa_retrieval_limit,
            semantic_search=semantic_search,
        )
        articles = await retrieval.search("液冷技术让算力中心能耗下降了多少？")
        assert articles[0].id == 101
        assert any("整体能耗下降了百分之十七" in item.text for item in articles[0].passages)

        gateway = _CapturingGateway()
        qa = QaService(
            retrieval=retrieval,
            gateway=gateway,
            context_builder=RetrievalContextBuilder(
                token_counter=tokens,
                max_tokens=settings.ai_qa_max_context_tokens,
            ),
        )
        answer = await qa.ask("液冷技术让算力中心能耗下降了多少？")

        assert "整体能耗下降了百分之十七" in gateway.context
        assert tokens.count(gateway.context) <= settings.ai_qa_max_context_tokens
        assert answer.citations[0].news_id == 101
        assert "百分之十七" in (answer.citations[0].excerpt or "")
    finally:
        try:
            await client.execute_command("FT.ALIASDEL", index_alias)
        except Exception:
            pass
        await vector_store.discard_build(build_id)
        await client.aclose()


def test_real_bge_redis_tail_fact_reaches_qa_context_and_citation():
    import asyncio

    asyncio.run(_run_tail_fact_round_trip())
