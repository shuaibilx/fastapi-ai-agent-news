"""Deterministic, token-aware chunking for Chinese news articles."""

from dataclasses import dataclass
from hashlib import sha256
from html import unescape
from pathlib import Path
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter
from tokenizers import Tokenizer


_BLOCK_END_RE = re.compile(r"</(?:p|div|section|article|h[1-6]|li)>|<br\s*/?>", re.IGNORECASE)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_INLINE_SPACE_RE = re.compile(r"[\t\f\v \u3000]+")
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


def normalize_news_text(value: str | None) -> str:
    """Return stable plain text while preserving meaningful paragraph breaks."""
    if not value:
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _SCRIPT_STYLE_RE.sub("", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = unescape(text).replace("\xa0", " ")
    lines = [_INLINE_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _EXCESS_NEWLINES_RE.sub("\n\n", text)
    return text.strip()


class BgeTokenCounter:
    """Count and truncate text with the tokenizer used by the local BGE model."""

    def __init__(self, tokenizer_path: str | Path):
        path = Path(tokenizer_path)
        if not path.is_file():
            raise FileNotFoundError(f"BGE tokenizer 不存在: {path}")
        self._tokenizer = Tokenizer.from_file(str(path))

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text).ids) if text else 0

    def truncate(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0 or not text:
            return ""
        if self.count(text) <= max_tokens:
            return text
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if self.count(text[:middle]) <= max_tokens:
                low = middle
            else:
                high = middle - 1
        return text[:low].rstrip()


@dataclass(frozen=True)
class NewsChunk:
    news_id: int
    chunk_id: str
    chunk_index: int
    start_index: int
    end_index: int
    chunk_text: str
    embedding_text: str
    content_hash: str
    title: str
    description: str | None


class NewsChunker:
    """Split normalized news content without exceeding the embedding input budget."""

    _SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", "、", ""]

    def __init__(
        self,
        *,
        token_counter: BgeTokenCounter,
        chunk_size_tokens: int,
        chunk_overlap_tokens: int,
        embedding_input_max_tokens: int,
    ):
        if chunk_overlap_tokens >= chunk_size_tokens:
            raise ValueError("Chunk overlap 必须小于 Chunk size")
        if chunk_size_tokens >= embedding_input_max_tokens:
            raise ValueError("Chunk size 必须小于 Embedding 输入上限")
        self._tokens = token_counter
        self._chunk_size_tokens = chunk_size_tokens
        self._embedding_input_max_tokens = embedding_input_max_tokens
        self._splitter = RecursiveCharacterTextSplitter(
            separators=self._SEPARATORS,
            keep_separator=True,
            chunk_size=chunk_size_tokens,
            chunk_overlap=chunk_overlap_tokens,
            length_function=token_counter.count,
            add_start_index=True,
        )

    def split(
        self,
        *,
        news_id: int,
        title: str,
        description: str | None,
        content: str,
    ) -> list[NewsChunk]:
        clean_title = normalize_news_text(title)
        clean_description = normalize_news_text(description) or None
        clean_content = normalize_news_text(content)
        if not clean_content:
            return []

        whole_embedding = self._embedding_text(
            clean_title,
            clean_description,
            clean_content,
            first=True,
        )
        if self._tokens.count(whole_embedding) <= self._embedding_input_max_tokens:
            pieces = [(clean_content, 0)]
        else:
            documents = self._splitter.create_documents([clean_content])
            pieces = [
                (document.page_content.strip(), int(document.metadata.get("start_index", 0)))
                for document in documents
                if document.page_content.strip()
            ]

        content_hash = sha256(clean_content.encode("utf-8")).hexdigest()
        chunks: list[NewsChunk] = []
        for chunk_index, (chunk_text, start_index) in enumerate(pieces):
            embedding_text = self._embedding_text(
                clean_title,
                clean_description,
                chunk_text,
                first=chunk_index == 0,
            )
            if self._tokens.count(embedding_text) > self._embedding_input_max_tokens:
                raise ValueError("生成的新闻 Chunk 超过 Embedding 输入上限")
            chunks.append(NewsChunk(
                news_id=news_id,
                chunk_id=f"{news_id}:{chunk_index}:{content_hash[:16]}",
                chunk_index=chunk_index,
                start_index=start_index,
                end_index=start_index + len(chunk_text),
                chunk_text=chunk_text,
                embedding_text=embedding_text,
                content_hash=content_hash,
                title=clean_title,
                description=clean_description,
            ))
        return chunks

    def _embedding_text(
        self,
        title: str,
        description: str | None,
        chunk_text: str,
        *,
        first: bool,
    ) -> str:
        title = self._tokens.truncate(title, 48)
        description = self._tokens.truncate(description or "", 48) if first else ""
        lines = [f"标题：{title}"] if title else []
        if description:
            lines.append(f"简介：{description}")
        lines.append(f"正文片段：{chunk_text}")
        result = "\n".join(lines)
        if self._tokens.count(result) <= self._embedding_input_max_tokens:
            return result

        # Metadata is supplemental; preserve the complete retrievable passage first.
        if description:
            lines = [line for line in lines if not line.startswith("简介：")]
            result = "\n".join(lines)
        if self._tokens.count(result) <= self._embedding_input_max_tokens:
            return result
        if title:
            lines = [line for line in lines if not line.startswith("标题：")]
            result = "\n".join(lines)
        return result
