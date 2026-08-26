"""Provider boundary for AI-generated news summaries."""

from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek


class SummaryProviderUnavailable(Exception):
    """Raised when a provider cannot return a usable summary."""


class SummaryGateway(Protocol):
    async def summarize(self, title: str, content: str) -> str: ...


def validate_summary_text(value: object, max_characters: int) -> str:
    if not isinstance(value, str):
        raise SummaryProviderUnavailable("模型未返回文本摘要")
    summary = value.strip()
    if not summary:
        raise SummaryProviderUnavailable("模型返回了空摘要")
    if len(summary) > max_characters:
        raise SummaryProviderUnavailable("模型返回的摘要超过允许长度")
    return summary


class LangChainSummaryGateway:
    """OpenAI-compatible LangChain gateway used by the summary service."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        max_characters: int,
    ):
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_characters = max_characters

    async def summarize(self, title: str, content: str) -> str:
        if not self._api_key or not self._model:
            raise SummaryProviderUnavailable("未配置模型服务")

        model = ChatDeepSeek(
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            timeout=self._timeout_seconds,
            temperature=0,
        )
        messages = [
            SystemMessage(
                content=(
                    "你是一名严谨的中文新闻编辑。仅根据用户提供的新闻标题和正文，"
                    f"用不超过 {self._max_characters} 个汉字的连贯中文概述关键事实。"
                    "不要添加来源中不存在的事实，不要使用项目符号。"
                )
            ),
            HumanMessage(content=f"新闻标题：{title}\n\n新闻正文：{content}"),
        ]
        try:
            response = await model.ainvoke(messages)
        except Exception as exc:
            raise SummaryProviderUnavailable("模型服务暂时不可用") from exc
        return validate_summary_text(response.content, self._max_characters)

