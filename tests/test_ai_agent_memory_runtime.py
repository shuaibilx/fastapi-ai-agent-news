import asyncio

from app.ai.agent.checkpointer import AgentThreadIdFactory
from app.ai.agent.memory_runtime import (
    AgentMemorySession,
    CheckpointerMemoryRuntime,
)
from app.ai.agent.memory_store import MemoryStatus


class FakeSaver:
    async def aget_tuple(self, config):
        return self.checkpoints.get(config["configurable"]["thread_id"])

    def __init__(self, checkpoints=None):
        self.checkpoints = checkpoints or {}


def test_memory_runtime_reports_loaded_and_builds_user_scoped_config():
    async def scenario():
        saver = FakeSaver({AgentThreadIdFactory.derive(7, "7c1f07e2-46db-4ce1-9724-f428561d8f45"): object()})
        runtime = CheckpointerMemoryRuntime(lambda: saver)

        session = await runtime.prepare(7, "7c1f07e2-46db-4ce1-9724-f428561d8f45")

        assert isinstance(session, AgentMemorySession)
        assert session.status is MemoryStatus.LOADED
        assert session.config["configurable"]["thread_id"].startswith("news-agent:v2:user:7:")

    asyncio.run(scenario())


def test_memory_runtime_uses_stateless_mode_when_checkpointer_is_unavailable():
    async def scenario():
        runtime = CheckpointerMemoryRuntime(lambda: None)

        session = await runtime.prepare(7, "7c1f07e2-46db-4ce1-9724-f428561d8f45")

        assert session.status is MemoryStatus.UNAVAILABLE
        assert session.config == {}

    asyncio.run(scenario())


def test_memory_runtime_treats_missing_thread_as_empty():
    async def scenario():
        runtime = CheckpointerMemoryRuntime(lambda: FakeSaver())

        session = await runtime.prepare(7, "7c1f07e2-46db-4ce1-9724-f428561d8f45")

        assert session.status is MemoryStatus.EMPTY
        assert session.config["configurable"]["thread_id"]

    asyncio.run(scenario())
