import asyncio

import pytest
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from app.ai.agent.memory_runtime import AgentMemorySession
from app.ai.agent.memory_store import MemoryStatus
from app.ai.agent.safety import SensitiveDataBlocked
from app.ai.agent.service import (
    AgentExecutionLimitExceeded,
    AgentProviderUnavailable,
    AgentService,
)


class FakeMemoryRuntime:
    def __init__(self, status=MemoryStatus.EMPTY, config=None):
        self.session = AgentMemorySession(status, config or {}, object() if config else None)
        self.verified = []

    async def prepare(self, user_id, conversation_id):
        return self.session

    async def verify_saved(self, session):
        self.verified.append(session)
        return MemoryStatus.LOADED


class FakeRunner:
    def __init__(self, extra_messages=None, error=None):
        self.extra_messages = extra_messages or [AIMessage(content="最终回答")]
        self.error = error
        self.calls = []

    async def ainvoke(self, payload, *, context, config):
        self.calls.append((payload, context, config))
        if self.error:
            raise self.error
        return {"messages": [*payload["messages"], *self.extra_messages]}


class FakeReader:
    pass


def make_service(runner, memory):
    return AgentService(
        runner=runner,
        memory_runtime=memory,
        max_iterations=4,
        retrieval_limit=5,
        page_size_limit=10,
        tool_result_max_tokens=500,
    )


def tool_result(call_id, news_id, name="search_news_knowledge"):
    return ToolMessage(
        content=f"新闻 {news_id}",
        tool_call_id=call_id,
        name=name,
        artifact={
            "citations": [{"news_id": news_id, "title": f"标题{news_id}", "excerpt": "摘录"}],
            "tool_summary": {"name": name, "status": "success", "summary": "执行成功"},
        },
    )


def test_agent_service_sends_only_current_message_and_server_thread_config():
    memory = FakeMemoryRuntime(
        MemoryStatus.LOADED,
        {"configurable": {"thread_id": "server-thread"}},
    )
    runner = FakeRunner()

    result = asyncio.run(make_service(runner, memory).ask(
        user_id=17,
        message="当前问题",
        conversation_id="7c1f07e2-46db-4ce1-9724-f428561d8f45",
        reader=FakeReader(),
    ))

    payload, context, config = runner.calls[0]
    assert [(type(item), item.content) for item in payload["messages"]] == [
        (HumanMessage, "当前问题"),
    ]
    assert context.user_id == 17
    assert config["configurable"]["thread_id"] == "server-thread"
    assert result.memory_status is MemoryStatus.LOADED
    assert len(memory.verified) == 1


def test_agent_service_collects_multiple_tool_results_and_deduplicates_sources():
    runner = FakeRunner([
        tool_result("call-1", 11),
        tool_result("call-2", 11, "get_news_detail"),
        tool_result("call-3", 12, "list_my_history"),
        AIMessage(content="综合回答"),
    ])

    result = asyncio.run(make_service(runner, FakeMemoryRuntime()).ask(
        user_id=17,
        message="综合分析",
        conversation_id=None,
        reader=FakeReader(),
    ))

    assert [item.news_id for item in result.citations] == [11, 12]
    assert [item.name for item in result.tool_calls] == [
        "search_news_knowledge", "get_news_detail", "list_my_history",
    ]


def test_agent_service_runs_stateless_when_redis_is_unavailable():
    runner = FakeRunner()
    result = asyncio.run(make_service(
        runner,
        FakeMemoryRuntime(MemoryStatus.UNAVAILABLE),
    ).ask(
        user_id=17,
        message="无记忆执行",
        conversation_id=None,
        reader=FakeReader(),
    ))

    assert result.memory_status is MemoryStatus.UNAVAILABLE
    assert "configurable" not in runner.calls[0][2]


def test_agent_service_blocks_credentials_before_runner_call():
    runner = FakeRunner()

    with pytest.raises(SensitiveDataBlocked):
        asyncio.run(make_service(runner, FakeMemoryRuntime()).ask(
            user_id=17,
            message="我的 key 是 sk-test-12345678901234567890",
            conversation_id=None,
            reader=FakeReader(),
        ))

    assert runner.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("provider failed"), AgentProviderUnavailable),
        (GraphRecursionError("too many steps"), AgentExecutionLimitExceeded),
    ],
)
def test_agent_service_maps_runner_failures_without_verifying_failed_runs(error, expected):
    memory = FakeMemoryRuntime()
    with pytest.raises(expected):
        asyncio.run(make_service(FakeRunner(error=error), memory).ask(
            user_id=17,
            message="问题",
            conversation_id=None,
            reader=FakeReader(),
        ))

    assert memory.verified == []
