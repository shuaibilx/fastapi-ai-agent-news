import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.ai.summarization import NewsSummaryResult, SummaryProviderUnavailable
from app.api.routers.ai import get_news_summary_service
from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app


class NewsSummaryApiAuthenticationTests(unittest.TestCase):
    def test_summary_endpoint_rejects_a_request_without_a_bearer_token(self):
        with TestClient(app) as client:
            response = client.post("/api/ai/news/7/summary")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 401)


class StubSummaryService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def summarize(self, news_id, title, content):
        self.calls.append((news_id, title, content))
        if self.error:
            raise self.error
        return self.result


async def override_current_user():
    return SimpleNamespace(id=1)


async def override_db():
    yield object()


class NewsSummaryApiContractTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = override_current_user
        app.dependency_overrides[get_db] = override_db

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_summary_endpoint_returns_the_documented_success_payload(self):
        service = StubSummaryService(
            result=NewsSummaryResult(summary="新闻摘要", cache_status="miss")
        )
        app.dependency_overrides[get_news_summary_service] = lambda: service
        article = SimpleNamespace(id=7, title="AI 新闻", content="这是正文")

        with patch("app.api.routers.ai.news.get_news_detail", new=AsyncMock(return_value=article)):
            with TestClient(app) as client:
                response = client.post("/api/ai/news/7/summary")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 200,
                "message": "获取新闻摘要成功",
                "data": {"newsId": 7, "summary": "新闻摘要", "cacheStatus": "miss"},
            },
        )

    def test_missing_news_returns_not_found_without_calling_the_provider(self):
        service = StubSummaryService(
            result=NewsSummaryResult(summary="不应返回", cache_status="miss")
        )
        app.dependency_overrides[get_news_summary_service] = lambda: service

        with patch("app.api.routers.ai.news.get_news_detail", new=AsyncMock(return_value=None)):
            with TestClient(app) as client:
                response = client.post("/api/ai/news/404/summary")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 404)
        self.assertEqual(service.calls, [])

    def test_provider_failure_returns_service_unavailable(self):
        service = StubSummaryService(error=SummaryProviderUnavailable("provider failed"))
        app.dependency_overrides[get_news_summary_service] = lambda: service
        article = SimpleNamespace(id=7, title="AI 新闻", content="这是正文")

        with patch("app.api.routers.ai.news.get_news_detail", new=AsyncMock(return_value=article)):
            with TestClient(app) as client:
                response = client.post("/api/ai/news/7/summary")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], 503)
        self.assertEqual(response.json()["message"], "摘要服务暂时不可用")


if __name__ == "__main__":
    unittest.main()
