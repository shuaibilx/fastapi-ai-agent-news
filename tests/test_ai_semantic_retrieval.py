import unittest


class FakeEmbeddingResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeEmbeddingHttpClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else []
        self.error = error
        self.requests = []

    async def post(self, url, *, json):
        self.requests.append((url, json))
        if self.error is not None:
            raise self.error
        return FakeEmbeddingResponse(self.payload)


class TeiEmbeddingClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_embeds_a_batch_from_the_local_tei_endpoint(self):
        from app.ai.embeddings.client import TeiEmbeddingClient

        http_client = FakeEmbeddingHttpClient(payload=[[0.1, 0.2], [0.3, 0.4]])
        client = TeiEmbeddingClient(
            base_url="http://embedding:8081/",
            timeout_seconds=20,
            vector_dimensions=2,
            http_client=http_client,
        )

        vectors = await client.embed(["第一篇新闻", "第二篇新闻"])

        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
        self.assertEqual(
            http_client.requests,
            [("http://embedding:8081/embed", {"inputs": ["第一篇新闻", "第二篇新闻"]})],
        )

    async def test_rejects_a_tei_response_with_the_wrong_vector_dimension(self):
        from app.ai.embeddings.client import (
            EmbeddingProviderUnavailable,
            TeiEmbeddingClient,
        )

        client = TeiEmbeddingClient(
            base_url="http://embedding:8081",
            timeout_seconds=20,
            vector_dimensions=2,
            http_client=FakeEmbeddingHttpClient(payload=[[0.1, 0.2, 0.3]]),
        )

        with self.assertRaises(EmbeddingProviderUnavailable):
            await client.embed(["维度错误"])

    async def test_translates_transport_errors_to_a_safe_provider_failure(self):
        from app.ai.embeddings.client import (
            EmbeddingProviderUnavailable,
            TeiEmbeddingClient,
        )

        client = TeiEmbeddingClient(
            base_url="http://embedding:8081",
            timeout_seconds=20,
            vector_dimensions=2,
            http_client=FakeEmbeddingHttpClient(error=ConnectionError("offline")),
        )

        with self.assertRaises(EmbeddingProviderUnavailable):
            await client.embed(["服务不可用"])


class SemanticSearchStub:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.calls = []

    async def search(self, question, limit):
        self.calls.append((question, limit))
        if self.error:
            raise self.error
        return self.rows


class KeywordSearchStub:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def search_news(self, question, limit):
        self.calls.append((question, limit))
        return self.rows


class CompositeNewsRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_result_is_used_even_when_question_has_no_matching_keyword(self):
        from app.ai.rag.retrieval import (
            NewsRetrievalService,
            RetrievedArticle,
        )

        semantic = SemanticSearchStub(rows=[RetrievedArticle(
            id=7,
            title="国产算力新闻",
            description="芯片产业",
            content="新的 AI 加速器发布",
            views=10,
            excerpt="新的 AI 加速器发布",
            match_count=0,
        )])
        keyword = KeywordSearchStub([])
        service = NewsRetrievalService(
            search_port=keyword,
            semantic_search=semantic,
            default_limit=3,
        )

        rows = await service.search("本土智能计算有什么进展？")

        self.assertEqual([row.id for row in rows], [7])
        self.assertEqual(keyword.calls, [])

    async def test_healthy_semantic_empty_result_does_not_mix_in_keyword_results(self):
        from app.ai.rag.retrieval import NewsRetrievalService

        keyword = KeywordSearchStub([
            type("News", (), {"id": 9, "title": "关键词新闻", "description": None, "content": "正文", "views": 1})(),
        ])
        service = NewsRetrievalService(
            search_port=keyword,
            semantic_search=SemanticSearchStub(rows=[]),
            default_limit=3,
        )

        self.assertEqual(await service.search("没有语义结果的问题"), [])
        self.assertEqual(keyword.calls, [])

    async def test_semantic_infrastructure_failure_falls_back_to_keyword_results(self):
        from app.ai.rag.retrieval import (
            NewsRetrievalService,
            SemanticSearchUnavailable,
        )

        keyword = KeywordSearchStub([
            type("News", (), {"id": 9, "title": "AI 新闻", "description": "AI", "content": "AI 正文", "views": 1})(),
        ])
        service = NewsRetrievalService(
            search_port=keyword,
            semantic_search=SemanticSearchStub(error=SemanticSearchUnavailable("offline")),
            default_limit=3,
        )

        rows = await service.search("AI")

        self.assertEqual([row.id for row in rows], [9])
        self.assertEqual(keyword.calls, [("AI", 3)])


if __name__ == "__main__":
    unittest.main()
