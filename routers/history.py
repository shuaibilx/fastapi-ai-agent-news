from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.db_config import get_db
from crud import history
from crud.history import get_history_list
from models.users import User
from schemas.history import HistoryAddRequest, HistoryListResponse, HistoryNewsItemResponse
from utils.auth import get_current_user
from utils.response import success_response

router = APIRouter(prefix="/api/history", tags=["history"])


@router.post("/add")
async def add_history(data: HistoryAddRequest,
                      user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """
    添加历史记录
    """
    result = await history.add_history(db, user.id, data.news_id)
    return success_response(message="添加成功", data=result)


@router.get("/list")
async def list_history(page: int = Query(1, ge=1),
                       page_size: int = Query(10, ge=1, le=100, alias="pageSize"),
                       User=Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    rows, total = await get_history_list(db, User.id, page, page_size)  # 调用异步函数使用 await
    has_more = total > page * page_size
    history_list = [HistoryNewsItemResponse.model_validate(
        {
            **news.__dict__,
            "view_time": view_time,
            "history_id": history_id,
        }) for news, view_time, history_id in rows
    ]
    data = HistoryListResponse(list=history_list, total=total, hasMore=has_more)

    return success_response(message="获取浏览历史成功", data=data)


@router.delete("/delete/{history_id}")
async def delete_history(history_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    res = await history.delete_history(db, user.id, history_id)
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="历史记录不存在")
    return success_response(message="删除历史记录成功")


@router.delete("/clear")
async def clear_history(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    count = await history.claer_history(db, user.id)

    return success_response(message=f"清空{count}浏览历史成功")
