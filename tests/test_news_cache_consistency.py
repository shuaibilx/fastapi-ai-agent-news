import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from app.cache.news_cache import NewsCache, NewsCacheInvalidator
from app.cache.news_cache_maintenance import invalidate_news_cache
from app.core.config import Settings
from app.core.database import get_db
from app.main import app
from app.models.news import Category, News
from app.schemas.news import NewsPageCachePayload
from app.services.news import NewsPage, get_categories, get_news_page, increase_news_views


class InMemoryRedis:
    def __init__(self):
        self.values = {}
        self.ttl = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def setex(self, key, expire, value):
        self.values[key] = value
        self.ttl[key] = expire
        return True

    async def incr(self, key):
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value


class UnavailableRedis:
    async def get(self, key):
        raise ConnectionError("redis unavailable")

    async def set(self, key, value, nx=False):
        raise ConnectionError("redis unavailable")

    async def setex(self, key, expire, value):
        raise ConnectionError("redis unavailable")

    async def incr(self, key):
        raise ConnectionError("redis unavailable")


class ScalarResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values

    def scalar_one(self):
        return self.values


class NewsPageDb:
    def __init__(self, rows, total):
        self.rows = rows
        self.total = total
        self.statements = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        if len(self.statements) == 1:
            return ScalarResult(self.rows)
        return ScalarResult(self.total)


class CategoryDb:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    async def execute(self, statement):
        self.calls += 1
        return ScalarResult(self.rows)


class ViewUpdateResult:
    rowcount = 1


class ViewUpdateDb:
    def __init__(self):
        self.statements = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(str(statement))
        return ViewUpdateResult()

    async def commit(self):
        self.commits += 1


class CommitDb:
    def __init__(self, fail_commit=False):
        self.fail_commit = fail_commit
        self.rollbacks = 0

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("commit failed")

    async def rollback(self):
        self.rollbacks += 1


def news_row(news_id, publish_time):
    return News(
        id=news_id,
        title=f"新闻 {news_id}",
        description="摘要",
        content="正文",
        image=None,
        author="作者",
        category_id=2,
        views=5,
        publish_time=publish_time,
    )


def page_payload(news_id=1):
    return NewsPageCachePayload.model_validate({
        "list": [{
            "id": news_id,
            "title": f"新闻 {news_id}",
            "description": "摘要",
            "image": None,
            "author": "作者",
            "category_id": 2,
            "views": 5,
            "publish_time": "2026-08-31T12:00:00",
        }],
        "total": 1,
        "hasMore": False,
    })


class NewsCacheContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_is_part_of_each_page_cache_identity(self):
        cache = NewsCache(InMemoryRedis(), ttl_jitter=lambda ttl: ttl)

        first_generation = await cache.news_generation(2)
        first_key = cache.news_page_key(2, first_generation, 1, 10)
        next_generation = await cache.invalidate_news_categories({2})
        next_key = cache.news_page_key(2, next_generation[2], 1, 10)

        self.assertEqual(first_generation, 1)
        self.assertEqual(first_key, "news:list:v2:2:g1:p1:s10")
        self.assertEqual(next_key, "news:list:v2:2:g2:p1:s10")
        self.assertNotEqual(first_key, next_key)

    async def test_invalidated_generation_cannot_read_a_cached_old_page(self):
        redis = InMemoryRedis()
        cache = NewsCache(redis, ttl_jitter=lambda ttl: ttl)
        old_generation = await cache.news_generation(2)
        await cache.set_news_page(2, old_generation, 1, 10, page_payload())

        await cache.invalidate_news_categories({2})
        current_generation = await cache.news_generation(2)
        cached = await cache.get_news_page(2, current_generation, 1, 10)

        self.assertIsNone(cached)

    async def test_empty_page_uses_shorter_ttl_and_payload_round_trips(self):
        redis = InMemoryRedis()
        cache = NewsCache(
            redis,
            page_ttl_seconds=1800,
            empty_page_ttl_seconds=60,
            ttl_jitter=lambda ttl: ttl + 7,
        )
        generation = await cache.news_generation(9)
        empty = NewsPageCachePayload.model_validate({"list": [], "total": 0, "hasMore": False})

        await cache.set_news_page(9, generation, 3, 10, empty)
        cached = await cache.get_news_page(9, generation, 3, 10)
        key = cache.news_page_key(9, generation, 3, 10)

        self.assertEqual(redis.ttl[key], 67)
        self.assertEqual(cached.model_dump(mode="json", by_alias=True), empty.model_dump(mode="json", by_alias=True))

    async def test_category_cache_keeps_pagination_query_shapes_isolated(self):
        redis = InMemoryRedis()
        cache = NewsCache(redis, ttl_jitter=lambda ttl: ttl)
        generation = await cache.categories_generation()
        first_slice = [{"id": 1, "name": "头条"}]

        await cache.set_categories(generation, 0, 1, first_slice)

        self.assertEqual(await cache.get_categories(generation, 0, 1), first_slice)
        self.assertIsNone(await cache.get_categories(generation, 1, 1))
        self.assertEqual(
            cache.categories_key(generation, 0, 1),
            "news:categories:v2:g1:skip0:limit1",
        )

    async def test_cache_outage_returns_unavailable_without_raising(self):
        cache = NewsCache(UnavailableRedis(), ttl_jitter=lambda ttl: ttl)

        self.assertIsNone(await cache.news_generation(2))
        self.assertFalse(await cache.set_news_page(2, 1, 1, 10, page_payload()))
        self.assertIsNone(await cache.invalidate_news_categories({2}))

    async def test_news_mutation_invalidates_every_affected_category_generation(self):
        redis = InMemoryRedis()
        cache = NewsCache(redis, ttl_jitter=lambda ttl: ttl)
        invalidator = NewsCacheInvalidator(cache)
        old_generation = await cache.news_generation(2)
        await cache.set_news_page(2, old_generation, 2, 10, page_payload())

        generations = await invalidator.after_news_commit(previous_category_id=2, current_category_id=3)

        self.assertEqual(generations, {2: 2, 3: 1})
        self.assertIsNone(await cache.get_news_page(2, 2, 2, 10))

    async def test_create_update_and_delete_each_advance_the_relevant_generation(self):
        cache = NewsCache(InMemoryRedis(), ttl_jitter=lambda ttl: ttl)
        invalidator = NewsCacheInvalidator(cache)

        created = await invalidator.after_news_commit(previous_category_id=None, current_category_id=4)
        updated = await invalidator.after_news_commit(previous_category_id=4, current_category_id=4)
        deleted = await invalidator.after_news_commit(previous_category_id=4, current_category_id=None)

        self.assertEqual(created, {4: 1})
        self.assertEqual(updated, {4: 2})
        self.assertEqual(deleted, {4: 3})

    async def test_failed_database_commit_does_not_advance_cache_generation(self):
        cache = NewsCache(InMemoryRedis(), ttl_jitter=lambda ttl: ttl)
        invalidator = NewsCacheInvalidator(cache)

        async def write_news():
            return "pending write"

        with self.assertRaisesRegex(RuntimeError, "commit failed"):
            await invalidator.commit_news_write(
                CommitDb(fail_commit=True),
                write_news,
                previous_category_id=None,
                current_category_id=5,
            )

        self.assertEqual(await cache.news_generation(5), 1)

    async def test_maintenance_invalidation_only_touches_news_cache_generations(self):
        redis = InMemoryRedis()
        redis.values["ai:summary:v1:1:hash"] = "摘要"
        redis.values["ai:news:vector:v1:1"] = "向量"
        redis.values["checkpoint:thread"] = "会话"
        cache = NewsCache(redis, ttl_jitter=lambda ttl: ttl)

        success = await invalidate_news_cache(cache, category_ids=[2], include_categories=True)

        self.assertTrue(success)
        self.assertEqual(redis.values["news:cache:category:2:generation"], "1")
        self.assertEqual(redis.values["news:cache:categories:generation"], "1")
        self.assertEqual(redis.values["ai:summary:v1:1:hash"], "摘要")
        self.assertEqual(redis.values["ai:news:vector:v1:1"], "向量")
        self.assertEqual(redis.values["checkpoint:thread"], "会话")


class NewsCacheSettingsTests(unittest.TestCase):
    def test_defaults_expose_normal_empty_and_jitter_ttl_settings(self):
        settings = Settings(_env_file=None)

        self.assertEqual(settings.news_list_cache_ttl_seconds, 1800)
        self.assertEqual(settings.news_list_empty_cache_ttl_seconds, 60)
        self.assertEqual(settings.news_cache_ttl_jitter_seconds, 180)


class NewsPageReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_read_uses_one_cached_snapshot_with_stable_order(self):
        cache = NewsCache(InMemoryRedis(), ttl_jitter=lambda ttl: ttl)
        db = NewsPageDb(
            [
                news_row(8, datetime(2026, 8, 30, 12, 0, 0)),
                news_row(7, datetime(2026, 8, 30, 12, 0, 0)),
            ],
            2,
        )

        first = await get_news_page(db, category_id=2, page=1, page_size=10, cache=cache)
        second = await get_news_page(db, category_id=2, page=1, page_size=10, cache=cache)

        self.assertEqual([item.id for item in first.list], [8, 7])
        self.assertEqual(first.total, 2)
        self.assertFalse(first.has_more)
        self.assertEqual([item.id for item in second.list], [8, 7])
        self.assertEqual(len(db.statements), 2)
        self.assertIn("ORDER BY news.publish_time DESC, news.id DESC", db.statements[0])

    async def test_category_read_falls_back_to_database_when_redis_is_unavailable(self):
        db = CategoryDb([Category(id=2, name="科技", sort_order=3)])
        categories = await get_categories(db, cache=NewsCache(UnavailableRedis()))

        self.assertEqual(categories, [{"id": 2, "name": "科技", "sort_order": 3}])
        self.assertEqual(db.calls, 1)

    async def test_news_page_falls_back_to_database_when_redis_is_unavailable(self):
        db = NewsPageDb([news_row(8, datetime(2026, 8, 30, 12, 0, 0))], 1)

        page = await get_news_page(
            db,
            category_id=2,
            page=1,
            page_size=10,
            cache=NewsCache(UnavailableRedis()),
        )

        self.assertEqual([item.id for item in page.list], [8])
        self.assertEqual(page.total, 1)
        self.assertEqual(len(db.statements), 2)

    async def test_view_update_does_not_invalidate_an_entire_news_category(self):
        db = ViewUpdateDb()

        updated = await increase_news_views(db, 8)

        self.assertTrue(updated)
        self.assertEqual(db.commits, 1)
        self.assertIn("SET views=(news.views +", db.statements[0])


async def override_db():
    yield object()


class NewsListApiTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_db] = override_db

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_list_response_uses_the_single_page_snapshot(self):
        page = NewsPage(list=[news_row(8, datetime(2026, 8, 30, 12, 0, 0))], total=3, has_more=True)
        with patch("app.api.routers.news.news.get_news_page", new=AsyncMock(return_value=page)):
            with TestClient(app) as client:
                response = client.get("/api/news/list?categoryId=2&page=1&pageSize=10")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 3)
        self.assertTrue(response.json()["data"]["hasMore"])
        self.assertEqual(response.json()["data"]["list"][0]["id"], 8)


if __name__ == "__main__":
    unittest.main()
