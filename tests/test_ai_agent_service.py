import asyncio

import pytest
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from app.ai.agent.memory import ConversationTurn, TokenBudgetPolicy
from app.ai.agent.memory_store import MemoryLoadResult, MemoryStatus
from app.ai.agent.service import (
    AgentExecutionLimitExceeded,
    AgentProviderUnavailable,
    AgentService,
)


class FakeMemoryStore:
    def __init__(self, load_result=None, append_status=MemoryStatus.LOADED):
        self.load_result = load_result or MemoryLoadResult([], MemoryStatus.EMPTY)
        self.append_status = append_status
        self.appended = []

    async def load(self, user_id, conversation_id):
        return self.load_result

    async def append(self, user_id, conversation_id, turn):
        self.appended.append((user_id, conversation_id, turn))
        return self.append_status


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
        memory_store=memory,
        budget_policy=TokenBudgetPolicy(
            max_rounds=5,
            max_history_tokens=1000,
            max_input_tokens=2000,
            count_tokens=len,
        ),
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
            "citations": [
                {"news_id": news_id, "title": f"标题{news_id}", "excerpt": "摘录"},
            ],
            "tool_summary": {
                "name": name,
                "status": "success",
                "summary": "执行成功",
            },
        },
    )


def test_agent_service_loads_history_runs_with_trusted_context_and_saves_final_turn():
    memory = FakeMemoryStore(MemoryLoadResult([
        ConversationTurn("上一问", "上一答", "2026-08-27T00:00:00+00:00"),
    ], MemoryStatus.LOADED))
    runner = FakeRunner()
    service = make_service(runner, memory)

    result = asyncio.run(service.ask(
        user_id=17,
        message="现在的问题",
        conversation_id="7c1f07e2-46db-4ce1-9724-f428561d8f45",
        reader=FakeReader(),
    ))

    payload, context, config = runner.calls[0]
    assert [(type(item), item.content) for item in payload["messages"]] == [
        (HumanMessage, "上一问"),
        (AIMessage, "上一答"),
        (HumanMessage, "现在的问题"),
    ]
    assert context.user_id == 17
    assert context.reader.__class__ is FakeReader
    assert config["recursion_limit"] == 11
    assert result.answer == "最终回答"
    assert result.memory_status is MemoryStatus.LOADED
    assert memory.appended[0][2].user_message == "现在的问题"
    assert memory.appended[0][2].assistant_message == "最终回答"


def test_agent_service_collects_multiple_tool_results_and_deduplicates_sources():
    memory = FakeMemoryStore()
    runner = FakeRunner([
        tool_result("call-1", 11),
        tool_result("call-2", 11, "get_news_detail"),
        tool_result("call-3", 12, "list_my_history"),
        AIMessage(content="综合回答"),
    ])

    result = asyncio.run(make_service(runner, memory).ask(
        user_id=17,
        message="综合分析",
        conversation_id=None,
        reader=FakeReader(),
    ))

    assert [item.news_id for item in result.citations] == [11, 12]
    assert [item.name for item in result.tool_calls] == [
        "search_news_knowledge", "get_news_detail", "list_my_history",
    ]
    assert result.memory_status is MemoryStatus.EMPTY
    assert result.conversation_id


@pytest.mark.parametrize(
    ("load_status", "append_status"),
    [
        (MemoryStatus.UNAVAILABLE, MemoryStatus.LOADED),
        (MemoryStatus.EMPTY, MemoryStatus.UNAVAILABLE),
    ],
)
def test_agent_service_reports_unavailable_when_redis_read_or_write_fails(
    load_status,
    append_status,
):
    memory = FakeMemoryStore(
        MemoryLoadResult([], load_status),
        append_status=append_status,
    )

    result = asyncio.run(make_service(FakeRunner(), memory).ask(
        user_id=17,
        message="问题",
        conversation_id=None,
        reader=FakeReader(),
    ))

    assert result.answer == "最终回答"
    assert result.memory_status is MemoryStatus.UNAVAILABLE


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("provider failed"), AgentProviderUnavailable),
        (GraphRecursionError("too many steps"), AgentExecutionLimitExceeded),
    ],
)
def test_agent_service_maps_runner_failures_and_never_saves_failed_turns(error, expected):
    memory = FakeMemoryStore()
    service = make_service(FakeRunner(error=error), memory)

    with pytest.raises(expected):
        asyncio.run(service.ask(
            user_id=17,
            message="问题",
            conversation_id=None,
            reader=FakeReader(),
        ))

    assert memory.appended == []
