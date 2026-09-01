import unittest

from app.ai.rag.retrieval import RetrievedArticle, RetrievedPassage
from app.ai.rag.vector_store import VectorSearchHit


def hit(news_id, chunk_index, score, text, *, start=0):
    return VectorSearchHit(
        news_id=news_id,
        chunk_id=f"{news_id}:{chunk_index}:hash",
        chunk_index=chunk_index,
        start_index=start,
        end_index=start + len(text),
        title=f"新闻 {news_id}",
        description=f"简介 {news_id}",
        chunk_text=text,
        content_hash="hash",
        category_id=1,
        publish_time="2026-09-01T08:00:00",
        views=10,
        score=score,
    )


class Embeddings:
    async def embed(self, texts):
        return [[0.1, 0.2]]


class VectorStore:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    async def search(self, embedding, *, limit, minimum_score):
        self.calls.append((embedding, limit, minimum_score))
        return self.hits


class ChunkRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_limit_is_independent_and_hits_are_grouped_by_news(self):
        """One article's chunks must not consume every final article slot."""
        from app.ai.rag.retrieval import RedisSemanticNewsSearch

        store = VectorStore([
            hit(1, 3, 0.98, "A3", start=30),
            hit(1, 1, 0.96, "A1", start=10),
            hit(1, 2, 0.95, "A2", start=20),
            hit(2, 0, 0.90, "B0"),
            hit(3, 0, 0.80, "C0"),
        ])
        search = RedisSemanticNewsSearch(
            embedding_service=Embeddings(),
            vector_store=store,
            minimum_score=0.35,
            candidate_chunk_limit=20,
            max_chunks_per_news=2,
        )

        rows = await search.search("问题", limit=3)

        self.assertEqual(store.calls[0][1], 20)
        self.assertEqual([row.id for row in rows], [1, 2, 3])
        self.assertEqual([p.chunk_index for p in rows[0].passages], [1, 3])
        self.assertEqual(len(rows[0].passages), 2)
        self.assertEqual(rows[0].excerpt, "A3")

    async def test_excerpt_is_the_highest_scoring_hit_not_the_article_head(self):
        from app.ai.rag.retrieval import RedisSemanticNewsSearch

        search = RedisSemanticNewsSearch(
            embedding_service=Embeddings(),
            vector_store=VectorStore([
                hit(7, 4, 0.92, "正文后部的关键事实", start=400),
            ]),
            minimum_score=0.35,
            candidate_chunk_limit=20,
            max_chunks_per_news=2,
        )

        rows = await search.search("关键事实", limit=5)

        self.assertEqual(rows[0].excerpt, "正文后部的关键事实")
        self.assertEqual(rows[0].passages[0].start_index, 400)


class CharacterTokenCounter:
    def count(self, text):
        return len(text)


class RetrievalContextTests(unittest.TestCase):
    def test_context_removes_adjacent_overlap_and_keeps_source_offsets(self):
        from app.ai.rag.context import RetrievalContextBuilder

        article = RetrievedArticle(
            id=7,
            title="T",
            description=None,
            content=None,
            views=1,
            excerpt="abcdefghij",
            match_count=0,
            passages=(
                RetrievedPassage("7:0", 0, 0, 10, "abcdefghij", 0.9),
                RetrievedPassage("7:1", 1, 8, 18, "ijklmnopqr", 0.8),
            ),
        )
        result = RetrievalContextBuilder(
            token_counter=CharacterTokenCounter(),
            max_tokens=200,
        ).build([article])

        self.assertEqual([p.text for p in result.articles[0].passages], ["abcdefghij", "klmnopqr"])
        self.assertEqual(result.articles[0].passages[1].start_index, 10)
        self.assertEqual(result.context.count("ij"), 1)

    def test_context_never_splits_a_passage_to_fit_the_token_budget(self):
        from app.ai.rag.context import RetrievalContextBuilder

        article = RetrievedArticle(
            id=8,
            title="T",
            description=None,
            content=None,
            views=1,
            excerpt="short",
            match_count=0,
            passages=(
                RetrievedPassage("8:0", 0, 0, 5, "short", 0.9),
                RetrievedPassage("8:1", 1, 5, 105, "x" * 100, 0.8),
            ),
        )
        builder = RetrievalContextBuilder(
            token_counter=CharacterTokenCounter(),
            max_tokens=35,
        )

        result = builder.build([article])

        self.assertIn("short", result.context)
        self.assertNotIn("x", result.context)
        self.assertLessEqual(result.token_count, 35)
        self.assertEqual(len(result.articles[0].passages), 1)


if __name__ == "__main__":
    unittest.main()
