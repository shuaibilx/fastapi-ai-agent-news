import asyncio
import os
from uuid import uuid4

from langchain.messages import AIMessage, HumanMessage
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.graph import END, START, MessagesState, StateGraph
import pytest


pytestmark = pytest.mark.skipif(
    "AGENT_TEST_REDIS_URL" not in os.environ,
    reason="需要显式配置隔离 Redis 才运行集成测试",
)


def _redis_url() -> str:
    # RediSearch indexes used by langgraph-checkpoint-redis must be created in DB 0.
    return os.getenv("AGENT_TEST_REDIS_URL", "redis://127.0.0.1:6380/0")


async def _run_checkpointer_round_trip() -> None:
    async with AsyncRedisSaver.from_conn_string(
        _redis_url(),
        ttl={"default_ttl": 60, "refresh_on_read": True},
    ) as checkpointer:
        builder = StateGraph(MessagesState)

        async def respond(state: MessagesState):
            return {"messages": [AIMessage(content="已保存到线程状态") ]}

        builder.add_node("respond", respond)
        builder.add_edge(START, "respond")
        builder.add_edge("respond", END)
        graph = builder.compile(checkpointer=checkpointer)

        thread_id = f"integration-{uuid4()}"
        config = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="保存这条测试消息")]},
            config,
        )

        assert result["messages"][-1].content == "已保存到线程状态"
        resumed = await graph.ainvoke(
            {"messages": [HumanMessage(content="恢复这条测试消息")]},
            config,
        )
        assert any(
            item.content == "保存这条测试消息"
            for item in resumed["messages"]
            if isinstance(item, HumanMessage)
        )
        checkpoint = await checkpointer.aget_tuple(config)
        assert checkpoint is not None
        assert checkpoint.config["configurable"]["thread_id"] == thread_id

        await checkpointer.adelete_thread(thread_id)
        assert await checkpointer.aget_tuple(config) is None


async def _run_checkpointer_expiration_check() -> None:
    async with AsyncRedisSaver.from_conn_string(
        _redis_url(),
        ttl={"default_ttl": 0.05, "refresh_on_read": False},
    ) as checkpointer:
        builder = StateGraph(MessagesState)

        async def respond(state: MessagesState):
            return {"messages": [AIMessage(content="短期状态") ]}

        builder.add_node("respond", respond)
        builder.add_edge(START, "respond")
        builder.add_edge("respond", END)
        graph = builder.compile(checkpointer=checkpointer)
        expired_id = f"expire-{uuid4()}"
        expired_config = {"configurable": {"thread_id": expired_id}}

        await graph.ainvoke({"messages": [HumanMessage(content="会过期")]}, expired_config)
        await asyncio.sleep(4)

        assert await checkpointer.aget_tuple(expired_config) is None


def test_async_redis_saver_can_initialize_persist_and_clean_a_thread():
    asyncio.run(_run_checkpointer_round_trip())


def test_async_redis_saver_expires_inactive_thread_state():
    asyncio.run(_run_checkpointer_expiration_check())
