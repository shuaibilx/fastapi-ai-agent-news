import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.ai.agent.memory import ContextWindowExceeded
from app.ai.agent.memory_store import MemoryStatus
from app.ai.agent.results import AgentCitation, AgentToolSummary
from app.ai.agent.service import (
    AgentExecutionLimitExceeded,
    AgentProviderUnavailable,
    AgentResult,
)
from app.api.routers.ai import get_agent_service
from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app


async def override_current_user():
    return SimpleNamespace(id=31)


async def override_db():
    yield object()


class StubAgentService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def ask(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class AgentApiTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = override_current_user
        app.dependency_overrides[get_db] = override_db

    def tearDown(self):
        app.dependency_overrides.clear()

    @staticmethod
    def result(memory_status=MemoryStatus.LOADED):
        return AgentResult(
            answer="综合回答",
            conversation_id="7c1f07e2-46db-4ce1-9724-f428561d8f45",
            citations=[AgentCitation(11, "AI 新闻", "相关摘录")],
            tool_calls=[AgentToolSummary("search_news_knowledge", "success", "检索成功")],
            memory_status=memory_status,
        )

    def test_agent_endpoint_rejects_requests_without_authentication(self):
        app.dependency_overrides.clear()

        with TestClient(app) as client:
            response = client.post("/api/ai/agent", json={"message": "我的收藏有什么？"})

        self.assertEqual(response.status_code, 401)

    def test_agent_endpoint_returns_answer_trace_citations_and_conversation_id(self):
        service = StubAgentService(result=self.result())
        app.dependency_overrides[get_agent_service] = lambda: service

        with TestClient(app) as client:
            response = client.post(
                "/api/ai/agent",
                json={
                    "message": "分析我的收藏",
                    "conversationId": "7c1f07e2-46db-4ce1-9724-f428561d8f45",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "code": 200,
            "message": "获取 Agent 回答成功",
            "data": {
                "answer": "综合回答",
                "conversationId": "7c1f07e2-46db-4ce1-9724-f428561d8f45",
                "citations": [{"newsId": 11, "title": "AI 新闻", "excerpt": "相关摘录"}],
                "toolCalls": [{
                    "name": "search_news_knowledge",
                    "status": "success",
                    "summary": "检索成功",
                }],
                "memoryStatus": "loaded",
            },
        })
        self.assertEqual(service.calls[0]["user_id"], 31)
        self.assertEqual(service.calls[0]["message"], "分析我的收藏")

    def test_agent_endpoint_accepts_missing_conversation_id_and_reports_redis_degradation(self):
        service = StubAgentService(result=self.result(MemoryStatus.UNAVAILABLE))
        app.dependency_overrides[get_agent_service] = lambda: service

        with TestClient(app) as client:
            response = client.post("/api/ai/agent", json={"message": "继续"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(service.calls[0]["conversation_id"])
        self.assertEqual(response.json()["data"]["memoryStatus"], "unavailable")

    def test_agent_endpoint_rejects_blank_messages_without_running_service(self):
        service = StubAgentService(result=self.result())
        app.dependency_overrides[get_agent_service] = lambda: service

        with TestClient(app) as client:
            response = client.post("/api/ai/agent", json={"message": "   "})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(service.calls, [])

    def test_agent_endpoint_maps_provider_and_execution_limit_failures_to_503(self):
        for error in (
            AgentProviderUnavailable("provider failed"),
            AgentExecutionLimitExceeded("loop stopped"),
        ):
            app.dependency_overrides[get_agent_service] = lambda error=error: StubAgentService(error=error)
            with TestClient(app) as client:
                response = client.post("/api/ai/agent", json={"message": "问题"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["code"], 503)

    def test_agent_endpoint_maps_oversized_current_message_to_422(self):
        app.dependency_overrides[get_agent_service] = lambda: StubAgentService(
            error=ContextWindowExceeded("当前消息超过限制")
        )

        with TestClient(app) as client:
            response = client.post("/api/ai/agent", json={"message": "太长的问题"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], 422)


if __name__ == "__main__":
    unittest.main()
