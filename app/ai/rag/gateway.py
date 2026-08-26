"""Provider boundary for grounded news question answering."""

from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek


class QaProviderUnavailable(Exception):
    """Raised when the model provider cannot return a grounded answer."""


class QaGateway(Protocol):
    async def answer(self, question: str, context: str) -> str: ...


class LangChainQaGateway:
    """OpenAI-compatible gateway constrained to the provided news context."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
    ):
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def answer(self, question: str, context: str) -> str:
        if not self._api_key or not self._model:
            raise QaProviderUnavailable("未配置模型服务")

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
                    "你是一名严谨的中文新闻问答助手。仅根据下方提供的新闻资料回答用户问题。"
                    "如果资料不足以回答问题，请明确说明无法回答，不要编造事实或引用不存在的来源。"
                )
            ),
            HumanMessage(content=f"新闻资料：\n{context}\n\n用户问题：{question}"),
        ]
        try:
            response = await model.ainvoke(messages)
        except Exception as exc:
            raise QaProviderUnavailable("问答服务暂时不可用") from exc
        answer = response.content
        if not answer or not str(answer).strip():
            raise QaProviderUnavailable("模型返回了空回答")
        return str(answer).strip()

