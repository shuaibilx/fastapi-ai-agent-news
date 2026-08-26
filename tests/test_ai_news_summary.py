import unittest

from app.ai import summarization


class InMemoryRedis:
    def __init__(self):
        self.values = {}
        self.ttl = {}

    async def get(self, key):
        return self.values.get(key)

    async def setex(self, key, expire, value):
        self.values[key] = value
        self.ttl[key] = expire


class UnavailableRedis:
    async def get(self, key):
        raise ConnectionError("Redis is unavailable")

    async def setex(self, key, expire, value):
        raise ConnectionError("Redis is unavailable")


class FakeSummaryGateway:
    def __init__(self, summary="AI 生成摘要"):
        self.summary = summary
        self.calls = []

    async def summarize(self, title, content):
        self.calls.append((title, content))
        return self.summary


class FailingSummaryGateway:
    async def summarize(self, title, content):
        raise RuntimeError("provider timed out")


class SummaryContentVersionTests(unittest.TestCase):
    def test_hash_is_stable_for_the_same_title_and_content(self):
        content_hash = getattr(summarization, "build_content_hash", lambda *_: "")(
            "AI 新闻", "这是新闻正文。"
        )

        self.assertEqual(
            content_hash,
            "71c6b9b29ded4e87fd611c42863db309f7651619f12a15c90528eaf4b661d91f",
        )

    def test_cache_key_changes_when_article_content_changes(self):
        build_hash = getattr(summarization, "build_content_hash", lambda *_: "")
        build_key = getattr(summarization, "build_summary_cache_key", lambda *_: "")

        original_key = build_key(7, build_hash("AI 新闻", "第一版正文"))
        changed_key = build_key(7, build_hash("AI 新闻", "第二版正文"))

        self.assertEqual(original_key, "ai:summary:v1:7:24e211a260d687296f296d00ad12ba2941b938611562f14643e5cd5d745c1236")
        self.assertNotEqual(original_key, changed_key)


class SummaryCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_returns_the_summary_written_for_a_content_version(self):
        cache_class = getattr(summarization, "SummaryCache", None)
        self.assertIsNotNone(cache_class, "SummaryCache must be available to cache AI summaries")

        redis = InMemoryRedis()
        cache = cache_class(redis, ttl_seconds=120)
        await cache.set("ai:summary:v1:7:version", "一段可靠的摘要")

        result = await cache.get("ai:summary:v1:7:version")

        self.assertEqual(result.status, "hit")
        self.assertEqual(result.summary, "一段可靠的摘要")
        self.assertEqual(redis.ttl["ai:summary:v1:7:version"], 120)

    async def test_cache_failure_is_not_reported_as_a_normal_miss(self):
        cache_class = getattr(summarization, "SummaryCache", None)
        self.assertIsNotNone(cache_class, "SummaryCache must expose cache availability")

        with self.assertLogs("app.ai.summarization.cache", level="WARNING"):
            result = await cache_class(UnavailableRedis(), ttl_seconds=120).get("any-key")

        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.summary)


class NewsSummaryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_miss_generates_and_stores_a_summary(self):
        service_class = getattr(summarization, "NewsSummaryService", None)
        self.assertIsNotNone(service_class, "NewsSummaryService must orchestrate generation and caching")

        redis = InMemoryRedis()
        gateway = FakeSummaryGateway("新闻的三个关键点")
        service = service_class(
            cache=summarization.SummaryCache(redis, ttl_seconds=120),
            gateway=gateway,
        )

        result = await service.summarize(7, "AI 新闻", "这是新闻正文。")

        self.assertEqual(result.summary, "新闻的三个关键点")
        self.assertEqual(result.cache_status, "miss")
        self.assertEqual(gateway.calls, [("AI 新闻", "这是新闻正文。")])
        self.assertEqual(len(redis.values), 1)

    async def test_cache_hit_returns_stored_summary_without_generating_again(self):
        service_class = getattr(summarization, "NewsSummaryService", None)
        self.assertIsNotNone(service_class, "NewsSummaryService must read a cached summary")

        redis = InMemoryRedis()
        cache = summarization.SummaryCache(redis, ttl_seconds=120)
        content_hash = summarization.build_content_hash("AI 新闻", "这是新闻正文。")
        await cache.set(summarization.build_summary_cache_key(7, content_hash), "已缓存摘要")
        gateway = FakeSummaryGateway("不应生成")

        result = await service_class(cache=cache, gateway=gateway).summarize(7, "AI 新闻", "这是新闻正文。")

        self.assertEqual(result.summary, "已缓存摘要")
        self.assertEqual(result.cache_status, "hit")
        self.assertEqual(gateway.calls, [])

    async def test_cache_outage_returns_generated_summary_as_unavailable(self):
        service_class = getattr(summarization, "NewsSummaryService", None)
        self.assertIsNotNone(service_class, "NewsSummaryService must degrade when Redis is unavailable")

        gateway = FakeSummaryGateway("无缓存也可返回")
        service = service_class(
            cache=summarization.SummaryCache(UnavailableRedis(), ttl_seconds=120),
            gateway=gateway,
        )

        with self.assertLogs("app.ai.summarization.cache", level="WARNING"):
            result = await service.summarize(7, "AI 新闻", "这是新闻正文。")

        self.assertEqual(result.summary, "无缓存也可返回")
        self.assertEqual(result.cache_status, "unavailable")

    async def test_provider_failure_is_reported_without_caching_a_summary(self):
        service_class = getattr(summarization, "NewsSummaryService", None)
        self.assertIsNotNone(service_class, "NewsSummaryService must report provider failures")

        redis = InMemoryRedis()
        service = service_class(
            cache=summarization.SummaryCache(redis, ttl_seconds=120),
            gateway=FailingSummaryGateway(),
        )

        with self.assertRaises(summarization.SummaryProviderUnavailable):
            await service.summarize(7, "AI 新闻", "这是新闻正文。")
        self.assertEqual(redis.values, {})

    async def test_blank_provider_output_is_rejected_without_caching(self):
        service_class = getattr(summarization, "NewsSummaryService", None)
        self.assertIsNotNone(service_class, "NewsSummaryService must validate provider output")

        redis = InMemoryRedis()
        service = service_class(
            cache=summarization.SummaryCache(redis, ttl_seconds=120),
            gateway=FakeSummaryGateway("   "),
        )

        with self.assertRaises(summarization.SummaryProviderUnavailable):
            await service.summarize(7, "AI 新闻", "这是新闻正文。")
        self.assertEqual(redis.values, {})

    async def test_changed_content_generates_a_new_cached_summary(self):
        service_class = getattr(summarization, "NewsSummaryService", None)
        self.assertIsNotNone(service_class, "NewsSummaryService must use content-versioned cache keys")

        redis = InMemoryRedis()
        gateway = FakeSummaryGateway("更新后的摘要")
        service = service_class(
            cache=summarization.SummaryCache(redis, ttl_seconds=120),
            gateway=gateway,
        )

        await service.summarize(7, "AI 新闻", "第一版正文")
        result = await service.summarize(7, "AI 新闻", "第二版正文")

        self.assertEqual(result.cache_status, "miss")
        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual(len(redis.values), 2)


if __name__ == "__main__":
    unittest.main()

class DeepSeekGatewayConstructionTests(unittest.TestCase):
    def test_summary_gateway_uses_deepseek_integration(self):
        import inspect
        import app.ai.summarization.gateway as summary_gw
        self.assertIn("ChatDeepSeek", inspect.getsource(summary_gw))
        self.assertNotIn("from langchain_openai", inspect.getsource(summary_gw))

    def test_qa_gateway_uses_deepseek_integration(self):
        import inspect
        import app.ai.rag.gateway as rag_gw
        self.assertIn("ChatDeepSeek", inspect.getsource(rag_gw))
        self.assertNotIn("from langchain_openai", inspect.getsource(rag_gw))


