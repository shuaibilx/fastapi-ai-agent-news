"""Semantic-first news retrieval with a keyword fallback."""

from dataclasses import dataclass
from typing import Protocol

from app.ai.embeddings import EmbeddingProviderUnavailable
from app.ai.rag.vector_store import (
    NewsVectorStoreUnavailable,
    RedisNewsVectorStore,
    VectorSearchHit,
)


class NewsRecord(Protocol):
    id: int
    title: str
    description: str | None
    content: str | None
    views: int


@dataclass(frozen=True)
class RetrievedPassage:
    chunk_id: str
    chunk_index: int
    start_index: int
    end_index: int
    text: str
    score: float


@dataclass(frozen=True)
class RetrievedArticle:
    id: int
    title: str
    description: str | None
    content: str | None
    views: int
    excerpt: str | None
    match_count: int
    passages: tuple[RetrievedPassage, ...] = ()


class SemanticSearchUnavailable(RuntimeError):
    """Semantic retrieval cannot be used for this request."""


class SemanticNewsSearchPort(Protocol):
    async def search(self, question: str, limit: int) -> list[RetrievedArticle]: ...


class EmbeddingSearchPort(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class RedisSemanticNewsSearch:
    """Translate a question into a Redis vector search result."""

    _QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

    def __init__(
        self,
        *,
        embedding_service: EmbeddingSearchPort,
        vector_store: RedisNewsVectorStore,
        minimum_score: float,
        candidate_chunk_limit: int = 20,
        max_chunks_per_news: int = 2,
    ):
        self._embedding_service = embedding_service
        self._vector_store = vector_store
        self._minimum_score = minimum_score
        self._candidate_chunk_limit = candidate_chunk_limit
        self._max_chunks_per_news = max_chunks_per_news

    async def search(self, question: str, limit: int) -> list[RetrievedArticle]:
        clean_question = question.strip()
        if not clean_question:
            return []
        try:
            vectors = await self._embedding_service.embed([
                f"{self._QUERY_INSTRUCTION}{clean_question}",
            ])
            if len(vectors) != 1:
                raise SemanticSearchUnavailable("Embedding 结果无效")
            hits = await self._vector_store.search(
                vectors[0],
                limit=self._candidate_chunk_limit,
                minimum_score=self._minimum_score,
            )
        except (EmbeddingProviderUnavailable, NewsVectorStoreUnavailable) as exc:
            raise SemanticSearchUnavailable("语义检索暂时不可用") from exc

        return aggregate_chunk_hits(
            hits,
            limit=limit,
            max_chunks_per_news=self._max_chunks_per_news,
        )


def aggregate_chunk_hits(
    hits: list[VectorSearchHit],
    *,
    limit: int,
    max_chunks_per_news: int,
) -> list[RetrievedArticle]:
    grouped: dict[int, list[VectorSearchHit]] = {}
    for hit in hits:
        grouped.setdefault(hit.news_id, []).append(hit)

    ranked_groups = sorted(
        grouped.values(),
        key=lambda group: (-max(hit.score for hit in group), group[0].news_id),
    )
    articles: list[RetrievedArticle] = []
    for group in ranked_groups[:limit]:
        best_hits = sorted(
            group,
            key=lambda hit: (-hit.score, hit.chunk_index, hit.chunk_id),
        )[:max_chunks_per_news]
        highest = best_hits[0]
        ordered_hits = sorted(
            best_hits,
            key=lambda hit: (hit.chunk_index, hit.start_index, hit.chunk_id),
        )
        excerpt = highest.chunk_text[:240]
        if len(highest.chunk_text) > 240:
            excerpt += "…"
        passages = tuple(
            RetrievedPassage(
                chunk_id=hit.chunk_id,
                chunk_index=hit.chunk_index,
                start_index=hit.start_index,
                end_index=hit.end_index,
                text=hit.chunk_text,
                score=hit.score,
            )
            for hit in ordered_hits
        )
        articles.append(RetrievedArticle(
            id=highest.news_id,
            title=highest.title,
            description=highest.description,
            content="\n".join(passage.text for passage in passages),
            views=highest.views,
            excerpt=excerpt,
            match_count=0,
            passages=passages,
        ))
    return articles


class NewsSearchPort(Protocol):
    async def search_news(self, question: str, limit: int) -> list[NewsRecord]: ...


def tokenize(question: str) -> list[str]:
    """Return a small set of non-empty keyword tokens for matching."""
    return [
        part.strip().lower()
        for part in question.replace("?", " ").replace("？", " ").replace("，", " ").replace(",", " ").split()
        if part.strip()
    ]


def extract_match_excerpt(article_text: str | None, keyword: str, width: int = 40) -> str | None:
    """Return a deterministic window around the first keyword match."""
    if not article_text:
        return None
    lowered = article_text.lower()
    index = lowered.find(keyword.lower())
    if index < 0:
        return article_text[:width] if len(article_text) <= width else article_text[:width] + "…"
    start = max(0, index - width // 2)
    end = min(len(article_text), index + len(keyword) + width // 2)
    excerpt = article_text[start:end]
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(article_text):
        excerpt = excerpt + "…"
    return excerpt


class NewsRetrievalService:
    """Use semantic results when available and retain a reliable keyword fallback."""

    def __init__(
        self,
        search_port: NewsSearchPort,
        default_limit: int = 5,
        semantic_search: SemanticNewsSearchPort | None = None,
    ):
        self._search_port = search_port
        self._default_limit = default_limit
        self._semantic_search = semantic_search

    async def search(self, question: str, limit: int | None = None) -> list[RetrievedArticle]:
        limit = limit or self._default_limit
        if self._semantic_search is not None:
            try:
                return await self._semantic_search.search(question, limit)
            except SemanticSearchUnavailable:
                pass
        return await self._search_keywords(question, limit)

    async def _search_keywords(self, question: str, limit: int) -> list[RetrievedArticle]:
        records = await self._search_port.search_news(question, limit)
        keywords = tokenize(question)
        ranked: list[RetrievedArticle] = []
        for record in records:
            combined = " ".join(filter(None, [record.title, record.description, record.content]))
            match_count = sum(combined.lower().count(kw) for kw in keywords)
            excerpt_keyword = next((kw for kw in keywords if kw and kw in combined.lower()), None)
            excerpt = extract_match_excerpt(combined, excerpt_keyword) if excerpt_keyword else (
                (record.content or record.description or record.title or "")[:80]
            )
            if match_count > 0 or excerpt_keyword:
                ranked.append(RetrievedArticle(
                    id=record.id,
                    title=record.title,
                    description=record.description,
                    content=record.content,
                    views=record.views,
                    excerpt=excerpt,
                    match_count=match_count,
                    passages=(RetrievedPassage(
                        chunk_id=f"keyword:{record.id}",
                        chunk_index=0,
                        start_index=0,
                        end_index=len(excerpt or ""),
                        text=excerpt or "",
                        score=0.0,
                    ),) if excerpt else (),
                ))
        ranked.sort(key=lambda item: (item.match_count, item.views), reverse=True)
        return ranked[:limit]

