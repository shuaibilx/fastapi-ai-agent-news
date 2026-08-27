import asyncio
from datetime import datetime
from types import SimpleNamespace

from langchain.messages import ToolMessage

from app.ai.agent.tools import (
    AgentRuntimeContext,
    get_news_detail,
    list_my_favorites,
    list_my_history,
    search_news_knowledge,
)


class FakeReader:
    def __init__(self):
        self.calls = []
        self.search_result = []
        self.detail_result = None
        self.favorite_result = ([], 0)
        self.history_result = ([], 0)

    async def search_news(self, query, limit):
        self.calls.append(("search", query, limit))
        return self.search_result

    async def get_news_detail(self, news_id):
        self.calls.append(("detail", news_id))
        return self.detail_result

    async def list_favorites(self, user_id, page, page_size):
        self.calls.append(("favorites", user_id, page, page_size))
        return self.favorite_result

    async def list_history(self, user_id, page, page_size):
        self.calls.append(("history", user_id, page, page_size))
        return self.history_result


def runtime(reader, *, user_id=7, max_tokens=100):
    return SimpleNamespace(
        tool_call_id="call-1",
        context=AgentRuntimeContext(
            user_id=user_id,
            reader=reader,
            retrieval_limit=5,
            page_size_limit=10,
            tool_result_max_tokens=max_tokens,
        ),
    )


def invoke(tool, **kwargs):
    return asyncio.run(tool.coroutine(**kwargs))


def article(news_id=11, title="AI 新闻", content="新闻正文"):
    return SimpleNamespace(
        id=news_id,
        title=title,
        description="新闻简介",
        content=content,
        author="作者",
        category_id=2,
        views=9,
        publish_time=datetime(2026, 8, 27, 8, 0, 0),
        excerpt="相关摘录",
    )


def test_tool_schemas_never_expose_authenticated_user_id_or_runtime():
    for tool in (search_news_knowledge, get_news_detail, list_my_favorites, list_my_history):
        properties = tool.tool_call_schema.model_json_schema()["properties"]
        assert "user_id" not in properties
        assert "runtime" not in properties


def test_news_search_uses_shared_reader_and_caps_requested_limit():
    reader = FakeReader()
    reader.search_result = [article()]

    result = invoke(
        search_news_knowledge,
        query="人工智能",
        limit=99,
        runtime=runtime(reader),
    )

    assert isinstance(result, ToolMessage)
    assert reader.calls == [("search", "人工智能", 5)]
    assert "AI 新闻" in result.content
    assert result.artifact["citations"] == [
        {"news_id": 11, "title": "AI 新闻", "excerpt": "相关摘录"},
    ]


def test_news_detail_returns_serializable_content_without_orm_internal_state():
    reader = FakeReader()
    reader.detail_result = article(content="完整正文")

    result = invoke(get_news_detail, news_id=11, runtime=runtime(reader))

    assert reader.calls == [("detail", 11)]
    assert "完整正文" in result.content
    assert "_sa_instance_state" not in result.content
    assert result.artifact["citations"][0]["news_id"] == 11


def test_favorites_are_scoped_to_runtime_user_and_page_size_is_bounded():
    reader = FakeReader()
    reader.favorite_result = ([(article(), datetime(2026, 8, 27, 9, 0, 0), 51)], 1)

    result = invoke(
        list_my_favorites,
        page=0,
        page_size=100,
        runtime=runtime(reader, user_id=23),
    )

    assert reader.calls == [("favorites", 23, 1, 10)]
    assert "AI 新闻" in result.content
    assert result.artifact["citations"][0]["news_id"] == 11


def test_history_is_scoped_to_runtime_user_and_handles_empty_results():
    reader = FakeReader()

    result = invoke(
        list_my_history,
        page=1,
        page_size=10,
        runtime=runtime(reader, user_id=24),
    )

    assert reader.calls == [("history", 24, 1, 10)]
    assert "没有浏览历史" in result.content
    assert result.artifact["citations"] == []


def test_model_visible_tool_content_is_capped_without_losing_citation_metadata():
    reader = FakeReader()
    reader.detail_result = article(content="很长的正文" * 30)

    result = invoke(
        get_news_detail,
        news_id=11,
        runtime=runtime(reader, max_tokens=40),
    )

    assert len(result.content) <= 40
    assert result.content.endswith("…")
    assert result.artifact["citations"][0]["news_id"] == 11
    assert result.artifact["citations"][0]["title"] == "AI 新闻"
