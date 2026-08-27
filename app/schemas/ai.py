from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class SummaryCacheStatus(str, Enum):
    HIT = "hit"
    MISS = "miss"
    UNAVAILABLE = "unavailable"


class NewsSummaryResponse(BaseModel):
    news_id: int = Field(alias="newsId")
    summary: str
    cache_status: SummaryCacheStatus = Field(alias="cacheStatus")

    model_config = ConfigDict(populate_by_name=True)


class QaCitationResponse(BaseModel):
    news_id: int = Field(alias="newsId")
    title: str
    excerpt: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class QaRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class QaResponse(BaseModel):
    answer: str
    citations: list[QaCitationResponse]


class AgentRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    conversation_id: UUID | None = Field(default=None, alias="conversationId")

    model_config = ConfigDict(populate_by_name=True)


class AgentToolCallResponse(BaseModel):
    name: str
    status: str
    summary: str


class AgentResponse(BaseModel):
    answer: str
    conversation_id: UUID = Field(alias="conversationId")
    citations: list[QaCitationResponse]
    tool_calls: list[AgentToolCallResponse] = Field(alias="toolCalls")
    memory_status: str = Field(alias="memoryStatus")

    model_config = ConfigDict(populate_by_name=True)
