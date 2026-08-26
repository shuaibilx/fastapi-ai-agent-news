"""Keyword retrieval over the news table for RAG question answering."""

from dataclasses import dataclass
from typing import Protocol


class NewsRecord(Protocol):
    id: int
    title: str
    description: str | None
    content: str | None
    views: int


@dataclass(frozen=True)
class RetrievedArticle:
    id: int
    title: str
    description: str | None
    content: str | None
    views: int
    excerpt: str | None
    match_count: int


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
    """Rank news records by keyword match count and keep results bounded."""

    def __init__(self, search_port: NewsSearchPort, default_limit: int = 5):
        self._search_port = search_port
        self._default_limit = default_limit

    async def search(self, question: str, limit: int | None = None) -> list[RetrievedArticle]:
        limit = limit or self._default_limit
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
                ))
        ranked.sort(key=lambda item: (item.match_count, item.views), reverse=True)
        return ranked[:limit]

