"""Lazy provider-backed LangChain runner for the news agent."""

from typing import Any

from langchain_deepseek import ChatDeepSeek

from app.ai.agent.factory import build_news_agent
from app.ai.agent.tools import AgentRuntimeContext


class LangChainNewsAgentRunner:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        max_iterations: int,
        max_input_tokens: int,
        tool_result_max_tokens: int,
    ):
        self._base_url = base_url
        self._api_key = api_key
        self._model_name = model
        self._timeout_seconds = timeout_seconds
        self._max_iterations = max_iterations
        self._max_input_tokens = max_input_tokens
        self._tool_result_max_tokens = tool_result_max_tokens
        self._agent = None

    def _get_agent(self):
        if not self._api_key or not self._model_name:
            raise RuntimeError("未配置模型服务")
        if self._agent is None:
            model = ChatDeepSeek(
                base_url=self._base_url,
                api_key=self._api_key,
                model=self._model_name,
                timeout=self._timeout_seconds,
                temperature=0,
            )
            self._agent = build_news_agent(
                model=model,
                max_iterations=self._max_iterations,
                max_input_tokens=self._max_input_tokens,
                tool_result_max_tokens=self._tool_result_max_tokens,
            )
        return self._agent

    async def ainvoke(
        self,
        payload: dict[str, Any],
        *,
        context: AgentRuntimeContext,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._get_agent().ainvoke(payload, context=context, config=config)
