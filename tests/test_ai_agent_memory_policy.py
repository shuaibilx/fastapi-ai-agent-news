from uuid import UUID

import pytest

from app.ai.agent.memory import (
    ContextWindowExceeded,
    ConversationTurn,
    TokenBudgetPolicy,
    normalize_conversation_id,
)


def make_turn(index: int, *, user_size: int = 1, assistant_size: int = 1) -> ConversationTurn:
    return ConversationTurn(
        user_message=str(index) * user_size,
        assistant_message=str(index) * assistant_size,
        completed_at=f"2026-08-27T00:00:0{index}+00:00",
    )


def test_missing_conversation_id_creates_an_unpredictable_uuid():
    first = normalize_conversation_id(None)
    second = normalize_conversation_id(None)

    assert UUID(first).version == 4
    assert UUID(second).version == 4
    assert first != second


def test_invalid_conversation_id_is_rejected():
    with pytest.raises(ValueError, match="conversationId"):
        normalize_conversation_id("not-a-uuid")


def test_history_policy_keeps_only_the_latest_five_complete_turns():
    policy = TokenBudgetPolicy(
        max_rounds=5,
        max_history_tokens=100,
        max_input_tokens=200,
        count_tokens=len,
    )

    selected = policy.select_history(
        [make_turn(index) for index in range(1, 7)],
        current_message="现在的问题",
    )

    assert [turn.user_message for turn in selected] == ["2", "3", "4", "5", "6"]
    assert all(turn.assistant_message for turn in selected)


def test_history_policy_removes_oldest_whole_pairs_to_fit_token_budget():
    policy = TokenBudgetPolicy(
        max_rounds=5,
        max_history_tokens=8,
        max_input_tokens=20,
        count_tokens=len,
    )

    selected = policy.select_history(
        [make_turn(1, user_size=2, assistant_size=2),
         make_turn(2, user_size=2, assistant_size=2),
         make_turn(3, user_size=2, assistant_size=2)],
        current_message="问",
    )

    assert [(turn.user_message, turn.assistant_message) for turn in selected] == [
        ("22", "22"),
        ("33", "33"),
    ]


def test_current_message_is_never_silently_truncated_when_it_exceeds_total_budget():
    policy = TokenBudgetPolicy(
        max_rounds=5,
        max_history_tokens=8,
        max_input_tokens=5,
        count_tokens=len,
    )

    with pytest.raises(ContextWindowExceeded, match="当前消息"):
        policy.select_history([make_turn(1)], current_message="123456", base_tokens=0)
