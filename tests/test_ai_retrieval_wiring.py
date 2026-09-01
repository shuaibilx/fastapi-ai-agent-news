from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.ai.rag.vector_store import VectorSearchHit


class SemanticEmbeddingStub:
    async def embed(self, texts):
        return [[0.1, 0.2]]


class SemanticVectorStoreStub:
    async def search(self, embedding, *, limit, minimum_score):
        return [VectorSearchHit(
            news_id=31,
            chunk_id="31:2:hash",
            chunk_index=2,
            start_index=200,
            end_index=215,
            title="国产算力进展",
            description="芯片产业",
            chunk_text="本土 AI 加速器发布",
            content_hash="hash",
            category_id=1,
            publish_time="2026-09-01T08:00:00",
            views=88,
            score=0.91,
        )]


class NewsRetrievalWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_retrieval_factory_exposes_semantic_results_to_qa_and_agent_consumers(self):
        from app.api.routers.ai import build_news_retrieval

        settings = SimpleNamespace(
            ai_qa_retrieval_limit=5,
            embedding_base_url="http://embedding:8081",
            embedding_timeout_seconds=20,
            ai_semantic_vector_dimensions=2,
            ai_semantic_index_alias="idx:ai:news:chunk:active",
            ai_semantic_index_prefix="idx:ai:news:chunk:v2",
            ai_semantic_chunk_key_prefix="ai:news:chunk:v2",
            ai_semantic_score_threshold=0.35,
            ai_semantic_candidate_chunk_limit=20,
            ai_semantic_max_chunks_per_news=2,
        )
        with (
            patch("app.api.routers.ai.get_settings", return_value=settings),
            patch("app.api.routers.ai.TeiEmbeddingClient", return_value=SemanticEmbeddingStub()),
            patch("app.api.routers.ai.RedisNewsVectorStore", return_value=SemanticVectorStoreStub()),
        ):
            retrieval = build_news_retrieval(object())
            rows = await retrieval.search("本土智能计算有什么进展？")

        self.assertEqual([row.id for row in rows], [31])
        self.assertEqual(rows[0].title, "国产算力进展")


if __name__ == "__main__":
    unittest.main()
