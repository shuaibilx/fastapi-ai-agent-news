"""Read-only LangChain tools for the authenticated news agent."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool


@runtime_checkable
class AgentReadPort(Protocol):
    async def search_news(self, query: str, limit: int) -> list[Any]: ...
    async def get_news_detail(self, news_id: int) -> Any | None: ...
    async def list_favorites(
        self, user_id: int, page: int, page_size: int,
    ) -> tuple[list[Any], int]: ...
    async def list_history(
        self, user_id: int, page: int, page_size: int,
    ) -> tuple[list[Any], int]: ...


@dataclass(frozen=True)
class AgentRuntimeContext:
    user_id: int
    reader: AgentReadPort
    retrieval_limit: int
    page_size_limit: int
    tool_result_max_tokens: int


def _display_time(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value) if value is not None else None


def _truncate(text: str, max_tokens: int) -> str:
    if len(text) <= max_tokens:
        return text
    if max_tokens <= 1:
        return "…"
    return text[: max_tokens - 1] + "…"


def _citation(news: Any, excerpt: str | None = None) -> dict[str, Any]:
    source_excerpt = excerpt
    if source_excerpt is None:
        source_excerpt = (
            getattr(news, "description", None)
            or getattr(news, "content", None)
            or getattr(news, "title", "")
        )
    return {
        "news_id": int(news.id),
        "title": str(news.title),
        "excerpt": _truncate(str(source_excerpt), 240) if source_excerpt else None,
    }


def _message(
    runtime: ToolRuntime[AgentRuntimeContext],
    *,
    name: str,
    content: str,
    citations: list[dict[str, Any]],
    summary: str,
    status: str = "success",
) -> ToolMessage:
    return ToolMessage(
        content=_truncate(content, runtime.context.tool_result_max_tokens),
        tool_call_id=runtime.tool_call_id,
        name=name,
        status="error" if status == "error" else "success",
        artifact={
            "citations": citations,
            "tool_summary": {
                "name": name,
                "status": status,
                "summary": summary,
            },
        },
    )


@tool
async def search_news_knowledge(
    query: str,
    runtime: ToolRuntime[AgentRuntimeContext],
    limit: int = 5,
) -> ToolMessage:
    """Search the news knowledge base for passages relevant to a question."""
    bounded_limit = max(1, min(limit, runtime.context.retrieval_limit))
    articles = await runtime.context.reader.search_news(query.strip(), bounded_limit)
    if not articles:
        return _message(
            runtime,
            name="search_news_knowledge",
            content="没有找到与该问题相关的新闻资料。",
            citations=[],
            summary="未找到相关新闻",
        )

    lines = []
    citations = []
    for article in articles:
        excerpt = getattr(article, "excerpt", None) or getattr(article, "description", None)
        lines.append(f"[{article.id}] {article.title}\n{excerpt or ''}")
        citations.append(_citation(article, excerpt))
    return _message(
        runtime,
        name="search_news_knowledge",
        content="\n\n".join(lines),
        citations=citations,
        summary=f"检索到 {len(articles)} 篇相关新闻",
    )


@tool
async def get_news_detail(
    news_id: int,
    runtime: ToolRuntime[AgentRuntimeContext],
) -> ToolMessage:
    """Get the read-only details of one news article by its numeric ID."""
    news = await runtime.context.reader.get_news_detail(news_id)
    if news is None:
        return _message(
            runtime,
            name="get_news_detail",
            content=f"新闻 {news_id} 不存在。",
            citations=[],
            summary="新闻不存在",
        )

    content = "\n".join(filter(None, [
        f"新闻 ID: {news.id}",
        f"标题: {news.title}",
        f"作者: {getattr(news, 'author', None) or '未知'}",
        f"发布时间: {_display_time(getattr(news, 'publish_time', None)) or '未知'}",
        f"简介: {getattr(news, 'description', None) or ''}",
        f"正文: {getattr(news, 'content', None) or ''}",
    ]))
    return _message(
        runtime,
        name="get_news_detail",
        content=content,
        citations=[_citation(news)],
        summary=f"读取新闻 {news.id} 详情",
    )


@tool
async def list_my_favorites(
    runtime: ToolRuntime[AgentRuntimeContext],
    page: int = 1,
    page_size: int = 10,
) -> ToolMessage:
    """List favorite news for the currently authenticated user."""
    bounded_page = max(1, page)
    bounded_page_size = max(1, min(page_size, runtime.context.page_size_limit))
    rows, total = await runtime.context.reader.list_favorites(
        runtime.context.user_id,
        bounded_page,
        bounded_page_size,
    )
    if not rows:
        return _message(
            runtime,
            name="list_my_favorites",
            content="当前用户没有收藏新闻。",
            citations=[],
            summary="收藏列表为空",
        )

    lines = []
    citations = []
    for news, favorite_time, favorite_id in rows:
        lines.append(
            f"收藏 ID {favorite_id} | 新闻 {news.id}: {news.title} | "
            f"收藏时间: {_display_time(favorite_time)}"
        )
        citations.append(_citation(news))
    return _message(
        runtime,
        name="list_my_favorites",
        content=f"收藏总数: {total}\n" + "\n".join(lines),
        citations=citations,
        summary=f"读取 {len(rows)} 条收藏",
    )


@tool
async def list_my_history(
    runtime: ToolRuntime[AgentRuntimeContext],
    page: int = 1,
    page_size: int = 10,
) -> ToolMessage:
    """List browsing history for the currently authenticated user."""
    bounded_page = max(1, page)
    bounded_page_size = max(1, min(page_size, runtime.context.page_size_limit))
    rows, total = await runtime.context.reader.list_history(
        runtime.context.user_id,
        bounded_page,
        bounded_page_size,
    )
    if not rows:
        return _message(
            runtime,
            name="list_my_history",
            content="当前用户没有浏览历史。",
            citations=[],
            summary="浏览历史为空",
        )

    lines = []
    citations = []
    for news, view_time, history_id in rows:
        lines.append(
            f"历史 ID {history_id} | 新闻 {news.id}: {news.title} | "
            f"浏览时间: {_display_time(view_time)}"
        )
        citations.append(_citation(news))
    return _message(
        runtime,
        name="list_my_history",
        content=f"历史总数: {total}\n" + "\n".join(lines),
        citations=citations,
        summary=f"读取 {len(rows)} 条浏览历史",
    )


AGENT_TOOLS = (
    search_news_knowledge,
    get_news_detail,
    list_my_favorites,
    list_my_history,
)
