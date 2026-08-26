from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict
from schemas.base import NewsItemBase


class FavoriteCheckResponse(BaseModel):
    # 允许 Pydantic 模型既可以用字段名赋值，也可以用 alias 别名赋值
    model_config = ConfigDict(populate_by_name=True)
    is_favorite: bool = Field(..., alias="isFavorite")


class FavoriteAddRequest(BaseModel):
    news_id: int = Field(..., alias="newsId")


# 规划两个类 ： 1. 新闻模型类 2. 收藏的模型类
class FavoriteNewsItemsResponse(NewsItemBase):
    favorite_id: int = Field(..., alias="favoriteId")
    favorite_time: datetime = Field(alias="favoriteTime")
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# 收藏列表响应的模型类
class FavoriteListResponse(BaseModel):
    list: list[FavoriteNewsItemsResponse]
    total: int
    has_more: bool = Field(..., alias="hasMore")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
