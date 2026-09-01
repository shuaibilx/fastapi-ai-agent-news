"""Build-isolated Redis Stack storage and search for news chunks."""

from dataclasses import dataclass
import re
import struct
from typing import Any, Protocol

from redis.exceptions import ResponseError


class RedisVectorClient(Protocol):
    async def execute_command(self, *parts: Any) -> Any: ...
    async def scan(
        self,
        cursor: int = 0,
        match: str | None = None,
        count: int | None = None,
    ) -> tuple[int, list[str]]: ...
    async def delete(self, *keys: str) -> Any: ...
    async def hset(self, key: str, mapping: dict[str, str | bytes]) -> Any: ...


class NewsVectorStoreUnavailable(RuntimeError):
    """Redis Stack search is unavailable or its index cannot be used."""


@dataclass(frozen=True)
class NewsVectorDocument:
    news_id: int
    chunk_id: str
    chunk_index: int
    start_index: int
    end_index: int
    title: str
    description: str | None
    chunk_text: str
    content_hash: str
    category_id: int
    publish_time: str
    views: int
    embedding: list[float]


@dataclass(frozen=True)
class VectorSearchHit:
    news_id: int
    chunk_id: str
    chunk_index: int
    start_index: int
    end_index: int
    title: str
    description: str | None
    chunk_text: str
    content_hash: str
    category_id: int
    publish_time: str
    views: int
    score: float


class RedisNewsVectorStore:
    _BUILD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

    def __init__(
        self,
        *,
        redis_client: RedisVectorClient,
        index_alias: str,
        index_prefix: str,
        key_prefix: str,
        vector_dimensions: int,
    ):
        self._redis = redis_client
        self._index_alias = index_alias.rstrip(":")
        self._index_prefix = index_prefix.rstrip(":")
        self._key_prefix = key_prefix.rstrip(":")
        self._vector_dimensions = vector_dimensions

    def build_index_name(self, build_id: str) -> str:
        self._validate_build_id(build_id)
        return f"{self._index_prefix}:{build_id}"

    def build_key_prefix(self, build_id: str) -> str:
        self._validate_build_id(build_id)
        return f"{self._key_prefix}:{build_id}:"

    def _key_for(self, build_id: str, document: NewsVectorDocument) -> str:
        return f"{self.build_key_prefix(build_id)}{document.news_id}:{document.chunk_index}"

    @classmethod
    def _validate_build_id(cls, build_id: str) -> None:
        if not cls._BUILD_ID_RE.fullmatch(build_id):
            raise ValueError("build_id 只能包含字母、数字、下划线和连字符")

    def _pack_embedding(self, embedding: list[float]) -> bytes:
        if len(embedding) != self._vector_dimensions:
            raise ValueError(
                f"embedding 必须包含 {self._vector_dimensions} 个维度，实际为 {len(embedding)}"
            )
        try:
            return struct.pack(f"<{self._vector_dimensions}f", *embedding)
        except (TypeError, struct.error) as exc:
            raise ValueError("embedding 必须由数值组成") from exc

    async def prepare_build(self, build_id: str) -> str:
        index_name = self.build_index_name(build_id)
        key_prefix = self.build_key_prefix(build_id)
        try:
            await self._redis.execute_command("FT.INFO", index_name)
        except ResponseError as exc:
            if "unknown index" not in str(exc).lower():
                raise NewsVectorStoreUnavailable("无法检查新闻 Chunk 候选索引") from exc
        except (OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("无法检查新闻 Chunk 候选索引") from exc
        else:
            raise ValueError(f"候选索引已存在: {index_name}")

        try:
            await self._redis.execute_command(
                "FT.CREATE",
                index_name,
                "ON", "HASH",
                "PREFIX", "1", key_prefix,
                "SCHEMA",
                "news_id", "NUMERIC", "SORTABLE",
                "chunk_id", "TAG",
                "chunk_index", "NUMERIC", "SORTABLE",
                "start_index", "NUMERIC",
                "end_index", "NUMERIC",
                "title", "TEXT",
                "description", "TEXT",
                "chunk_text", "TEXT",
                "content_hash", "TAG",
                "category_id", "NUMERIC", "SORTABLE",
                "publish_time", "TEXT",
                "views", "NUMERIC", "SORTABLE",
                "embedding", "VECTOR", "HNSW", "6",
                "TYPE", "FLOAT32",
                "DIM", str(self._vector_dimensions),
                "DISTANCE_METRIC", "COSINE",
            )
            return index_name
        except (ResponseError, OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("无法创建新闻 Chunk 候选索引") from exc

    async def write_documents(
        self,
        build_id: str,
        documents: list[NewsVectorDocument],
    ) -> int:
        packed_documents = [
            (document, self._pack_embedding(document.embedding))
            for document in documents
        ]
        try:
            for document, packed_embedding in packed_documents:
                await self._redis.hset(
                    self._key_for(build_id, document),
                    mapping={
                        "news_id": str(document.news_id),
                        "chunk_id": document.chunk_id,
                        "chunk_index": str(document.chunk_index),
                        "start_index": str(document.start_index),
                        "end_index": str(document.end_index),
                        "title": document.title,
                        "description": document.description or "",
                        "chunk_text": document.chunk_text,
                        "content_hash": document.content_hash,
                        "category_id": str(document.category_id),
                        "publish_time": document.publish_time,
                        "views": str(document.views),
                        "embedding": packed_embedding,
                    },
                )
            return len(packed_documents)
        except (ResponseError, OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("无法写入新闻 Chunk 候选索引") from exc

    async def validate_build(
        self,
        build_id: str,
        *,
        expected_documents: int,
        probe_embedding: list[float] | None = None,
    ) -> None:
        index_name = self.build_index_name(build_id)
        try:
            response = await self._redis.execute_command(
                "FT.SEARCH", index_name, "*", "LIMIT", "0", "0"
            )
            actual = int(response[0])
            if expected_documents:
                if probe_embedding is None:
                    raise ValueError("非空候选索引需要提供查询向量")
                probe_response = await self._redis.execute_command(
                    "FT.SEARCH",
                    index_name,
                    "*=>[KNN 1 @embedding $vector AS vector_distance]",
                    "NOCONTENT",
                    "PARAMS", "2", "vector", self._pack_embedding(probe_embedding),
                    "SORTBY", "vector_distance",
                    "LIMIT", "0", "1",
                    "DIALECT", "2",
                )
                if int(probe_response[0]) < 1:
                    raise ValueError("新闻 Chunk 候选索引无法完成向量查询")
        except (ResponseError, OSError, ConnectionError, TypeError, ValueError, IndexError) as exc:
            raise NewsVectorStoreUnavailable("无法验证新闻 Chunk 候选索引") from exc
        if actual != expected_documents:
            raise NewsVectorStoreUnavailable(
                f"新闻 Chunk 候选索引不完整: expected={expected_documents}, actual={actual}"
            )

    async def activate_build(self, build_id: str) -> str:
        index_name = self.build_index_name(build_id)
        try:
            await self._redis.execute_command("FT.INFO", index_name)
            try:
                await self._redis.execute_command(
                    "FT.ALIASUPDATE", self._index_alias, index_name
                )
            except ResponseError as exc:
                message = str(exc).lower()
                if "unknown alias" not in message and "alias does not exist" not in message:
                    raise
                await self._redis.execute_command(
                    "FT.ALIASADD", self._index_alias, index_name
                )
            return index_name
        except (ResponseError, OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("无法激活新闻 Chunk 索引") from exc

    async def discard_build(self, build_id: str) -> None:
        index_name = self.build_index_name(build_id)
        active_index = await self._active_index_name()
        if active_index == index_name:
            raise ValueError("不能清理活动新闻 Chunk 索引")
        await self._delete_build_documents(build_id)
        try:
            await self._redis.execute_command("FT.DROPINDEX", index_name)
        except ResponseError as exc:
            if "unknown index" not in str(exc).lower():
                raise NewsVectorStoreUnavailable("无法删除新闻 Chunk 候选索引") from exc
        except (OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("无法删除新闻 Chunk 候选索引") from exc

    async def _active_index_name(self) -> str | None:
        try:
            info = await self._redis.execute_command("FT.INFO", self._index_alias)
        except ResponseError as exc:
            if "unknown index" in str(exc).lower() or "unknown alias" in str(exc).lower():
                return None
            raise NewsVectorStoreUnavailable("无法读取活动新闻 Chunk 索引") from exc
        except (OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("无法读取活动新闻 Chunk 索引") from exc
        values = {
            self._decode_text(info[index]): self._decode_text(info[index + 1])
            for index in range(0, len(info) - 1, 2)
        }
        return values.get("index_name")

    async def _delete_build_documents(self, build_id: str) -> None:
        cursor = 0
        pattern = f"{self.build_key_prefix(build_id)}*"
        try:
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                if cursor == 0:
                    return
        except (ResponseError, OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("无法清理新闻 Chunk 文档") from exc

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
                self._index_alias,
                "*=>[KNN $limit @embedding $vector AS vector_distance]",
                "PARAMS", "4", "limit", str(bounded_limit), "vector", packed_embedding,
                "SORTBY", "vector_distance",
                "RETURN", "13",
                "news_id", "chunk_id", "chunk_index", "start_index", "end_index",
                "title", "description", "chunk_text", "content_hash", "category_id",
                "publish_time", "views", "vector_distance",
                "DIALECT", "2",
            )
        except (ResponseError, OSError, ConnectionError) as exc:
            raise NewsVectorStoreUnavailable("新闻 Chunk 向量检索暂时不可用") from exc
        return self._parse_search_response(response, minimum_score)

    @staticmethod
    def _parse_search_response(
        response: Any,
        minimum_score: float,
    ) -> list[VectorSearchHit]:
        if not isinstance(response, (list, tuple)) or not response:
            raise NewsVectorStoreUnavailable("新闻 Chunk 向量检索返回了无效结果")
        hits: list[VectorSearchHit] = []
        for position in range(1, len(response), 2):
            if position + 1 >= len(response):
                raise NewsVectorStoreUnavailable("新闻 Chunk 向量检索返回了无效结果")
            fields = response[position + 1]
            if not isinstance(fields, (list, tuple)):
                raise NewsVectorStoreUnavailable("新闻 Chunk 向量检索返回了无效结果")
            values = {
                RedisNewsVectorStore._decode_text(fields[index]):
                    RedisNewsVectorStore._decode_text(fields[index + 1])
                for index in range(0, len(fields) - 1, 2)
            }
            try:
                score = 1.0 - float(values["vector_distance"])
                if score < minimum_score:
                    continue
                hits.append(VectorSearchHit(
                    news_id=int(values["news_id"]),
                    chunk_id=values["chunk_id"],
                    chunk_index=int(values["chunk_index"]),
                    start_index=int(values["start_index"]),
                    end_index=int(values["end_index"]),
                    title=values["title"],
                    description=values.get("description") or None,
                    chunk_text=values["chunk_text"],
                    content_hash=values["content_hash"],
                    category_id=int(values["category_id"]),
                    publish_time=values["publish_time"],
                    views=int(values.get("views") or 0),
                    score=score,
                ))
            except (KeyError, TypeError, ValueError) as exc:
                raise NewsVectorStoreUnavailable(
                    "新闻 Chunk 向量检索返回了无效结果"
                ) from exc
        return hits

    @staticmethod
    def _decode_text(value: Any) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)
