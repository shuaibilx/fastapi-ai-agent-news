from config.db_config import get_db
from crud.favorite import is_news_favorite, add_news_favorite, remove_news_favorite, get_news_favorite, \
    remove_all_favorite
from fastapi import APIRouter, Query, HTTPException
from fastapi.params import Depends
from schemas.favorite import FavoriteCheckResponse, FavoriteAddRequest, FavoriteListResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from models.users import User
from utils.auth import get_current_user
from utils.response import success_response

router = APIRouter(prefix="/api/favorite", tags=["favorite"])


@router.get("/check")
async def check_favorite(news_id: int = Query(..., alias="newsId"),
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    is_favorite = await is_news_favorite(db, user.id, news_id)
    return success_response(message="检查收藏状态成功", data=FavoriteCheckResponse(isFavorite=is_favorite))


@router.post("/add")
# async def add_favorite(data: int = Query(..., alias="newsId"),
async def add_favorite(data: FavoriteAddRequest, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    favorite = await add_news_favorite(data.news_id, user.id, db)

    return success_response(message="添加收藏成功", data=favorite)


@router.delete("/remove")
async def remove_favorite(news_id: int = Query(..., alias="newsId"), user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    res = await remove_news_favorite(news_id, user.id, db)
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="收藏记录不存在")
    return success_response(message="取消收藏成功")


@router.get("/list")
async def get_favorite_list(
        page: int = Query(1, ge=1),
        page_size: int = Query(10, ge=1, le=100, alias="page_size"),
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    rows, total = await get_news_favorite(db, user.id, page, page_size)
    favorite_list = [{
        **news.__dict__,
        "favorite_time": favorite_time,
        "favorite_id": favorite_id,
    } for news, favorite_time, favorite_id in rows]
    has_more = total > page * page_size
    data = FavoriteListResponse(list=favorite_list, total=total, hasMore=has_more)
    return success_response(message="获取收藏列表成功", data=data)


@router.delete("/clear")
async def clear_favorite(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    count = await remove_all_favorite(db, user.id)
    return success_response(message=f"清空了{count}条收藏")
