from enum import Enum
from typing import Annotated

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
