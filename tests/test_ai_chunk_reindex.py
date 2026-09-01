from datetime import datetime
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.ai.rag.chunking import NewsChunk


def make_chunk(news_id: int, chunk_index: int) -> NewsChunk:
    text = f"新闻 {news_id} 的第 {chunk_index} 个片段"
    return NewsChunk(
        news_id=news_id,
        chunk_id=f"{news_id}:{chunk_index}:hash",
        chunk_index=chunk_index,
        start_index=chunk_index * 20,
        end_index=chunk_index * 20 + len(text),
        chunk_text=text,
        embedding_text=f"标题：新闻 {news_id}\n正文片段：{text}",
        content_hash="hash",
        title=f"新闻 {news_id}",
        description="简介",
    )


class FakeNewsSource:
    def __init__(self, rows):
        self.rows = rows

    async def list_news(self, offset, limit):
        return self.rows[offset: offset + limit]


class TwoChunkSplitter:
    def split(self, *, news_id, title, description, content):
        return [make_chunk(news_id, 0), make_chunk(news_id, 1)]


class BatchEmbeddingService:
    def __init__(self, *, wrong_size=False, error=None):
        self.batches = []
        self.wrong_size = wrong_size
        self.error = error

    async def embed(self, texts):
        if self.error:
            raise self.error
        self.batches.append(list(texts))
        vectors = [[float(index + 1), 0.5] for index in range(len(texts))]
        return vectors[:-1] if self.wrong_size else vectors


class StagedVectorStore:
    def __init__(self):
        self.active = "idx:old"
        self.candidates = {}
        self.validated = []

    async def prepare_build(self, build_id):
        self.candidates[build_id] = []
        return f"idx:v2:{build_id}"

    async def write_documents(self, build_id, documents):
        self.candidates[build_id].extend(documents)
        return len(documents)

    async def validate_build(self, build_id, *, expected_documents, probe_embedding=None):
        if len(self.candidates[build_id]) != expected_documents:
            raise RuntimeError("incomplete")
        self.validated.append((build_id, expected_documents, probe_embedding))

    async def activate_build(self, build_id):
        self.active = f"idx:v2:{build_id}"
        return self.active

    async def discard_build(self, build_id):
        if self.active == f"idx:v2:{build_id}":
            raise ValueError("active")
        self.candidates.pop(build_id, None)


def news(news_id):
    return SimpleNamespace(
        id=news_id,
        title=f"新闻 {news_id}",
        description="简介",
        content="很长的正文",
        category_id=2,
        publish_time=datetime(2026, 9, 1, 8, 0, 0),
        views=5,
    )


class ChunkIndexRebuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_runner_disposes_engine_before_event_loop_closes(self):
        from app.ai.rag.reindex import NewsIndexRebuildResult, run_rebuild_command

        class Engine:
            def __init__(self):
                self.disposed = False

            async def dispose(self):
                self.disposed = True

        engine = Engine()
        expected = NewsIndexRebuildResult(
            build_id="build-1",
            index_name="idx:v2:build-1",
            scanned_news=2,
            generated_chunks=4,
            indexed_chunks=4,
        )
        with (
            patch("app.ai.rag.reindex.rebuild_news_index", new=AsyncMock(return_value=expected)),
            patch("app.ai.rag.reindex.async_engine", engine),
        ):
            result = await run_rebuild_command()

        self.assertEqual(result, expected)
        self.assertTrue(engine.disposed)

    async def test_rebuild_batches_chunks_and_activates_only_after_validation(self):
        """Embedding per article would miss extra chunks and activate an incomplete index."""
        from app.ai.rag.reindex import NewsIndexRebuilder

        embeddings = BatchEmbeddingService()
        store = StagedVectorStore()
        rebuilder = NewsIndexRebuilder(
            source=FakeNewsSource([news(7), news(8)]),
            embedding_service=embeddings,
            vector_store=store,
            chunker=TwoChunkSplitter(),
            batch_size=3,
            build_id_factory=lambda: "build-1",
        )

        result = await rebuilder.rebuild()

        self.assertEqual(result.scanned_news, 2)
        self.assertEqual(result.generated_chunks, 4)
        self.assertEqual(result.indexed_chunks, 4)
        self.assertEqual(result.build_id, "build-1")
        self.assertEqual([len(batch) for batch in embeddings.batches], [3, 1])
        self.assertEqual(store.validated, [("build-1", 4, [1.0, 0.5])])
        self.assertEqual(store.active, "idx:v2:build-1")
        self.assertEqual(
            [item.chunk_id for item in store.candidates["build-1"]],
            ["7:0:hash", "7:1:hash", "8:0:hash", "8:1:hash"],
        )

    async def test_failed_embedding_mapping_discards_candidate_without_changing_active(self):
        """A malformed TEI batch must not expose a partial build."""
        from app.ai.rag.reindex import NewsIndexRebuilder, NewsIndexRebuildUnavailable

        store = StagedVectorStore()
        rebuilder = NewsIndexRebuilder(
            source=FakeNewsSource([news(7)]),
            embedding_service=BatchEmbeddingService(wrong_size=True),
            vector_store=store,
            chunker=TwoChunkSplitter(),
            batch_size=2,
            build_id_factory=lambda: "failed",
        )

        with self.assertRaises(NewsIndexRebuildUnavailable):
            await rebuilder.rebuild()

        self.assertEqual(store.active, "idx:old")
        self.assertNotIn("failed", store.candidates)


class ChunkIndexCliTests(unittest.TestCase):
    def test_cli_reports_build_statistics_and_success_exit_code(self):
        """A successful command must expose the build needed for rollback."""
        from app.ai.rag.reindex import NewsIndexRebuildResult, run_cli

        async def rebuild():
            return NewsIndexRebuildResult(
                build_id="build-1",
                index_name="idx:v2:build-1",
                scanned_news=2,
                generated_chunks=4,
                indexed_chunks=4,
            )

        stdout, stderr = StringIO(), StringIO()
        code = run_cli(rebuild=rebuild, stdout=stdout, stderr=stderr)

        self.assertEqual(code, 0)
        self.assertIn("build-1", stdout.getvalue())
        self.assertIn("4 个 Chunk", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_failure_is_nonzero_and_does_not_claim_activation(self):
        """A failed rebuild must never print the success wording consumed by operators."""
        from app.ai.rag.reindex import run_cli

        async def rebuild():
            raise RuntimeError("TEI offline")

        stdout, stderr = StringIO(), StringIO()
        code = run_cli(rebuild=rebuild, stdout=stdout, stderr=stderr)

        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("活动索引保持不变", stderr.getvalue())
        self.assertNotIn("构建完成", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
