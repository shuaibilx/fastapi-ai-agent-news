from typing import Optional
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.ai.rag import NewsQaResult, QaCitation, QaProviderUnavailable, QaService, NewsRetrievalService
from app.api.routers.ai import get_qa_service
from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app


class FakeQaGateway:
    def __init__(self, response="AI 新闻回答"):
        self.response = response
        self.calls = []

    async def answer(self, question, context):
        self.calls.append((question, context))
        return self.response


class FailingQaGateway:
    async def answer(self, question, context):
        raise QaProviderUnavailable("provider timed out")


class InMemoryNewsRepo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def search_news(self, question, limit):
        self.calls.append((question, limit))
        return self.rows


class NewsRetrievalServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_retrieval_orders_higher_match_count_first_and_bounds_results(self):
        from app.ai.rag.retrieval import NewsRetrievalService
        repo = InMemoryNewsRepo([
            SimpleNamespace(id=1, title="AI 新闻", description="AI", content="AI 大模型", views=10),
            SimpleNamespace(id=2, title="AI", description="", content="普通", views=20),
            SimpleNamespace(id=3, title="AI", description="AI", content="AI", views=30),
            SimpleNamespace(id=4, title="AI", description="AI", content="AI AI AI", views=40),
        ])
        service = NewsRetrievalService(repo, default_limit=2)

        rows = await service.search("AI")

        self.assertEqual([r.id for r in rows], [4, 3])

    async def test_returns_empty_when_no_match(self):
        from app.ai.rag.retrieval import NewsRetrievalService
        repo = InMemoryNewsRepo([])
        service = NewsRetrievalService(repo, default_limit=5)

        self.assertEqual(await service.search("不存在的关键词"), [])

    def test_extracts_deterministic_excerpt_containing_match(self):
        from app.ai.rag.retrieval import extract_match_excerpt
        excerpt = extract_match_excerpt("这是一段包含AI人工智能的新闻正文", "AI")

        self.assertIn("AI", excerpt)
        self.assertLessEqual(len(excerpt), 80)

    def test_excerpt_with_no_match_uses_head_of_content(self):
        from app.ai.rag.retrieval import extract_match_excerpt
        excerpt = extract_match_excerpt("第一句没有关键词", "关键词不在这里")

        self.assertEqual(excerpt, "第一句没有关键词")


class QaServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_generation_returns_answer_and_citations(self):
        service = QaService(
            retrieval=NewsRetrievalService(
                InMemoryNewsRepo([SimpleNamespace(id=7, title="AI 新闻", description="AI 描述", content="AI 大模型新闻", views=5)]),
                default_limit=3,
            ),
            gateway=FakeQaGateway("来自新闻的回答"),
        )

        result = await service.ask("AI 是什么？")

        self.assertEqual(result.answer, "来自新闻的回答")
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].news_id, 7)
        self.assertEqual(result.citations[0].title, "AI 新闻")
        self.assertTrue(result.citations[0].excerpt)

    async def test_empty_question_raises_validation_error_without_calling_gateway(self):
        gateway = FakeQaGateway()
        service = QaService(
            retrieval=NewsRetrievalService(InMemoryNewsRepo([]), default_limit=3),
            gateway=gateway,
        )

        with self.assertRaises(ValueError):
            await service.ask("   ")
        self.assertEqual(gateway.calls, [])

    async def test_no_context_returns_refusal_without_calling_gateway(self):
        gateway = FakeQaGateway()
        service = QaService(
            retrieval=NewsRetrievalService(InMemoryNewsRepo([]), default_limit=3),
            gateway=gateway,
        )

        result = await service.ask("找不到任何新闻")

        self.assertIn("无法", result.answer)
        self.assertEqual(result.citations, [])
        self.assertEqual(gateway.calls, [])

    async def test_provider_timeout_is_translated_to_service_unavailable(self):
        service = QaService(
            retrieval=NewsRetrievalService(
                InMemoryNewsRepo([SimpleNamespace(id=7, title="AI 新闻", description="AI", content="AI 新闻", views=5)]),
                default_limit=3,
            ),
            gateway=FailingQaGateway(),
        )

        with self.assertRaises(QaProviderUnavailable):
            await service.ask("AI 是什么？")

    async def test_citation_metadata_is_derived_from_retrieval_not_model(self):
        service = QaService(
            retrieval=NewsRetrievalService(
                InMemoryNewsRepo([SimpleNamespace(id=9, title="科技新闻", description="AI 芯片", content="芯片 细节", views=5)]),
                default_limit=3,
            ),
            gateway=FakeQaGateway("回答"),
        )

        result = await service.ask("AI 芯片")

        self.assertEqual(result.citations[0].news_id, 9)
        self.assertEqual(result.citations[0].title, "科技新闻")


async def override_current_user():
    return SimpleNamespace(id=1)


async def override_db():
    yield object()


class QaStubService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def ask(self, question):
        self.calls.append(question)
        if self.error:
            raise self.error
        return self.result


class QaApiTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = override_current_user
        app.dependency_overrides[get_db] = override_db

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_qa_rejects_request_without_auth(self):
        app.dependency_overrides.clear()
        with TestClient(app) as client:
            response = client.post("/api/ai/qa", json={"question": "AI 是什么？"})

        self.assertEqual(response.status_code, 401)

    def test_qa_returns_answer_with_citations(self):
        result = NewsQaResult(
            answer="AI 新闻回答",
            citations=[QaCitation(news_id=7, title="AI 新闻", excerpt="AI 新闻内容")],
        )
        app.dependency_overrides[get_qa_service] = lambda: QaStubService(result=result)

        with TestClient(app) as client:
            response = client.post("/api/ai/qa", json={"question": "AI 是什么？"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 200)
        self.assertEqual(response.json()["data"]["answer"], "AI 新闻回答")
        self.assertEqual(response.json()["data"]["citations"][0]["newsId"], 7)

    def test_qa_rejects_empty_question_without_calling_provider(self):
        service = QaStubService(result=NewsQaResult(answer="不应返回", citations=[]))
        app.dependency_overrides[get_qa_service] = lambda: service

        with TestClient(app) as client:
            response = client.post("/api/ai/qa", json={"question": "   "})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(service.calls, [])

    def test_qa_provider_failure_returns_service_unavailable(self):
        app.dependency_overrides[get_qa_service] = lambda: QaStubService(error=QaProviderUnavailable("provider failed"))

        with TestClient(app) as client:
            response = client.post("/api/ai/qa", json={"question": "AI 是什么？"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], 503)


if __name__ == "__main__":
    unittest.main()










