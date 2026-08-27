"""LangChain agent construction for the read-only news assistant."""

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    PIIMiddleware,
    SummarizationMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel

from app.ai.agent.tools import AGENT_TOOLS, AgentRuntimeContext
from app.ai.agent.safety import (
    detect_api_key,
    detect_bearer_token,
    detect_jwt,
    detect_national_id,
    detect_phone,
    detect_private_key,
)


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
    summary_trigger_tokens: int = 6000,
    summary_keep_tokens: int = 2500,
    summary_model: BaseChatModel | None = None,
    checkpointer: Any | None = None,
):
    pii_middleware = [
        PIIMiddleware(
            pii_type,
            strategy="redact",
            apply_to_input=True,
            apply_to_output=True,
            apply_to_tool_results=True,
        )
        for pii_type in ("email", "credit_card", "ip")
    ]
    pii_middleware.extend([
        PIIMiddleware(
            "phone",
            strategy="redact",
            detector=detect_phone,
            apply_to_input=True,
            apply_to_output=True,
            apply_to_tool_results=True,
        ),
        PIIMiddleware(
            "national_id",
            strategy="redact",
            detector=detect_national_id,
            apply_to_input=True,
            apply_to_output=True,
            apply_to_tool_results=True,
        ),
    ])
    pii_middleware.extend([
        PIIMiddleware(
            pii_type,
            strategy="block",
            detector=detector,
            apply_to_input=True,
            apply_to_output=True,
            apply_to_tool_results=True,
        )
        for pii_type, detector in (
            ("api_key", detect_api_key),
            ("bearer_token", detect_bearer_token),
            ("jwt", detect_jwt),
            ("private_key", detect_private_key),
        )
    ])
    summarization = SummarizationMiddleware(
        summary_model or model,
        trigger=("tokens", summary_trigger_tokens),
        keep=("tokens", summary_keep_tokens),
    )
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
        middleware=[*pii_middleware, summarization, context_editing, call_limit],
        context_schema=AgentRuntimeContext,
        checkpointer=checkpointer,
        name="news_agent",
    )
