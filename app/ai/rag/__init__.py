"""Retrieval-augmented generation capability."""

from app.ai.rag.gateway import LangChainQaGateway, QaGateway, QaProviderUnavailable
from app.ai.rag.retrieval import (
    NewsRecord,
    NewsRetrievalService,
    RetrievedArticle,
    extract_match_excerpt,
    tokenize,
)
from app.ai.rag.service import NewsQaResult, QaCitation, QaService

__all__ = [
    "LangChainQaGateway",
    "NewsQaResult",
    "NewsRecord",
    "NewsRetrievalService",
    "QaCitation",
    "QaGateway",
    "QaProviderUnavailable",
    "QaService",
    "RetrievedArticle",
    "extract_match_excerpt",
    "tokenize",
]
