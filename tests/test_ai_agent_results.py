from langchain.messages import AIMessage, ToolMessage

from app.ai.agent.results import collect_tool_metadata


def tool_message(call_id, *, news_id, title, secret=None):
    artifact = {
        "citations": [
            {"news_id": news_id, "title": title, "excerpt": f"{title}摘录"},
        ],
        "tool_summary": {
            "name": "search_news_knowledge",
            "status": "success",
            "summary": f"找到 {title}",
        },
    }
    if secret:
        artifact["database_password"] = secret
    return ToolMessage(
        content=title,
        tool_call_id=call_id,
        name="search_news_knowledge",
        artifact=artifact,
    )


def test_collect_tool_metadata_deduplicates_citations_and_ignores_unknown_fields():
    citations, summaries = collect_tool_metadata([
        AIMessage(content="准备检索"),
        tool_message("call-1", news_id=11, title="第一篇", secret="do-not-leak"),
        tool_message("call-2", news_id=11, title="第一篇"),
        tool_message("call-3", news_id=12, title="第二篇"),
    ])

    assert [(item.news_id, item.title) for item in citations] == [
        (11, "第一篇"),
        (12, "第二篇"),
    ]
    assert [item.name for item in summaries] == [
        "search_news_knowledge",
        "search_news_knowledge",
        "search_news_knowledge",
    ]
    assert "do-not-leak" not in repr((citations, summaries))


def test_collect_tool_metadata_ignores_untrusted_or_malformed_artifacts():
    citations, summaries = collect_tool_metadata([
        ToolMessage(content="plain", tool_call_id="call-1", artifact="not-a-dict"),
        ToolMessage(content="plain", tool_call_id="call-2", artifact={"citations": "bad"}),
    ])

    assert citations == []
    assert summaries == []


def test_collect_tool_metadata_redacts_personal_information_in_artifacts():
    message = tool_message("call-4", news_id=13, title="联系 alice@example.com")

    citations, summaries = collect_tool_metadata([message])

    assert citations[0].title != "联系 alice@example.com"
    assert "alice@example.com" not in repr((citations, summaries))
