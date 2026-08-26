from datetime import datetime

from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.history import History
from app.models.news import News


async def add_history(db: AsyncSession, user_id: int, news_id: int):
    stmt = History(user_id=user_id, news_id=news_id, view_time=datetime.now())
    db.add(stmt)
    await db.commit()
    await db.refresh(stmt)
    return stmt


async def get_history_list(db: AsyncSession, user_id: int, page: int = 1, page_size: int = 10):
    count_query = select(func.count(History.id)).where(History.user_id == user_id)
    count_res = await db.execute(count_query)  # 数据库操作是异步
    total = count_res.scalar_one()

    offset = (page - 1) * page_size

    stmt = (select(News, History.view_time.label("view_time"), History.id.label("history_id")).join(History,
                                                                                                    History.news_id == News.id).where(
        History.user_id == user_id).
            order_by(History.view_time.desc()).offset(
        offset).limit(page_size))
    res = await db.execute(stmt)
    return res.all(), total


async def delete_history(db: AsyncSession, user_id: int, news_id: int):
    stmt = delete(History).where(History.user_id == user_id).where(History.news_id == news_id)  # sql语句对象
    res = await db.execute(stmt)
    await db.commit()
    # await db.refresh() 只能针对ORM对象
    return res.rowcount > 0


async def claer_history(db: AsyncSession, user_id: int):
    stmt = delete(History).where(History.user_id == user_id)
    res = await db.execute(stmt)
    await db.commit()
    # # 返回一个删除的数量
    return res.rowcount or 0
