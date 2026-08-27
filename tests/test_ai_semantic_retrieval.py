import unittest
from unittest.mock import AsyncMock, patch

from redis.exceptions import ResponseError


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


class InMemoryRedisStack:
    def __init__(self):
        self.hashes = {
            "ai:summary:v1:9": {"summary": "保留的摘要缓存"},
            "checkpoint:session-a": {"state": "保留的会话"},
        }
        self.indexes = set()
        self.fail = False

    async def execute_command(self, *parts):
        if self.fail:
            raise ConnectionError("redis offline")
        command = str(parts[0]).upper()
        if command == "FT.INFO":
            if parts[1] not in self.indexes:
                raise ResponseError("Unknown Index name")
            return ["index_name", parts[1]]
        if command == "FT.CREATE":
            self.indexes.add(parts[1])
            return "OK"
        if command == "FT.SEARCH":
            return [0]
        raise AssertionError(f"unexpected command: {parts}")

    async def scan(self, cursor=0, match=None, count=None):
        keys = [key for key in self.hashes if match is None or key.startswith(match.rstrip("*"))]
        return 0, keys

    async def delete(self, *keys):
        for key in keys:
            self.hashes.pop(key, None)

    async def hset(self, key, mapping):
        self.hashes[key] = dict(mapping)


class RedisNewsVectorStoreTests(unittest.IsolatedAsyncioTestCase):
    def test_parses_redis_search_fields_returned_as_bytes(self):
        """A Redis client without decode_responses must still produce usable hits."""
        from app.ai.rag.vector_store import RedisNewsVectorStore

        hits = RedisNewsVectorStore._parse_search_response(
            [
                1,
                b"ai:news:vector:v1:7",
                [
                    b"news_id", b"7",
                    b"title", "AI 芯片".encode(),
                    b"description", "技术新闻".encode(),
                    b"content", "国产 AI 芯片发布".encode(),
                    b"views", b"12",
                    b"vector_distance", b"0.125",
                ],
            ],
            minimum_score=0.5,
        )

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].news_id, 7)
        self.assertEqual(hits[0].title, "AI 芯片")
        self.assertEqual(hits[0].score, 0.875)

    async def test_rebuild_uses_stable_news_keys_and_never_clears_other_redis_namespaces(self):
        from app.ai.rag.vector_store import NewsVectorDocument, RedisNewsVectorStore

        redis = InMemoryRedisStack()
        store = RedisNewsVectorStore(
            redis_client=redis,
            index_name="idx:ai:news:vector:v1",
            key_prefix="ai:news:vector:v1:",
            vector_dimensions=2,
        )
        document = NewsVectorDocument(
            news_id=7,
            title="人工智能发展",
            description="技术新闻",
            content="模型能力持续提升",
            views=12,
            embedding=[0.1, 0.2],
        )

        await store.replace_documents([document])
        await store.replace_documents([document])

        self.assertEqual(redis.indexes, {"idx:ai:news:vector:v1"})
        self.assertEqual(
            set(redis.hashes),
            {"ai:summary:v1:9", "checkpoint:session-a", "ai:news:vector:v1:7"},
        )
        self.assertEqual(redis.hashes["ai:news:vector:v1:7"]["news_id"], "7")

    async def test_rejects_invalid_embedding_and_translates_redis_outages(self):
        from app.ai.rag.vector_store import (
            NewsVectorDocument,
            NewsVectorStoreUnavailable,
            RedisNewsVectorStore,
        )

        redis = InMemoryRedisStack()
        store = RedisNewsVectorStore(
            redis_client=redis,
            index_name="idx:ai:news:vector:v1",
            key_prefix="ai:news:vector:v1:",
            vector_dimensions=2,
        )
        invalid = NewsVectorDocument(
            news_id=8,
            title="维度错误",
            description=None,
            content="正文",
            views=1,
            embedding=[0.1],
        )

        with self.assertRaises(ValueError):
            await store.replace_documents([invalid])

        redis.fail = True
        valid = NewsVectorDocument(
            news_id=8,
            title="服务错误",
            description=None,
            content="正文",
            views=1,
            embedding=[0.1, 0.2],
        )
        with self.assertRaises(NewsVectorStoreUnavailable):
            await store.replace_documents([valid])


class FakeNewsSource:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def list_news(self, offset, limit):
        self.calls.append((offset, limit))
        return self.rows[offset: offset + limit]


class FakeEmbeddingService:
    def __init__(self):
        self.batches = []

    async def embed(self, texts):
        self.batches.append(texts)
        return [[float(index), 0.5] for index, _ in enumerate(texts, start=1)]


class FakeVectorStore:
    def __init__(self):
        self.documents = None

    async def replace_documents(self, documents):
        self.documents = documents


class NewsIndexRebuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_rebuilds_the_current_news_set_with_stable_ids(self):
        from app.ai.rag.reindex import NewsIndexRebuilder

        source = FakeNewsSource([
            type("News", (), {"id": 7, "title": "AI 芯片", "description": "技术", "content": "国产芯片发布", "views": 5})(),
            type("News", (), {"id": 9, "title": "机器人", "description": None, "content": "机器人应用", "views": 8})(),
            type("News", (), {"id": 11, "title": "大模型", "description": "模型", "content": "模型开源", "views": 3})(),
        ])
        embeddings = FakeEmbeddingService()
        vector_store = FakeVectorStore()
        rebuilder = NewsIndexRebuilder(
            source=source,
            embedding_service=embeddings,
            vector_store=vector_store,
            batch_size=2,
        )

        result = await rebuilder.rebuild()

        self.assertEqual(result.scanned_news, 3)
        self.assertEqual(result.indexed_news, 3)
        self.assertEqual(source.calls, [(0, 2), (2, 2)])
        self.assertEqual([item.news_id for item in vector_store.documents], [7, 9, 11])
        self.assertEqual(vector_store.documents[0].embedding, [1.0, 0.5])
        self.assertIn("标题：AI 芯片", embeddings.batches[0][0])
        self.assertIn("正文：国产芯片发布", embeddings.batches[0][0])

    async def test_rebuild_rejects_an_embedding_batch_that_cannot_map_to_all_news(self):
        from app.ai.rag.reindex import NewsIndexRebuilder, NewsIndexRebuildUnavailable

        class WrongSizeEmbeddingService:
            async def embed(self, texts):
                return [[0.1, 0.2]]

        rebuilder = NewsIndexRebuilder(
            source=FakeNewsSource([
                type("News", (), {"id": 1, "title": "新闻一", "description": None, "content": "正文一", "views": 1})(),
                type("News", (), {"id": 2, "title": "新闻二", "description": None, "content": "正文二", "views": 2})(),
            ]),
            embedding_service=WrongSizeEmbeddingService(),
            vector_store=FakeVectorStore(),
            batch_size=2,
        )

        with self.assertRaises(NewsIndexRebuildUnavailable):
            await rebuilder.rebuild()

    async def test_command_runner_disposes_the_database_engine_before_the_event_loop_closes(self):
        from app.ai.rag.reindex import NewsIndexRebuildResult, run_rebuild_command

        class Engine:
            def __init__(self):
                self.disposed = False

            async def dispose(self):
                self.disposed = True

        engine = Engine()
        expected = NewsIndexRebuildResult(scanned_news=2, indexed_news=2)
        with (
            patch("app.ai.rag.reindex.rebuild_news_index", new=AsyncMock(return_value=expected)),
            patch("app.ai.rag.reindex.async_engine", engine),
        ):
            result = await run_rebuild_command()

        self.assertEqual(result, expected)
        self.assertTrue(engine.disposed)


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
