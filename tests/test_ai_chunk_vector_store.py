import unittest

from redis.exceptions import ResponseError


class BuildAwareRedisStack:
    def __init__(self):
        self.hashes = {
            "news:list:v2:1:g1:p1:s10": {"payload": "keep"},
            "ai:summary:v1:9:hash": {"summary": "keep"},
            "checkpoint:session-a": {"state": "keep"},
        }
        self.indexes = {}
        self.aliases = {}
        self.commands = []
        self.search_response = None

    async def execute_command(self, *parts):
        self.commands.append(parts)
        command = str(parts[0]).upper()
        if command == "FT.INFO":
            requested = str(parts[1])
            concrete = self.aliases.get(requested, requested)
            if concrete not in self.indexes:
                raise ResponseError("Unknown Index name")
            return [b"index_name", concrete.encode()]
        if command == "FT.CREATE":
            index_name = str(parts[1])
            prefix_position = parts.index("PREFIX")
            self.indexes[index_name] = str(parts[prefix_position + 2])
            return "OK"
        if command == "FT.SEARCH":
            if self.search_response is not None:
                return self.search_response
            requested = str(parts[1])
            concrete = self.aliases.get(requested, requested)
            prefix = self.indexes[concrete]
            return [sum(key.startswith(prefix) for key in self.hashes)]
        if command in {"FT.ALIASADD", "FT.ALIASUPDATE"}:
            alias, target = str(parts[1]), str(parts[2])
            if command == "FT.ALIASUPDATE" and alias not in self.aliases:
                raise ResponseError("Alias does not exist")
            self.aliases[alias] = target
            return "OK"
        if command == "FT.DROPINDEX":
            self.indexes.pop(str(parts[1]), None)
            return "OK"
        raise AssertionError(f"unexpected command: {parts}")

    async def scan(self, cursor=0, match=None, count=None):
        prefix = str(match).removesuffix("*") if match else ""
        return 0, [key for key in self.hashes if key.startswith(prefix)]

    async def delete(self, *keys):
        for key in keys:
            self.hashes.pop(str(key), None)

    async def hset(self, key, mapping):
        self.hashes[str(key)] = dict(mapping)


def chunk_document(*, news_id=7, chunk_index=0, embedding=None):
    from app.ai.rag.vector_store import NewsVectorDocument

    return NewsVectorDocument(
        news_id=news_id,
        chunk_id=f"{news_id}:{chunk_index}:abcdef",
        chunk_index=chunk_index,
        start_index=chunk_index * 100,
        end_index=chunk_index * 100 + 20,
        title="人工智能发展",
        description="技术新闻",
        chunk_text=f"第 {chunk_index} 个真正命中的正文片段",
        content_hash="abcdef",
        category_id=2,
        publish_time="2026-09-01T08:00:00",
        views=12,
        embedding=embedding or [0.1, 0.2],
    )


class ChunkVectorStoreTests(unittest.IsolatedAsyncioTestCase):
    def build_store(self, redis):
        from app.ai.rag.vector_store import RedisNewsVectorStore

        return RedisNewsVectorStore(
            redis_client=redis,
            index_alias="idx:ai:news:chunk:active",
            index_prefix="idx:ai:news:chunk:v2",
            key_prefix="ai:news:chunk:v2",
            vector_dimensions=2,
        )

    async def test_build_schema_and_hash_preserve_chunk_traceability(self):
        """Dropping chunk metadata would make citations impossible to trace."""
        redis = BuildAwareRedisStack()
        store = self.build_store(redis)

        await store.prepare_build("build-1")
        await store.write_documents("build-1", [chunk_document()])

        create = next(command for command in redis.commands if command[0] == "FT.CREATE")
        self.assertIn("HNSW", create)
        self.assertIn("COSINE", create)
        self.assertIn("chunk_id", create)
        self.assertIn("chunk_text", create)
        key = "ai:news:chunk:v2:build-1:7:0"
        self.assertIn(key, redis.hashes)
        self.assertEqual(redis.hashes[key]["chunk_id"], "7:0:abcdef")
        self.assertEqual(redis.hashes[key]["chunk_text"], "第 0 个真正命中的正文片段")

    async def test_candidate_activation_is_atomic_and_failed_build_cleanup_is_exact(self):
        """A failed candidate must not replace the active index or clear unrelated Redis data."""
        redis = BuildAwareRedisStack()
        store = self.build_store(redis)
        await store.prepare_build("good")
        await store.write_documents("good", [chunk_document()])
        await store.validate_build(
            "good",
            expected_documents=1,
            probe_embedding=[0.1, 0.2],
        )
        probe = [
            command for command in redis.commands
            if command[0] == "FT.SEARCH" and "KNN" in str(command)
        ]
        self.assertEqual(len(probe), 1)
        self.assertIn("NOCONTENT", probe[0])
        await store.activate_build("good")

        active_before = redis.aliases["idx:ai:news:chunk:active"]
        await store.prepare_build("failed")
        await store.write_documents("failed", [chunk_document(news_id=8)])
        await store.discard_build("failed")

        self.assertEqual(redis.aliases["idx:ai:news:chunk:active"], active_before)
        self.assertIn("ai:news:chunk:v2:good:7:0", redis.hashes)
        self.assertNotIn("ai:news:chunk:v2:failed:8:0", redis.hashes)
        self.assertIn("news:list:v2:1:g1:p1:s10", redis.hashes)
        self.assertIn("ai:summary:v1:9:hash", redis.hashes)
        self.assertIn("checkpoint:session-a", redis.hashes)

        with self.assertRaises(ValueError):
            await store.discard_build("good")

    async def test_search_returns_chunk_hits_and_filters_low_similarity(self):
        """Parsing an article head instead of the matched chunk would recreate the old RAG bug."""
        redis = BuildAwareRedisStack()
        store = self.build_store(redis)
        redis.indexes["idx:ai:news:chunk:v2:good"] = "ai:news:chunk:v2:good:"
        redis.aliases["idx:ai:news:chunk:active"] = "idx:ai:news:chunk:v2:good"
        redis.search_response = [
            2,
            b"ai:news:chunk:v2:good:7:3",
            [
                b"news_id", b"7", b"chunk_id", b"7:3:abc", b"chunk_index", b"3",
                b"start_index", b"300", b"end_index", b"340",
                b"title", "AI 芯片".encode(), b"description", "技术新闻".encode(),
                b"chunk_text", "真正命中的后部事实".encode(), b"content_hash", b"abc",
                b"category_id", b"2", b"publish_time", b"2026-09-01T08:00:00",
                b"views", b"12", b"vector_distance", b"0.125",
            ],
            b"ai:news:chunk:v2:good:8:0",
            [
                b"news_id", b"8", b"chunk_id", b"8:0:def", b"chunk_index", b"0",
                b"start_index", b"0", b"end_index", b"10",
                b"title", "无关内容".encode(), b"description", b"",
                b"chunk_text", "低分片段".encode(), b"content_hash", b"def",
                b"category_id", b"3", b"publish_time", b"2026-09-01T09:00:00",
                b"views", b"1", b"vector_distance", b"0.8",
            ],
        ]

        hits = await store.search([0.1, 0.2], limit=20, minimum_score=0.35)

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].chunk_id, "7:3:abc")
        self.assertEqual(hits[0].chunk_text, "真正命中的后部事实")
        self.assertEqual(hits[0].score, 0.875)

    async def test_invalid_embedding_is_rejected_before_any_redis_write(self):
        """A wrong vector dimension must not leave a partially written candidate."""
        redis = BuildAwareRedisStack()
        store = self.build_store(redis)
        await store.prepare_build("build-1")

        with self.assertRaises(ValueError):
            await store.write_documents("build-1", [chunk_document(embedding=[0.1])])

        self.assertNotIn("ai:news:chunk:v2:build-1:7:0", redis.hashes)


if __name__ == "__main__":
    unittest.main()
