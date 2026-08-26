"""Utilities shared by the AI news-summary capability."""

from hashlib import sha256

from app.ai.summarization.cache import SummaryCache
from app.ai.summarization.gateway import (
    LangChainSummaryGateway,
    SummaryProviderUnavailable,
    validate_summary_text,
)


def build_content_hash(title: str, content: str) -> str:
    """Return a stable version identifier for the summarizable article data."""
    source = f"{title.strip()}\n\n{content.strip()}"
    return sha256(source.encode("utf-8")).hexdigest()


def build_summary_cache_key(news_id: int, content_hash: str) -> str:
    """Build an isolated, versioned Redis key for a news summary."""
    return f"ai:summary:v1:{news_id}:{content_hash}"


from app.ai.summarization.service import NewsSummaryResult, NewsSummaryService
