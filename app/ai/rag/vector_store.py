"""Redis Stack-backed storage and search for news embeddings."""

from dataclasses import dataclass
import struct
from typing import Any, Protocol

from redis.exceptions import ResponseError


class RedisVectorClient(Protocol):
    async def execute_command(self, *parts: Any) -> Any: ...
    async def scan(self, cursor: int = 0, match: str | None = None, count: int | None = None) -> tuple[int, list[str]]: ...
    async def delete(self, *keys: str) -> Any: ...
    async def hset(self, key: str, mapping: dict[str, str | bytes]) -> Any: ...


class NewsVectorStoreUnavailable(RuntimeError):
    """Redis Stack search is unavailable or its index cannot be used."""


@dataclass(frozen=True)
class NewsVectorDocument:
    news_id: int
    title: str
    description: str | None
    content: str | None
    views: int
    embedding: list[float]


@dataclass(frozen=True)
class VectorSearchHit:
    news_id: int
    title: str
    description: str | None
    content: str | None
    views: int
    score: float


class RedisNewsVectorStore:
    def __init__(
        self,
        *,
        redis_client: RedisVectorClient,
        index_name: str,
        key_prefix: str,
        vector_dimensions: int,
    ):
        self._redis = redis_client
        self._index_name = index_name
        self._key_prefix = key_prefix
        self._vector_dimensions = vector_dimensions

    def _key_for(self, news_id: int) -> str:
        return f"{self._key_prefix}{news_id}"

    def _pack_embedding(self, embedding: list[float]) -> bytes:
        if len(embedding) != self._vector_dimensions:
            raise ValueError(
                f"embedding 必须包含 {self._vector_dimensions} 个维度，实际为 {len(embedding)}"
            )
        try:
            return struct.pack(f"<{self._vector_dimensions}f", *embedding)
        except (TypeError, struct.error) as exc:
            raise ValueError("embedding 必须由数值组成") from exc

    async def ensure_index(self) -> None:
        try:
            await self._redis.execute_command("FT.INFO", self._index_name)
            return
        except ResponseError as exc:
            if "unknown index" not in str(exc).lower():
                raise NewsVectorStoreUnavailable("新闻向量索引不可用") from exc
        except (OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("新闻向量索引不可用") from exc

        try:
            await self._redis.execute_command(
                "FT.CREATE",
                self._index_name,
                "ON", "HASH",
                "PREFIX", "1", self._key_prefix,
                "SCHEMA",
                "news_id", "NUMERIC", "SORTABLE",
                "title", "TEXT",
                "description", "TEXT",
                "content", "TEXT",
                "views", "NUMERIC", "SORTABLE",
                "embedding", "VECTOR", "HNSW", "6",
                "TYPE", "FLOAT32",
                "DIM", str(self._vector_dimensions),
                "DISTANCE_METRIC", "COSINE",
            )
        except (ResponseError, OSError, ConnectionError) as exc:
            if isinstance(exc, ResponseError) and "index already exists" in str(exc).lower():
                return
            raise NewsVectorStoreUnavailable("无法创建新闻向量索引") from exc

    async def clear_documents(self) -> None:
        cursor = 0
        try:
            while True:
                cursor, keys = await self._redis.scan(
                    cursor,
                    match=f"{self._key_prefix}*",
                    count=100,
                )
                if keys:
                    await self._redis.delete(*keys)
                if cursor == 0:
                    return
        except (ResponseError, OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("无法清理新闻向量索引") from exc

    async def replace_documents(self, documents: list[NewsVectorDocument]) -> None:
        packed_documents = [
            (document, self._pack_embedding(document.embedding))
            for document in documents
        ]
        await self.ensure_index()
        await self.clear_documents()
        try:
            for document, packed_embedding in packed_documents:
                await self._redis.hset(
                    self._key_for(document.news_id),
                    mapping={
                        "news_id": str(document.news_id),
                        "title": document.title,
                        "description": document.description or "",
                        "content": document.content or "",
                        "views": str(document.views),
                        "embedding": packed_embedding,
                    },
                )
        except (ResponseError, OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("无法写入新闻向量索引") from exc

    async def search(
        self,
        embedding: list[float],
        *,
        limit: int,
        minimum_score: float,
    ) -> list[VectorSearchHit]:
        packed_embedding = self._pack_embedding(embedding)
        bounded_limit = max(1, limit)
        try:
            response = await self._redis.execute_command(
                "FT.SEARCH",
                self._index_name,
                "*=>[KNN $limit @embedding $vector AS vector_distance]",
                "PARAMS", "4", "limit", str(bounded_limit), "vector", packed_embedding,
                "SORTBY", "vector_distance",
                "RETURN", "6", "news_id", "title", "description", "content", "views", "vector_distance",
                "DIALECT", "2",
            )
        except (ResponseError, OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("新闻向量检索暂时不可用") from exc
        return self._parse_search_response(response, minimum_score)

    @staticmethod
    def _parse_search_response(response: Any, minimum_score: float) -> list[VectorSearchHit]:
        if not isinstance(response, (list, tuple)) or not response:
            raise NewsVectorStoreUnavailable("新闻向量检索返回了无效结果")
        hits: list[VectorSearchHit] = []
        for position in range(1, len(response), 2):
            fields = response[position + 1]
            if not isinstance(fields, (list, tuple)):
                raise NewsVectorStoreUnavailable("新闻向量检索返回了无效结果")
            values = {
                RedisNewsVectorStore._decode_text(fields[index]): RedisNewsVectorStore._decode_text(fields[index + 1])
                for index in range(0, len(fields) - 1, 2)
            }
            try:
                score = 1.0 - float(values["vector_distance"])
                if score < minimum_score:
                    continue
                hits.append(VectorSearchHit(
                    news_id=int(values["news_id"]),
                    title=str(values["title"]),
                    description=str(values.get("description") or "") or None,
                    content=str(values.get("content") or "") or None,
                    views=int(values.get("views") or 0),
                    score=score,
                ))
            except (KeyError, TypeError, ValueError) as exc:
                raise NewsVectorStoreUnavailable("新闻向量检索返回了无效结果") from exc
        return hits

    @staticmethod
    def _decode_text(value: Any) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)
