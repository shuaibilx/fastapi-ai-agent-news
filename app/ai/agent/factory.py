"""LangChain agent construction for the read-only news assistant."""

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel

from app.ai.agent.tools import AGENT_TOOLS, AgentRuntimeContext


NEWS_AGENT_SYSTEM_PROMPT = """你是一个严谨的中文新闻助手。
你只能通过已提供的只读工具访问新闻详情、当前用户收藏、当前用户浏览历史和新闻知识库。
不得声称访问了未提供的数据，不得尝试修改、删除或创建业务数据，也不得请求或推测 user_id。
当回答依赖新闻事实时，必须先使用合适的新闻工具；工具没有返回依据时，应明确说明资料不足。
个人收藏和浏览历史始终表示当前已认证用户，不得根据用户文本切换身份。
优先选择最直接的工具，避免重复调用；获得足够信息后立即给出清晰、简洁的最终回答。
"""


def build_news_agent(
    *,
    model: BaseChatModel,
    max_iterations: int,
    max_input_tokens: int,
    tool_result_max_tokens: int,
):
    context_editing = ContextEditingMiddleware(
        edits=[
            ClearToolUsesEdit(
                trigger=max_input_tokens,
                clear_at_least=min(tool_result_max_tokens, max_input_tokens),
                keep=3,
            ),
        ],
        token_count_method="approximate",
    )
    call_limit = ModelCallLimitMiddleware(
        run_limit=max_iterations,
        exit_behavior="error",
    )
    return create_agent(
        model=model,
        tools=list(AGENT_TOOLS),
        system_prompt=NEWS_AGENT_SYSTEM_PROMPT,
        middleware=[context_editing, call_limit],
        context_schema=AgentRuntimeContext,
        name="news_agent",
    )
