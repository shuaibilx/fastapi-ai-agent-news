import asyncio
from uuid import UUID
from unittest.mock import patch

import pytest

from app.ai.agent.checkpointer import (
    AgentThreadIdFactory,
    RedisCheckpointManager,
)
from app.main import app, lifespan


class FakeSaver:
    def __init__(self):
        self.entered = 0
        self.closed = 0
        self.deleted = []

    async def adelete_thread(self, thread_id):
        self.deleted.append(thread_id)

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *_args):
        self.closed += 1


def test_thread_id_is_server_derived_and_user_scoped():
    conversation_id = "7c1f07e2-46db-4ce1-9724-f428561d8f45"

    first = AgentThreadIdFactory.derive(17, conversation_id)
    second = AgentThreadIdFactory.derive(18, conversation_id)

    assert first != second
    assert first.startswith("news-agent:v2:user:17:conversation:")
    assert str(UUID(first.rsplit(":", 1)[-1])) == conversation_id


def test_thread_config_contains_only_server_derived_thread_id():
    config = AgentThreadIdFactory.config(17, "7c1f07e2-46db-4ce1-9724-f428561d8f45")

    assert set(config) == {"configurable"}
    assert set(config["configurable"]) == {"thread_id"}
    assert config["configurable"]["thread_id"].startswith("news-agent:v2:user:17:")


def test_checkpoint_manager_initializes_once_and_closes_owned_saver():
    savers = []

    def factory(_url, _ttl):
        saver = FakeSaver()
        savers.append(saver)
        return saver

    async def scenario():
        manager = RedisCheckpointManager(
            "redis://localhost:6379/15",
            ttl_seconds=600,
            saver_factory=factory,
        )
        assert await manager.initialize() is True
        assert await manager.initialize() is True
        assert manager.available is True
        assert len(savers) == 1
        await manager.close()
        assert savers[0].closed == 1

    asyncio.run(scenario())


def test_checkpoint_manager_reports_initialization_failure_without_fallback_to_old_store():
    def factory(_url, _ttl):
        raise RuntimeError("Redis Search module unavailable")

    async def scenario():
        manager = RedisCheckpointManager(
            "redis://localhost:6379/15",
            ttl_seconds=600,
            saver_factory=factory,
        )
        assert await manager.initialize() is False
        assert manager.available is False
        assert manager.checkpointer is None

    asyncio.run(scenario())


def test_checkpoint_manager_deletes_only_the_derived_thread():
    async def scenario():
        saver = FakeSaver()
        manager = RedisCheckpointManager(
            "redis://localhost:6379/15",
            ttl_seconds=600,
            saver_factory=lambda _url, _ttl: saver,
        )
        await manager.initialize()

        assert await manager.delete_thread(7, "7c1f07e2-46db-4ce1-9724-f428561d8f45") is True
        assert saver.deleted == [
            "news-agent:v2:user:7:conversation:7c1f07e2-46db-4ce1-9724-f428561d8f45",
        ]

    asyncio.run(scenario())


def test_application_lifespan_owns_checkpointer_lifecycle():
    class FakeManager:
        def __init__(self, *_args, **_kwargs):
            self.initialized = 0
            self.closed = 0

        async def initialize(self):
            self.initialized += 1
            return True

        async def close(self):
            self.closed += 1

    async def scenario():
        with patch("app.main.RedisCheckpointManager", FakeManager):
            async with lifespan(app):
                manager = app.state.agent_checkpoint_manager
                assert manager.initialized == 1
            assert manager.closed == 1

    asyncio.run(scenario())
