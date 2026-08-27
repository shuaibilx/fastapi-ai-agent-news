import asyncio
import json

from app.ai.agent.memory import ConversationTurn
from app.ai.agent.memory_store import ConversationMemoryStore, MemoryStatus


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.operations = []

    def rpush(self, key, value):
        self.operations.append(("rpush", key, value))
        return self

    def ltrim(self, key, start, end):
        self.operations.append(("ltrim", key, start, end))
        return self

    def expire(self, key, seconds):
        self.operations.append(("expire", key, seconds))
        return self

    async def execute(self):
        for operation in self.operations:
            name, key, *args = operation
            if name == "rpush":
                self.redis.values.setdefault(key, []).append(args[0])
            elif name == "ltrim":
                start, end = args
                values = self.redis.values.get(key, [])
                self.redis.values[key] = values[start:] if end == -1 else values[start:end + 1]
            elif name == "expire":
                self.redis.expirations[key] = args[0]


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    def pipeline(self, transaction=True):
        assert transaction is True
        return FakePipeline(self)

    async def lrange(self, key, start, end):
        values = self.values.get(key, [])
        return values[start:] if end == -1 else values[start:end + 1]

    async def expire(self, key, seconds):
        if key in self.values:
            self.expirations[key] = seconds
            return True
        return False


class FailingRedis(FakeRedis):
    async def lrange(self, key, start, end):
        raise ConnectionError("redis unavailable")

    def pipeline(self, transaction=True):
        raise ConnectionError("redis unavailable")


def turn(index: int) -> ConversationTurn:
    return ConversationTurn(
        user_message=f"问题{index}",
        assistant_message=f"回答{index}",
        completed_at=f"2026-08-27T00:00:0{index}+00:00",
    )


def test_store_keeps_latest_five_turns_and_isolates_users():
    redis = FakeRedis()
    store = ConversationMemoryStore(redis, ttl_seconds=600, max_rounds=5)

    for index in range(1, 7):
        assert asyncio.run(store.append(7, "session-a", turn(index))) is MemoryStatus.LOADED

    result = asyncio.run(store.load(7, "session-a"))
    other_user = asyncio.run(store.load(8, "session-a"))

    assert result.status is MemoryStatus.LOADED
    assert [item.user_message for item in result.turns] == [
        "问题2", "问题3", "问题4", "问题5", "问题6",
    ]
    assert other_user.status is MemoryStatus.EMPTY
    assert other_user.turns == []
    assert set(redis.values) == {"ai:agent:memory:v1:7:session-a"}


def test_store_persists_only_the_completed_turn_fields_and_refreshes_ttl():
    redis = FakeRedis()
    store = ConversationMemoryStore(redis, ttl_seconds=900, max_rounds=5)

    asyncio.run(store.append(3, "session-b", turn(1)))
    asyncio.run(store.load(3, "session-b"))

    key = "ai:agent:memory:v1:3:session-b"
    assert set(json.loads(redis.values[key][0])) == {
        "user_message", "assistant_message", "completed_at",
    }
    assert redis.expirations[key] == 900


def test_store_degrades_to_unavailable_when_redis_fails():
    store = ConversationMemoryStore(FailingRedis(), ttl_seconds=900, max_rounds=5)

    loaded = asyncio.run(store.load(3, "session-c"))
    appended = asyncio.run(store.append(3, "session-c", turn(1)))

    assert loaded.status is MemoryStatus.UNAVAILABLE
    assert loaded.turns == []
    assert appended is MemoryStatus.UNAVAILABLE
