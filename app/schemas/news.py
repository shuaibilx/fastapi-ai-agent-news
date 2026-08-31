from typing import List

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import NewsItemBase


class NewsPageCachePayload(BaseModel):
    """The complete, serializable snapshot stored for one news page."""

    list: List[NewsItemBase]
    total: int = Field(ge=0)
    has_more: bool = Field(alias="hasMore")

    model_config = ConfigDict(populate_by_name=True)
