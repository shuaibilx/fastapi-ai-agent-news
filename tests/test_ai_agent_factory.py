import asyncio
from itertools import count

import pytest
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware import SummarizationMiddleware
from langchain.messages import AIMessage, HumanMessage
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langgraph.checkpoint.memory import MemorySaver
from pydantic import PrivateAttr

from app.ai.agent.factory import build_news_agent
from app.ai.agent.tools import AgentRuntimeContext


class ToolCallingFakeModel(GenericFakeChatModel):
    _bound_tools: list = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self


class EmptyReader:
    async def search_news(self, query, limit):
        return []

    async def get_news_detail(self, news_id):
        return None

    async def list_favorites(self, user_id, page, page_size):
        return [], 0

    async def list_history(self, user_id, page, page_size):
        return [], 0


def context():
    return AgentRuntimeContext(
        user_id=7,
        reader=EmptyReader(),
        retrieval_limit=5,
        page_size_limit=10,
        tool_result_max_tokens=200,
    )


def test_news_agent_binds_only_the_four_approved_read_only_tools():
    model = ToolCallingFakeModel(messages=iter([AIMessage(content="直接回答")]))
    agent = build_news_agent(
        model=model,
        max_iterations=3,
        max_input_tokens=1000,
        tool_result_max_tokens=200,
    )

    result = asyncio.run(agent.ainvoke(
        {"messages": [HumanMessage(content="你好")]},
        context=context(),
    ))

    assert result["messages"][-1].content == "直接回答"
    assert {tool.name for tool in model._bound_tools} == {
        "search_news_knowledge",
        "get_news_detail",
        "list_my_favorites",
        "list_my_history",
    }
    assert all("delete" not in tool.name and "remove" not in tool.name for tool in model._bound_tools)


def test_news_agent_stops_a_repeating_tool_loop_at_the_model_call_limit():
    responses = (
        AIMessage(
            content="",
            tool_calls=[{
                "name": "search_news_knowledge",
                "args": {"query": "AI", "limit": 1},
                "id": f"call-{index}",
            }],
        )
        for index in count(1)
    )
    model = ToolCallingFakeModel(messages=responses)
    agent = build_news_agent(
        model=model,
        max_iterations=2,
        max_input_tokens=1000,
        tool_result_max_tokens=200,
    )

    with pytest.raises(ModelCallLimitExceededError):
        asyncio.run(agent.ainvoke(
            {"messages": [HumanMessage(content="一直检索")]},
            context=context(),
        ))


def test_news_agent_registers_token_summary_and_server_side_pii_middleware():
    model = ToolCallingFakeModel(messages=iter([AIMessage(content="直接回答")]))
    agent = build_news_agent(
        model=model,
        max_iterations=3,
        max_input_tokens=1000,
        tool_result_max_tokens=200,
        summary_trigger_tokens=600,
        summary_keep_tokens=200,
        summary_model=model,
    )

    node_names = set(agent.nodes)
    assert "SummarizationMiddleware.before_model" in node_names
    assert any(name.startswith("PIIMiddleware") for name in node_names)


def test_news_agent_summarizes_old_messages_when_token_trigger_is_reached():
    model = ToolCallingFakeModel(messages=iter([AIMessage(content="最终回答")]))
    summary_model = ToolCallingFakeModel(messages=iter([AIMessage(content="旧对话摘要")]))
    agent = build_news_agent(
        model=model,
        max_iterations=3,
        max_input_tokens=1000,
        tool_result_max_tokens=200,
        summary_trigger_tokens=10,
        summary_keep_tokens=3,
        summary_model=summary_model,
    )

    result = asyncio.run(agent.ainvoke(
        {
            "messages": [
                HumanMessage(content="旧问题" * 10),
                AIMessage(content="旧回答" * 10),
                HumanMessage(content="当前问题"),
            ],
        },
        context=context(),
    ))

    contents = [item.content for item in result["messages"]]
    assert any("旧对话摘要" in content for content in contents)
    assert contents[-1] == "最终回答"


def test_persisted_summary_keeps_multi_tool_session_available_for_follow_up():
    model = ToolCallingFakeModel(messages=iter([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "search_news_knowledge",
                "args": {"query": "人工智能新闻", "limit": 1},
                "id": "tool-1",
            }],
        ),
        AIMessage(content="第一次回答"),
        AIMessage(content="后续回答"),
    ]))
    summary_model = ToolCallingFakeModel(messages=iter([
        AIMessage(content="保留了首次检索结论"),
        AIMessage(content="保留了首次检索结论"),
        AIMessage(content="保留了首次检索结论"),
    ]))
    agent = build_news_agent(
        model=model,
        max_iterations=3,
        max_input_tokens=1000,
        tool_result_max_tokens=200,
        summary_trigger_tokens=20,
        summary_keep_tokens=8,
        summary_model=summary_model,
        checkpointer=MemorySaver(),
    )

    config = {"configurable": {"thread_id": "summary-tool-test"}}
    asyncio.run(agent.ainvoke(
        {"messages": [HumanMessage(content="请检索人工智能新闻")]},
        context=context(),
        config=config,
    ))
    result = asyncio.run(agent.ainvoke(
        {"messages": [HumanMessage(content="基于刚才的检索继续回答")]},
        context=context(),
        config=config,
    ))

    contents = [item.content for item in result["messages"]]
    assert any("保留了首次检索结论" in content for content in contents)
    assert contents[-1] == "后续回答"
