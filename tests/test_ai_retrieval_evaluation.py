import unittest
import json
from pathlib import Path

from app.ai.rag.retrieval import RetrievedArticle, RetrievedPassage


def article(news_id, excerpt, *, relevant_passage=True):
    text = excerpt if relevant_passage else "无关片段"
    return RetrievedArticle(
        id=news_id,
        title=f"新闻 {news_id}",
        description=None,
        content=text,
        views=1,
        excerpt=excerpt,
        match_count=0,
        passages=(RetrievedPassage(
            f"{news_id}:0", 0, 0, len(text), text, 0.9,
        ),),
    )


class RetrievalEvaluationTests(unittest.TestCase):
    def test_fixture_covers_required_failure_modes_and_places_tail_fact_after_512_tokens(self):
        from app.ai.rag.chunking import BgeTokenCounter

        fixture = json.loads(
            Path("tests/fixtures/news_chunk_eval.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {item["id"] for item in fixture["samples"]},
            {"tail_fact", "boundary_fact", "multi_passage", "similar_topics", "irrelevant"},
        )
        article = next(item for item in fixture["articles"] if item["id"] == 101)
        prefix = article["content"].split("报告在正文后部确认", 1)[0]
        tokens = BgeTokenCounter("app/embedding/bge-large-zh-v1.5/tokenizer.json")
        self.assertGreater(tokens.count(prefix), 512)

    def test_metrics_cover_candidate_ranking_final_hits_context_and_citations(self):
        from app.ai.rag.evaluation import (
            EvaluationQueryResult,
            RetrievalEvaluationSample,
            evaluate_results,
        )

        samples = [
            RetrievalEvaluationSample(
                sample_id="tail",
                question="尾部事实",
                relevant_news_ids=(7,),
            ),
            RetrievalEvaluationSample(
                sample_id="multi",
                question="近似主题",
                relevant_news_ids=(8, 9),
            ),
        ]
        results = [
            EvaluationQueryResult(
                sample_id="tail",
                candidate_news_ids=(1, 7, 7),
                articles=(article(7, "尾部事实"),),
            ),
            EvaluationQueryResult(
                sample_id="multi",
                candidate_news_ids=(8, 3, 9),
                articles=(article(8, "近似主题"), article(3, "错误引用")),
            ),
        ]

        metrics = evaluate_results(samples, results)

        self.assertEqual(metrics.recall_at_20, 1.0)
        self.assertEqual(metrics.mrr, 0.75)
        self.assertEqual(metrics.hit_rate_at_5, 1.0)
        self.assertEqual(metrics.context_precision, 0.75)
        self.assertEqual(metrics.citation_correctness, 0.75)

    def test_unrelated_questions_contribute_to_rejection_accuracy(self):
        from app.ai.rag.evaluation import (
            EvaluationQueryResult,
            RetrievalEvaluationSample,
            evaluate_results,
        )

        samples = [
            RetrievalEvaluationSample("related", "q", (1,)),
            RetrievalEvaluationSample("irrelevant", "food", ()),
        ]
        results = [
            EvaluationQueryResult("related", (1,), (article(1, "q"),)),
            EvaluationQueryResult("irrelevant", (), ()),
        ]

        self.assertEqual(evaluate_results(samples, results).irrelevant_rejection_rate, 1.0)

    def test_missing_or_duplicate_results_are_rejected(self):
        from app.ai.rag.evaluation import (
            EvaluationQueryResult,
            RetrievalEvaluationSample,
            evaluate_results,
        )

        samples = [RetrievalEvaluationSample("one", "q", (1,))]
        with self.assertRaises(ValueError):
            evaluate_results(samples, [])
        with self.assertRaises(ValueError):
            evaluate_results(samples, [
                EvaluationQueryResult("one", (), ()),
                EvaluationQueryResult("one", (), ()),
            ])


class EvaluationBatchingTests(unittest.IsolatedAsyncioTestCase):
    async def test_embedding_requests_respect_the_configured_tei_batch_limit(self):
        from app.ai.rag.evaluate import embed_in_batches

        class Embeddings:
            def __init__(self):
                self.calls = []

            async def embed(self, texts):
                self.calls.append(list(texts))
                if len(texts) > 4:
                    raise RuntimeError("batch size exceeds TEI limit")
                return [[float(index)] for index, _ in enumerate(texts)]

        service = Embeddings()
        vectors = await embed_in_batches(
            service,
            [f"q{index}" for index in range(5)],
            batch_size=4,
        )

        self.assertEqual([len(call) for call in service.calls], [4, 1])
        self.assertEqual(len(vectors), 5)


if __name__ == "__main__":
    unittest.main()
