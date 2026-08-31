"""Orchestration for retrieval-augmented news question answering."""

from dataclasses import dataclass
from collections.abc import AsyncIterator

from app.ai.rag.gateway import QaGateway, QaProviderUnavailable
from app.ai.rag.retrieval import NewsRetrievalService
from app.ai.streaming import StreamEvent


@dataclass(frozen=True)
class QaCitation:
    news_id: int
    title: str
    excerpt: str | None


@dataclass(frozen=True)
class NewsQaResult:
    answer: str
    citations: list[QaCitation]


class QaService:
    """Retrieve first, then answer only from the retrieved news context."""

    def __init__(self, *, retrieval: NewsRetrievalService, gateway: QaGateway):
        self._retrieval = retrieval
        self._gateway = gateway

    async def ask(self, question: str) -> NewsQaResult:
        if not question or not question.strip():
            raise ValueError("问题不能为空")
        question = question.strip()
        articles = await self._retrieval.search(question)
        if not articles:
            return NewsQaResult(
                answer="无法回答：没有找到相关的新闻资料。",
                citations=[],
            )

        citations = [
            QaCitation(news_id=article.id, title=article.title, excerpt=article.excerpt)
            for article in articles
        ]
        context = "\n\n".join(
            f"[{article.id}] {article.title}\n{article.excerpt or ''}"
            for article in articles
        )
        answer = await self._gateway.answer(question, context)
        return NewsQaResult(answer=answer, citations=citations)

    async def stream(self, question: str) -> AsyncIterator[StreamEvent]:
        if not question or not question.strip():
            raise ValueError("问题不能为空")
        question = question.strip()
        yield StreamEvent.meta({"mode": "qa"})
        articles = await self._retrieval.search(question)
        if not articles:
            yield StreamEvent.delta("无法回答：没有找到相关的新闻资料。")
            yield StreamEvent.done({"citations": []})
            return

        citations = [
            QaCitation(news_id=article.id, title=article.title, excerpt=article.excerpt)
            for article in articles
        ]
        public_citations = [
            {"newsId": citation.news_id, "title": citation.title, "excerpt": citation.excerpt}
            for citation in citations
        ]
        for citation in public_citations:
            yield StreamEvent.citation(citation)
        context = "\n\n".join(
            f"[{article.id}] {article.title}\n{article.excerpt or ''}"
            for article in articles
        )
        emitted = False
        async for token in self._gateway.stream_answer(question, context):
            if token:
                emitted = True
                yield StreamEvent.delta(token)
        if not emitted:
            raise QaProviderUnavailable("模型返回了空回答")
        yield StreamEvent.done({"citations": public_citations})
