"""Run a reproducible BGE Chunk-parameter evaluation without mutating Redis."""

import argparse
import asyncio
from dataclasses import dataclass
import json
from math import sqrt
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

from app.ai.embeddings import TeiEmbeddingClient
from app.ai.rag.chunking import BgeTokenCounter, NewsChunker
from app.ai.rag.context import RetrievalContextBuilder
from app.ai.rag.evaluation import (
    EvaluationQueryResult,
    RetrievalEvaluationSample,
    evaluate_results,
)
from app.ai.rag.retrieval import aggregate_chunk_hits
from app.ai.rag.vector_store import VectorSearchHit
from app.core.config import get_settings


_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


@dataclass(frozen=True)
class IndexedChunk:
    chunk: object
    article: object
    embedding: list[float]


class EmbeddingService(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


async def embed_in_batches(
    embedding_service: EmbeddingService,
    texts: list[str],
    *,
    batch_size: int,
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(await embedding_service.embed(texts[start:start + batch_size]))
    return vectors


async def run_grid(
    fixture_path: Path,
    *,
    chunk_sizes: list[int],
    overlaps: list[int],
    thresholds: list[float],
) -> list[dict]:
    settings = get_settings()
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    articles = [SimpleNamespace(**item) for item in fixture["articles"]]
    samples = [
        RetrievalEvaluationSample(
            sample_id=item["id"],
            question=item["question"],
            relevant_news_ids=tuple(item["relevant_news_ids"]),
        )
        for item in fixture["samples"]
    ]
    embedding_service = TeiEmbeddingClient(
        base_url=settings.embedding_base_url,
        timeout_seconds=settings.embedding_timeout_seconds,
        vector_dimensions=settings.ai_semantic_vector_dimensions,
    )
    tokens = BgeTokenCounter(settings.embedding_tokenizer_path)
    query_embeddings = await embed_in_batches(
        embedding_service,
        [f"{_QUERY_INSTRUCTION}{sample.question}" for sample in samples],
        batch_size=settings.ai_semantic_batch_size,
    )
    output: list[dict] = []
    for chunk_size in chunk_sizes:
        for overlap in overlaps:
            if overlap >= chunk_size:
                continue
            chunker = NewsChunker(
                token_counter=tokens,
                chunk_size_tokens=chunk_size,
                chunk_overlap_tokens=overlap,
                embedding_input_max_tokens=settings.ai_semantic_embedding_input_max_tokens,
            )
            chunk_pairs = [
                (chunk, article)
                for article in articles
                for chunk in chunker.split(
                    news_id=article.id,
                    title=article.title,
                    description=article.description,
                    content=article.content,
                )
            ]
            vectors = await embed_in_batches(
                embedding_service,
                [chunk.embedding_text for chunk, _ in chunk_pairs],
                batch_size=settings.ai_semantic_batch_size,
            )
            indexed = [
                IndexedChunk(chunk, article, vector)
                for (chunk, article), vector in zip(chunk_pairs, vectors, strict=True)
            ]
            for threshold in thresholds:
                results = [
                    _evaluate_query(
                        sample,
                        query_embedding,
                        indexed,
                        threshold=threshold,
                        token_counter=tokens,
                        candidate_limit=settings.ai_semantic_candidate_chunk_limit,
                        final_limit=settings.ai_qa_retrieval_limit,
                        max_chunks_per_news=settings.ai_semantic_max_chunks_per_news,
                        context_tokens=settings.ai_qa_max_context_tokens,
                    )
                    for sample, query_embedding in zip(samples, query_embeddings, strict=True)
                ]
                metrics = evaluate_results(samples, results)
                output.append({
                    "chunk_size": chunk_size,
                    "overlap": overlap,
                    "minimum_score": threshold,
                    "chunk_count": len(indexed),
                    **metrics.as_dict(),
                })
    return output


def _evaluate_query(
    sample: RetrievalEvaluationSample,
    query_embedding: list[float],
    indexed: list[IndexedChunk],
    *,
    threshold: float,
    token_counter: BgeTokenCounter,
    candidate_limit: int,
    final_limit: int,
    max_chunks_per_news: int,
    context_tokens: int,
) -> EvaluationQueryResult:
    scored = sorted(
        (
            (_cosine(query_embedding, item.embedding), item)
            for item in indexed
        ),
        key=lambda pair: (-pair[0], pair[1].chunk.chunk_id),
    )[:candidate_limit]
    hits = [
        _to_hit(score, item)
        for score, item in scored
        if score >= threshold
    ]
    articles = aggregate_chunk_hits(
        hits,
        limit=final_limit,
        max_chunks_per_news=max_chunks_per_news,
    )
    context = RetrievalContextBuilder(
        token_counter=token_counter,
        max_tokens=context_tokens,
    ).build(articles)
    return EvaluationQueryResult(
        sample_id=sample.sample_id,
        candidate_news_ids=tuple(hit.news_id for hit in hits),
        articles=context.articles,
    )


def _to_hit(score: float, item: IndexedChunk) -> VectorSearchHit:
    chunk, article = item.chunk, item.article
    return VectorSearchHit(
        news_id=article.id,
        chunk_id=chunk.chunk_id,
        chunk_index=chunk.chunk_index,
        start_index=chunk.start_index,
        end_index=chunk.end_index,
        title=chunk.title,
        description=chunk.description,
        chunk_text=chunk.chunk_text,
        content_hash=chunk.content_hash,
        category_id=article.category_id,
        publish_time=article.publish_time,
        views=article.views,
        score=score,
    )


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = sqrt(sum(value * value for value in left)) * sqrt(
        sum(value * value for value in right)
    )
    return numerator / denominator if denominator else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="评测新闻 Chunk 参数")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/news_chunk_eval.json"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--chunk-sizes", default="256,320,384")
    parser.add_argument("--overlaps", default="32,48,64")
    parser.add_argument("--thresholds", default="0.25,0.35,0.45")
    args = parser.parse_args()
    rows = asyncio.run(run_grid(
        args.fixture,
        chunk_sizes=[int(value) for value in args.chunk_sizes.split(",")],
        overlaps=[int(value) for value in args.overlaps.split(",")],
        thresholds=[float(value) for value in args.thresholds.split(",")],
    ))
    payload = json.dumps(rows, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
