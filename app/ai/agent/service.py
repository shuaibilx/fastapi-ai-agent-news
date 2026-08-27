"""Application orchestration for the authenticated news agent."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from app.ai.agent.memory import (
    ConversationTurn,
    TokenBudgetPolicy,
    normalize_conversation_id,
)
from app.ai.agent.memory_store import ConversationMemoryStore, MemoryStatus
from app.ai.agent.results import AgentCitation, AgentToolSummary, collect_tool_metadata
from app.ai.agent.tools import AgentReadPort, AgentRuntimeContext


class AgentProviderUnavailable(Exception):
    """Raised when the model or a core agent dependency cannot complete a run."""


class AgentExecutionLimitExceeded(Exception):
    """Raised when the agent exceeds its bounded execution loop."""


class AgentRunner(Protocol):
    async def ainvoke(
        self,
        payload: dict[str, Any],
        *,
        context: AgentRuntimeContext,
        config: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AgentResult:
    answer: str
    conversation_id: str
    citations: list[AgentCitation]
    tool_calls: list[AgentToolSummary]
    memory_status: MemoryStatus


class AgentService:
    def __init__(
        self,
        *,
        runner: AgentRunner,
        memory_store: ConversationMemoryStore,
        budget_policy: TokenBudgetPolicy,
        max_iterations: int,
        retrieval_limit: int,
        page_size_limit: int,
        tool_result_max_tokens: int,
    ):
        self._runner = runner
        self._memory_store = memory_store
        self._budget_policy = budget_policy
        self._max_iterations = max_iterations
        self._retrieval_limit = retrieval_limit
        self._page_size_limit = page_size_limit
        self._tool_result_max_tokens = tool_result_max_tokens

    async def ask(
        self,
        *,
        user_id: int,
        message: str,
        conversation_id: str | None,
        reader: AgentReadPort,
    ) -> AgentResult:
        normalized_message = message.strip()
        conversation_id = normalize_conversation_id(conversation_id)
        loaded = await self._memory_store.load(user_id, conversation_id)
        history = self._budget_policy.select_history(
            loaded.turns,
            current_message=normalized_message,
        )

        messages: list[Any] = []
        for turn in history:
            messages.append(HumanMessage(content=turn.user_message))
            messages.append(AIMessage(content=turn.assistant_message))
        messages.append(HumanMessage(content=normalized_message))

        runtime_context = AgentRuntimeContext(
            user_id=user_id,
            reader=reader,
            retrieval_limit=self._retrieval_limit,
            page_size_limit=self._page_size_limit,
            tool_result_max_tokens=self._tool_result_max_tokens,
        )
        try:
            output = await self._runner.ainvoke(
                {"messages": messages},
                context=runtime_context,
                config={"recursion_limit": self._max_iterations * 2 + 3},
            )
        except (GraphRecursionError, ModelCallLimitExceededError) as exc:
            raise AgentExecutionLimitExceeded("Agent 超出允许的执行轮次") from exc
        except Exception as exc:
            raise AgentProviderUnavailable("Agent 服务暂时不可用") from exc

        output_messages = output.get("messages") or []
        final_message = next(
            (
                item for item in reversed(output_messages)
                if isinstance(item, AIMessage) and isinstance(item.content, str) and item.content.strip()
            ),
            None,
        )
        if final_message is None:
            raise AgentProviderUnavailable("模型未返回可用回答")

        answer = final_message.content.strip()
        citations, tool_calls = collect_tool_metadata(output_messages)
        append_status = await self._memory_store.append(
            user_id,
            conversation_id,
            ConversationTurn(
                user_message=normalized_message,
                assistant_message=answer,
                completed_at=datetime.now(timezone.utc).isoformat(),
            ),
        )
        memory_status = (
            MemoryStatus.UNAVAILABLE
            if MemoryStatus.UNAVAILABLE in {loaded.status, append_status}
            else loaded.status
        )
        return AgentResult(
            answer=answer,
            conversation_id=conversation_id,
            citations=citations,
            tool_calls=tool_calls,
            memory_status=memory_status,
        )
