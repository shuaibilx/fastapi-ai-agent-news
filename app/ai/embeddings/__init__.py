"""News embedding and semantic retrieval capability."""
"""Embedding provider integrations."""

from app.ai.embeddings.client import EmbeddingProviderUnavailable, TeiEmbeddingClient

__all__ = ["EmbeddingProviderUnavailable", "TeiEmbeddingClient"]
