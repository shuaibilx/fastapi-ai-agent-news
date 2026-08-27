"""Deterministic application-side metadata collected from agent tool messages."""

from dataclasses import dataclass
from typing import Any, Iterable

from langchain.messages import ToolMessage
from langchain_core.messages import BaseMessage

from app.ai.agent.safety import sanitize_value


@dataclass(frozen=True)
class AgentCitation:
    news_id: int
    title: str
    excerpt: str | None = None


@dataclass(frozen=True)
class AgentToolSummary:
    name: str
    status: str
    summary: str


def collect_tool_metadata(
    messages: Iterable[BaseMessage],
) -> tuple[list[AgentCitation], list[AgentToolSummary]]:
    citations: list[AgentCitation] = []
    summaries: list[AgentToolSummary] = []
    seen_news_ids: set[int] = set()

    for message in messages:
        if not isinstance(message, ToolMessage) or not isinstance(message.artifact, dict):
            continue
        artifact: dict[str, Any] = sanitize_value(message.artifact)

        raw_citations = artifact.get("citations")
        if isinstance(raw_citations, list):
            for item in raw_citations:
                if not isinstance(item, dict):
                    continue
                try:
                    news_id = int(item["news_id"])
                    title = str(item["title"])
                except (KeyError, TypeError, ValueError):
                    continue
                if news_id in seen_news_ids:
                    continue
                seen_news_ids.add(news_id)
                excerpt = item.get("excerpt")
                citations.append(AgentCitation(
                    news_id=news_id,
                    title=title,
                    excerpt=str(excerpt) if excerpt is not None else None,
                ))

        raw_summary = artifact.get("tool_summary")
        if isinstance(raw_summary, dict):
            try:
                summaries.append(AgentToolSummary(
                    name=str(raw_summary["name"]),
                    status=str(raw_summary["status"]),
                    summary=str(raw_summary["summary"]),
                ))
            except KeyError:
                continue

    return citations, summaries
