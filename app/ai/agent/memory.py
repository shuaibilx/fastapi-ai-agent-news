"""Bounded, user-scoped short-term memory primitives for the news agent."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4


class ContextWindowExceeded(ValueError):
    """Raised when the current request cannot fit the configured input budget."""


@dataclass(frozen=True)
class ConversationTurn:
    user_message: str
    assistant_message: str
    completed_at: str


def normalize_conversation_id(value: str | None) -> str:
    if value is None:
        return str(uuid4())
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("conversationId 必须是有效的 UUID") from exc


def approximate_token_count(text: str) -> int:
    """Conservatively estimate tokens for mixed Chinese and Latin text."""
    return len(text)


class TokenBudgetPolicy:
    def __init__(
        self,
        *,
        max_rounds: int,
        max_history_tokens: int,
        max_input_tokens: int,
        count_tokens: Callable[[str], int] = approximate_token_count,
    ):
        self.max_rounds = max_rounds
        self.max_history_tokens = max_history_tokens
        self.max_input_tokens = max_input_tokens
        self._count_tokens = count_tokens

    def select_history(
        self,
        turns: Sequence[ConversationTurn],
        *,
        current_message: str,
        base_tokens: int = 0,
    ) -> list[ConversationTurn]:
        current_tokens = self._count_tokens(current_message)
        available_input = self.max_input_tokens - base_tokens
        if current_tokens > available_input:
            raise ContextWindowExceeded("当前消息超过 Agent 输入上下文限制")

        history_budget = min(
            self.max_history_tokens,
            max(0, available_input - current_tokens),
        )
        selected_newest_first: list[ConversationTurn] = []
        used_tokens = 0

        for turn in reversed(turns[-self.max_rounds :]):
            turn_tokens = (
                self._count_tokens(turn.user_message)
                + self._count_tokens(turn.assistant_message)
            )
            if used_tokens + turn_tokens > history_budget:
                break
            selected_newest_first.append(turn)
            used_tokens += turn_tokens

        return list(reversed(selected_newest_first))
