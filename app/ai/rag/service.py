"""Orchestration for retrieval-augmented news question answering."""

from dataclasses import dataclass

from app.ai.rag.gateway import QaGateway, QaProviderUnavailable
from app.ai.rag.retrieval import NewsRetrievalService


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
