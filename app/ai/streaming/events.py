"""Stable, public domain events for AI server-sent event responses."""

from dataclasses import dataclass
from typing import Any


class StreamProtocolError(ValueError):
    """Raised when an event could expose data outside the public SSE contract."""


@dataclass(frozen=True)
class StreamEvent:
    name: str
    data: dict[str, Any]

    @classmethod
    def meta(cls, data: dict[str, Any]) -> "StreamEvent":
        return cls("meta", data)

    @classmethod
    def delta(cls, text: str) -> "StreamEvent":
        return cls("delta", {"text": text})

    @classmethod
    def citation(cls, data: dict[str, Any]) -> "StreamEvent":
        return cls("citation", data)

    @classmethod
    def tool(cls, data: dict[str, Any]) -> "StreamEvent":
        return cls("tool", data)

    @classmethod
    def done(cls, data: dict[str, Any]) -> "StreamEvent":
        return cls("done", data)

    @classmethod
    def error(cls, message: str) -> "StreamEvent":
        return cls("error", {"message": message})

    @classmethod
    def ping(cls) -> "StreamEvent":
        return cls("ping", {})


def _require_exact_keys(data: dict[str, Any], allowed: set[str], required: set[str] = set()) -> None:
    keys = set(data)
    if not required.issubset(keys) or not keys.issubset(allowed):
        raise StreamProtocolError("SSE 事件包含不允许的字段")


def _validate_citation(data: dict[str, Any]) -> None:
    _require_exact_keys(data, {"newsId", "title", "excerpt"}, {"newsId", "title"})
    if not isinstance(data["newsId"], int) or not isinstance(data["title"], str):
        raise StreamProtocolError("新闻引用字段类型无效")
    if "excerpt" in data and data["excerpt"] is not None and not isinstance(data["excerpt"], str):
        raise StreamProtocolError("新闻引用摘录字段类型无效")


def _validate_tool(data: dict[str, Any]) -> None:
    _require_exact_keys(data, {"name", "status", "summary"}, {"name", "status", "summary"})
    if not all(isinstance(data[key], str) for key in ("name", "status", "summary")):
        raise StreamProtocolError("工具状态字段类型无效")


def validate_stream_event(event: StreamEvent) -> None:
    if event.name == "meta":
        _require_exact_keys(event.data, {"mode", "conversationId", "memoryStatus"})
        return
    if event.name == "delta":
        _require_exact_keys(event.data, {"text"}, {"text"})
        if not isinstance(event.data["text"], str) or not event.data["text"]:
            raise StreamProtocolError("文本增量不能为空")
        return
    if event.name == "citation":
        _validate_citation(event.data)
        return
    if event.name == "tool":
        _validate_tool(event.data)
        return
    if event.name == "done":
        _require_exact_keys(event.data, {"citations", "toolCalls", "conversationId", "memoryStatus"})
        if "citations" in event.data:
            if not isinstance(event.data["citations"], list):
                raise StreamProtocolError("完成事件引用字段无效")
            for citation in event.data["citations"]:
                if not isinstance(citation, dict):
                    raise StreamProtocolError("完成事件引用字段无效")
                _validate_citation(citation)
        if "toolCalls" in event.data:
            if not isinstance(event.data["toolCalls"], list):
                raise StreamProtocolError("完成事件工具字段无效")
            for tool in event.data["toolCalls"]:
                if not isinstance(tool, dict):
                    raise StreamProtocolError("完成事件工具字段无效")
                _validate_tool(tool)
        return
    if event.name == "error":
        _require_exact_keys(event.data, {"message"}, {"message"})
        if not isinstance(event.data["message"], str):
            raise StreamProtocolError("错误事件字段无效")
        return
    if event.name == "ping":
        _require_exact_keys(event.data, set())
        return
    raise StreamProtocolError("未知 SSE 事件")
