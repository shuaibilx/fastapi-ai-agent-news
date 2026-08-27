"""Application orchestration for the authenticated news agent."""

from dataclasses import dataclass
from typing import Any, Protocol

from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.pii import PIIDetectionError
from langchain.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from app.ai.agent.memory import normalize_conversation_id
from app.ai.agent.memory_runtime import AgentMemorySession, CheckpointerMemoryRuntime
from app.ai.agent.memory_store import MemoryStatus
from app.ai.agent.results import AgentCitation, AgentToolSummary, collect_tool_metadata
from app.ai.agent.safety import SensitiveDataBlocked, sanitize_text
from app.ai.agent.tools import AgentReadPort, AgentRuntimeContext


_MIN_GRAPH_RECURSION_LIMIT = 100
_GRAPH_STEPS_PER_MODEL_CALL = 12
_GRAPH_STEP_OVERHEAD = 20


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
        memory_runtime: CheckpointerMemoryRuntime,
        max_iterations: int,
        retrieval_limit: int,
        page_size_limit: int,
        tool_result_max_tokens: int,
    ):
        self._runner = runner
        self._memory_runtime = memory_runtime
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

        return await self._ask_with_checkpointer(
            user_id=user_id,
            message=normalized_message,
            conversation_id=conversation_id,
            reader=reader,
        )

    async def _ask_with_checkpointer(
        self,
        *,
        user_id: int,
        message: str,
        conversation_id: str,
        reader: AgentReadPort,
    ) -> AgentResult:
        session: AgentMemorySession = await self._memory_runtime.prepare(user_id, conversation_id)
        safe_message = sanitize_text(message)
        runtime_context = AgentRuntimeContext(
            user_id=user_id,
            reader=reader,
            retrieval_limit=self._retrieval_limit,
            page_size_limit=self._page_size_limit,
            tool_result_max_tokens=self._tool_result_max_tokens,
        )
        # LangGraph counts middleware and tool nodes as graph steps. ModelCallLimitMiddleware
        # remains the hard bound for model invocations; this limit only leaves room for orchestration.
        recursion_limit = max(
            _MIN_GRAPH_RECURSION_LIMIT,
            self._max_iterations * _GRAPH_STEPS_PER_MODEL_CALL + _GRAPH_STEP_OVERHEAD,
        )
        config = {"recursion_limit": recursion_limit, **session.config}
        try:
            output = await self._runner.ainvoke(
                {"messages": [HumanMessage(content=safe_message)]},
                context=runtime_context,
                config=config,
            )
        except (SensitiveDataBlocked, PIIDetectionError) as exc:
            if isinstance(exc, PIIDetectionError):
                raise SensitiveDataBlocked(exc.pii_type) from exc
            raise
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

        try:
            answer = sanitize_text(final_message.content.strip())
            citations, tool_calls = collect_tool_metadata(output_messages)
        except SensitiveDataBlocked:
            raise

        memory_status = session.status
        if memory_status is not MemoryStatus.UNAVAILABLE:
            memory_status = await self._memory_runtime.verify_saved(session)
        return AgentResult(
            answer=answer,
            conversation_id=conversation_id,
            citations=citations,
            tool_calls=tool_calls,
            memory_status=memory_status,
        )
