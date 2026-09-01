"""Retrieval-augmented generation capability."""

from app.ai.rag.gateway import LangChainQaGateway, QaGateway, QaProviderUnavailable
from app.ai.rag.retrieval import (
    NewsRecord,
    NewsRetrievalService,
    RedisSemanticNewsSearch,
    RetrievedArticle,
    RetrievedPassage,
    SemanticSearchUnavailable,
    extract_match_excerpt,
    tokenize,
)
from app.ai.rag.service import NewsQaResult, QaCitation, QaService

__all__ = [
    "LangChainQaGateway",
    "NewsQaResult",
    "NewsRecord",
    "NewsRetrievalService",
    "RedisSemanticNewsSearch",
    "QaCitation",
    "QaGateway",
    "QaProviderUnavailable",
    "QaService",
    "RetrievedArticle",
    "RetrievedPassage",
    "SemanticSearchUnavailable",
    "extract_match_excerpt",
    "tokenize",
]
