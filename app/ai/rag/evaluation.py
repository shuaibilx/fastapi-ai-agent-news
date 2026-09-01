"""Deterministic metrics for labeled news Chunk retrieval evaluations."""

from dataclasses import dataclass

from app.ai.rag.retrieval import RetrievedArticle


@dataclass(frozen=True)
class RetrievalEvaluationSample:
    sample_id: str
    question: str
    relevant_news_ids: tuple[int, ...]


@dataclass(frozen=True)
class EvaluationQueryResult:
    sample_id: str
    candidate_news_ids: tuple[int, ...]
    articles: tuple[RetrievedArticle, ...]


@dataclass(frozen=True)
class RetrievalMetrics:
    recall_at_20: float
    mrr: float
    hit_rate_at_5: float
    context_precision: float
    citation_correctness: float
    irrelevant_rejection_rate: float

    def as_dict(self) -> dict[str, float]:
        return {
            "Recall@20": self.recall_at_20,
            "MRR": self.mrr,
            "HitRate@5": self.hit_rate_at_5,
            "context_precision": self.context_precision,
            "citation_correctness": self.citation_correctness,
            "irrelevant_rejection_rate": self.irrelevant_rejection_rate,
        }


def evaluate_results(
    samples: list[RetrievalEvaluationSample],
    results: list[EvaluationQueryResult],
) -> RetrievalMetrics:
    if len({result.sample_id for result in results}) != len(results):
        raise ValueError("每个评测样本只能有一份结果")
    by_id = {result.sample_id: result for result in results}
    if set(by_id) != {sample.sample_id for sample in samples}:
        raise ValueError("评测结果必须与标注样本一一对应")

    relevant_samples = [sample for sample in samples if sample.relevant_news_ids]
    if not relevant_samples:
        raise ValueError("至少需要一个包含相关新闻的样本")

    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    hit_rates: list[float] = []
    context_precisions: list[float] = []
    citation_scores: list[float] = []
    for sample in relevant_samples:
        result = by_id[sample.sample_id]
        relevant = set(sample.relevant_news_ids)
        candidate_ids = result.candidate_news_ids[:20]
        recalls.append(len(relevant.intersection(candidate_ids)) / len(relevant))
        first_rank = next(
            (rank for rank, news_id in enumerate(candidate_ids, start=1) if news_id in relevant),
            None,
        )
        reciprocal_ranks.append(1.0 / first_rank if first_rank else 0.0)
        hit_rates.append(float(any(article.id in relevant for article in result.articles[:5])))

        passages = [
            (article.id, passage)
            for article in result.articles
            for passage in article.passages
        ]
        context_precisions.append(
            sum(news_id in relevant for news_id, _ in passages) / len(passages)
            if passages else 0.0
        )
        citation_scores.append(
            sum(
                article.id in relevant
                and bool(article.excerpt)
                and any(article.excerpt.rstrip("…") in passage.text for passage in article.passages)
                for article in result.articles
            ) / len(result.articles)
            if result.articles else 0.0
        )

    irrelevant_samples = [sample for sample in samples if not sample.relevant_news_ids]
    rejection_scores = [
        float(not by_id[sample.sample_id].articles)
        for sample in irrelevant_samples
    ]
    return RetrievalMetrics(
        recall_at_20=_mean(recalls),
        mrr=_mean(reciprocal_ranks),
        hit_rate_at_5=_mean(hit_rates),
        context_precision=_mean(context_precisions),
        citation_correctness=_mean(citation_scores),
        irrelevant_rejection_rate=_mean(rejection_scores) if rejection_scores else 1.0,
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)
