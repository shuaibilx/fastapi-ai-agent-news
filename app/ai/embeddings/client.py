"""Client for the locally hosted Text Embeddings Inference service."""

from typing import Protocol

import httpx


class EmbeddingHttpClient(Protocol):
    async def post(self, url: str, *, json: dict) -> httpx.Response: ...


class EmbeddingProviderUnavailable(RuntimeError):
    """The local embedding service could not produce trustworthy vectors."""


class TeiEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int,
        vector_dimensions: int,
        http_client: EmbeddingHttpClient | None = None,
    ):
        self._endpoint = f"{base_url.rstrip('/')}/embed"
        self._timeout_seconds = timeout_seconds
        self._vector_dimensions = vector_dimensions
        self._http_client = http_client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            if self._http_client is not None:
                response = await self._http_client.post(self._endpoint, json={"inputs": texts})
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(self._endpoint, json={"inputs": texts})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            raise EmbeddingProviderUnavailable("本地 Embedding 服务暂时不可用") from exc

        if not isinstance(payload, list) or len(payload) != len(texts):
            raise EmbeddingProviderUnavailable("本地 Embedding 服务返回了无效向量")

        vectors: list[list[float]] = []
        for vector in payload:
            if not isinstance(vector, list) or len(vector) != self._vector_dimensions:
                raise EmbeddingProviderUnavailable("本地 Embedding 服务返回了错误维度")
            try:
                vectors.append([float(value) for value in vector])
            except (TypeError, ValueError) as exc:
                raise EmbeddingProviderUnavailable("本地 Embedding 服务返回了无效向量") from exc
        return vectors
