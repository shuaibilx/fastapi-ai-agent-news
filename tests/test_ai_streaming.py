import asyncio
import json
import unittest
from uuid import UUID
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.ai.agent.memory_runtime import AgentMemorySession
from app.ai.agent.memory_store import MemoryStatus
from app.ai.agent.results import AgentCitation, AgentToolSummary
from app.ai.agent.service import AgentProviderUnavailable, AgentService
from app.ai.rag import NewsRetrievalService, QaProviderUnavailable, QaService
from app.api.routers.ai import get_agent_service, get_qa_service
from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app


async def collect(iterator):
    return [item async for item in iterator]


class StreamingProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_encoder_uses_json_sse_and_rejects_events_after_done(self):
        from app.ai.streaming import StreamEvent, SseEventEncoder, StreamProtocolError

        encoder = SseEventEncoder()
        self.assertEqual(
            encoder.encode(StreamEvent.delta("你好")),
            'event: delta\ndata: {"text":"你好"}\n\n',
        )
        encoder.encode(StreamEvent.done({"citations": []}))
        with self.assertRaises(StreamProtocolError):
            encoder.encode(StreamEvent.delta("不应输出"))

    async def test_encoder_whitelists_payload_fields(self):
        from app.ai.streaming import StreamEvent, SseEventEncoder, StreamProtocolError

        encoder = SseEventEncoder()
        with self.assertRaises(StreamProtocolError):
            encoder.encode(StreamEvent("tool", {
                "name": "search_news_knowledge",
                "status": "success",
                "summary": "检索完成",
                "toolArguments": {"user_id": 7},
            }))

    async def test_coordinator_sends_ping_and_stops_without_done_after_disconnect(self):
        from app.ai.streaming import StreamEvent, iter_sse_events

        gate = asyncio.Event()
        checks = 0

        async def source():
            yield StreamEvent.delta("第一段")
            await gate.wait()
            yield StreamEvent.done({"citations": []})

        async def disconnected():
            nonlocal checks
            checks += 1
            return checks >= 5

        output = await collect(iter_sse_events(
            source(),
            heartbeat_seconds=0.001,
            is_disconnected=disconnected,
        ))

        decoded = "".join(output)
        self.assertIn("event: delta", decoded)
        self.assertIn("event: ping", decoded)
        self.assertNotIn("event: done", decoded)


class InMemoryNewsRepo:
    def __init__(self, rows):
        self.rows = rows

    async def search_news(self, question, limit):
        return self.rows


class StreamingQaGateway:
    def __init__(self, chunks=("来自", "新闻的回答"), error=None):
        self.chunks = chunks
        self.error = error
        self.stream_calls = []

    async def answer(self, question, context):
        return "".join(self.chunks)

    async def stream_answer(self, question, context):
        self.stream_calls.append((question, context))
        if self.error:
            raise self.error
        for chunk in self.chunks:
            yield chunk


class QaStreamingServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, gateway, rows):
        return QaService(
            retrieval=NewsRetrievalService(InMemoryNewsRepo(rows), default_limit=3),
            gateway=gateway,
        )

    async def test_streams_retrieved_citations_then_visible_deltas_and_done(self):
        service = self.make_service(
            StreamingQaGateway(),
            [SimpleNamespace(id=7, title="AI 新闻", description="AI 描述", content="AI 正文", views=5)],
        )

        events = await collect(service.stream("AI 是什么？"))

        self.assertEqual([event.name for event in events], ["meta", "citation", "delta", "delta", "done"])
        self.assertEqual("".join(event.data["text"] for event in events if event.name == "delta"), "来自新闻的回答")
        self.assertEqual(events[1].data["newsId"], 7)
        self.assertEqual(events[-1].data["citations"][0]["newsId"], 7)

    async def test_no_article_streams_refusal_without_invoking_provider(self):
        gateway = StreamingQaGateway()
        service = self.make_service(gateway, [])

        events = await collect(service.stream("没有相关新闻"))

        self.assertEqual([event.name for event in events], ["meta", "delta", "done"])
        self.assertIn("无法回答", events[1].data["text"])
        self.assertEqual(events[-1].data["citations"], [])
        self.assertEqual(gateway.stream_calls, [])

    async def test_provider_failure_after_stream_start_is_exposed_to_router(self):
        service = self.make_service(
            StreamingQaGateway(error=QaProviderUnavailable("timeout")),
            [SimpleNamespace(id=7, title="AI 新闻", description="AI", content="AI", views=5)],
        )

        with self.assertRaises(QaProviderUnavailable):
            await collect(service.stream("AI 是什么？"))


class FakeMemoryRuntime:
    def __init__(self):
        self.session = AgentMemorySession(MemoryStatus.EMPTY, {}, None)
        self.verified = []

    async def prepare(self, user_id, conversation_id):
        return self.session

    async def verify_saved(self, session):
        self.verified.append(session)
        return MemoryStatus.LOADED


class StreamingAgentRunner:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error
        self.calls = []

    async def ainvoke(self, payload, *, context, config):
        return {"messages": [*payload["messages"], AIMessage(content="unused")]}

    async def astream_events(self, payload, *, context, config):
        self.calls.append((payload, context, config))
        if self.error:
            raise self.error
        for event in self.events:
            yield event


def tool_message():
    return ToolMessage(
        content="原始工具结果 user_id=17",
        tool_call_id="call-1",
        name="search_news_knowledge",
        artifact={
            "citations": [{"news_id": 7, "title": "AI 新闻", "excerpt": "相关新闻"}],
            "tool_summary": {"name": "search_news_knowledge", "status": "success", "summary": "检索到 1 条新闻"},
        },
    )


class AgentStreamingServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, runner, memory=None):
        return AgentService(
            runner=runner,
            memory_runtime=memory or FakeMemoryRuntime(),
            max_iterations=4,
            retrieval_limit=5,
            page_size_limit=10,
            tool_result_max_tokens=500,
        )

    async def test_streams_only_final_visible_text_safe_tool_state_and_done_metadata(self):
        raw_events = [
            {
                "event": "on_chat_model_stream",
                "name": "news_agent",
                "data": {"chunk": AIMessageChunk(content="综合")},
            },
            {"event": "on_tool_end", "name": "search_news_knowledge", "data": {"output": tool_message()}},
            {
                "event": "on_chat_model_stream",
                "name": "news_agent",
                "data": {"chunk": AIMessageChunk(content="回答")},
            },
            {
                "event": "on_chain_end",
                "name": "news_agent",
                "data": {"output": {"messages": [tool_message(), AIMessage(content="综合回答")]}},
            },
            {
                "event": "on_chat_model_stream",
                "name": "news_agent",
                "data": {"chunk": AIMessageChunk(content="内部推理", additional_kwargs={"reasoning_content": "隐藏"})},
            },
        ]
        memory = FakeMemoryRuntime()
        service = self.make_service(StreamingAgentRunner(raw_events), memory)

        events = await collect(service.stream(
            user_id=17,
            message="综合分析",
            conversation_id=None,
            reader=object(),
        ))

        self.assertEqual(events[0].name, "meta")
        self.assertEqual("".join(item.data["text"] for item in events if item.name == "delta"), "综合回答")
        self.assertEqual([item.name for item in events].count("tool"), 1)
        self.assertNotIn("toolArguments", str([item.data for item in events]))
        self.assertNotIn("原始工具结果", str([item.data for item in events]))
        self.assertNotIn("内部推理", str([item.data for item in events]))
        self.assertEqual(events[-1].name, "done")
        UUID(events[-1].data["conversationId"])
        self.assertEqual(events[-1].data["citations"][0]["newsId"], 7)
        self.assertEqual(events[-1].data["memoryStatus"], "loaded")
        self.assertEqual(len(memory.verified), 1)

    async def test_stream_translates_runner_failure_and_does_not_verify_memory(self):
        memory = FakeMemoryRuntime()
        service = self.make_service(StreamingAgentRunner([], error=RuntimeError("provider failed")), memory)

        with self.assertRaises(AgentProviderUnavailable):
            await collect(service.stream(user_id=17, message="问题", conversation_id=None, reader=object()))

        self.assertEqual(memory.verified, [])


async def override_current_user():
    return SimpleNamespace(id=31)


async def override_db():
    yield object()


class QaStreamingStub:
    async def stream(self, question):
        from app.ai.streaming import StreamEvent
        yield StreamEvent.meta({"mode": "qa"})
        yield StreamEvent.delta("流式回答")
        yield StreamEvent.done({"citations": []})


class FailingQaStreamingStub:
    async def stream(self, question):
        from app.ai.streaming import StreamEvent
        yield StreamEvent.meta({"mode": "qa"})
        raise QaProviderUnavailable("provider failed")


class AgentStreamingStub:
    def __init__(self):
        self.calls = []

    def validate_input(self, message, conversation_id):
        return message, conversation_id or "7c1f07e2-46db-4ce1-9724-f428561d8f45"

    async def stream(self, **kwargs):
        from app.ai.streaming import StreamEvent
        self.calls.append(kwargs)
        yield StreamEvent.meta({"conversationId": "7c1f07e2-46db-4ce1-9724-f428561d8f45", "memoryStatus": "empty"})
        yield StreamEvent.tool({"name": "list_my_history", "status": "success", "summary": "查询完成"})
        yield StreamEvent.delta("你最近看了新闻")
        yield StreamEvent.done({
            "conversationId": "7c1f07e2-46db-4ce1-9724-f428561d8f45",
            "citations": [],
            "toolCalls": [{"name": "list_my_history", "status": "success", "summary": "查询完成"}],
            "memoryStatus": "loaded",
        })


class SensitiveAgentStreamingStub(AgentStreamingStub):
    def validate_input(self, message, conversation_id):
        from app.ai.agent.safety import SensitiveDataBlocked
        raise SensitiveDataBlocked("credential")


class AiStreamingApiTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = override_current_user
        app.dependency_overrides[get_db] = override_db

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_qa_stream_preserves_auth_and_validation_failures_before_sse(self):
        app.dependency_overrides.clear()
        with TestClient(app) as client:
            unauthenticated = client.post("/api/ai/qa/stream", json={"question": "AI 是什么？"})
        self.assertEqual(unauthenticated.status_code, 401)

        app.dependency_overrides[get_current_user] = override_current_user
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_qa_service] = lambda: QaStreamingStub()
        with TestClient(app) as client:
            invalid = client.post("/api/ai/qa/stream", json={"question": "   "})
        self.assertEqual(invalid.status_code, 422)

    def test_qa_stream_returns_sse_events_and_error_without_done_after_start(self):
        app.dependency_overrides[get_qa_service] = lambda: QaStreamingStub()
        with TestClient(app) as client:
            response = client.post("/api/ai/qa/stream", json={"question": "AI 是什么？"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertLess(response.text.index("event: delta"), response.text.index("event: done"))

        app.dependency_overrides[get_qa_service] = lambda: FailingQaStreamingStub()
        with TestClient(app) as client:
            failed = client.post("/api/ai/qa/stream", json={"question": "AI 是什么？"})
        self.assertIn("event: error", failed.text)
        self.assertNotIn("event: done", failed.text)

    def test_agent_stream_emits_safe_tool_event_and_keeps_json_endpoint_compatible(self):
        service = AgentStreamingStub()
        app.dependency_overrides[get_agent_service] = lambda: service
        with TestClient(app) as client:
            response = client.post("/api/ai/agent/stream", json={"message": "我的历史"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: tool", response.text)
        self.assertIn("event: done", response.text)
        self.assertNotIn("user_id", response.text)
        self.assertEqual(service.calls[0]["user_id"], 31)

    def test_agent_stream_rejects_blank_or_sensitive_messages_before_streaming(self):
        service = AgentStreamingStub()
        app.dependency_overrides[get_agent_service] = lambda: service
        with TestClient(app) as client:
            blank = client.post("/api/ai/agent/stream", json={"message": "   "})
        self.assertEqual(blank.status_code, 422)
        self.assertEqual(service.calls, [])

        sensitive = SensitiveAgentStreamingStub()
        app.dependency_overrides[get_agent_service] = lambda: sensitive
        with TestClient(app) as client:
            blocked = client.post("/api/ai/agent/stream", json={"message": "api key: sk-test-12345678901234567890"})
        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(sensitive.calls, [])
