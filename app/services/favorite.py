from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.favorite import Favorite
from app.models.news import News


# 检查是否收藏
async def is_news_favorite(
        db: AsyncSession,
        user_id: int,
        news_id: int
):
    query = select(Favorite).where(Favorite.user_id == user_id, Favorite.news_id == news_id)
    res = await db.execute(query)
    # 是否有收藏记录
    return res.scalar_one_or_none() is not None


# 添加收藏
async def add_news_favorite(news_id: int, user_id: int, db: AsyncSession):
    favorite = Favorite(news_id=news_id, user_id=user_id)  # 构建Favorite 的实例对象
    db.add(favorite)
    await db.commit()
    await db.refresh(favorite)
    return favorite


# 移出收藏
async def remove_news_favorite(news_id: int, user_id: int, db: AsyncSession):
    stmt = delete(Favorite).where(Favorite.news_id == news_id, Favorite.user_id == user_id)
    res = await db.execute(stmt)
    await db.commit()
    return res.rowcount > 0


# 获取收藏列表： 获取某个用户的收藏列表 + 分页功能
async def get_news_favorite(db: AsyncSession, user_id: int, page: int = 1, page_size: int = 10):
    # 总量 + 收藏的新闻列表
    count_query = select(func.count()).where(Favorite.user_id == user_id)
    count_res = await db.execute(count_query)
    total = count_res.scalar_one()

    # 获取收藏列表 - 联表查询 join() + 收藏时间排序 + 分页
    # select(查询主体模型类,字段别名).join(联合查询模型类,联合查询条件).where().order_by().offset().limit()
    # 别名： Favorite.created_at.label("favorite_time")
    offset = (page - 1) * page_size
    query = (
        select(  # select()里面选择什么，决定返回的每一行 row 中包含什么内容
            News,
            Favorite.created_at.label("favorite_time"),
            Favorite.id.label("favorite_id")
        )
        .join(
            Favorite,
            Favorite.news_id == News.id
        )
        .where(
            user_id == Favorite.user_id
        )
        .order_by(
            Favorite.created_at.desc()
        )
        .offset(offset)
        .limit(page_size)
    )
    res = await db.execute(query)
    rows = res.all()  # rows: list[Row[tuple[News, datetime, int]]]
    return rows, total
    # [
    #   (新闻对象, 收藏时间, 收藏id)
    # ]


# 返回示例
# [
#     (
#         <News(
#             id=55,
#             title="科技新闻标题",
#             description="新闻简介",
#             content="新闻正文内容",
#             image="https://example.com/image.jpg",
#             author="张三",
#             category_id=2,
#             views=128,
#             publish_time=datetime.datetime(2026, 8, 20, 10, 30, 0),
#             created_at=datetime.datetime(2026, 8, 20, 10, 30, 0),
#             updated_at=datetime.datetime(2026, 8, 20, 10, 30, 0)
#         )>,
#         datetime.datetime(2026, 8, 20, 12, 40, 27),
#         10
#     ),
#     (
#         <News(
#             id=54,
#             title="财经新闻标题",
#             description="财经新闻简介",
#             content="财经新闻正文",
#             image="https://example.com/image2.jpg",
#             author="李四",
#             category_id=3,
#             views=256,
#             publish_time=datetime.datetime(2026, 8, 20, 9, 20, 0),
#             created_at=datetime.datetime(2026, 8, 20, 9, 20, 0),
#             updated_at=datetime.datetime(2026, 8, 20, 9, 20, 0)
#         )>,
#         datetime.datetime(2026, 8, 20, 12, 35, 12),
#         9
#     )
# ]

# 清空收藏列表 ： 当前用户的收藏列表
async def remove_all_favorite(db: AsyncSession, user_id: int):
    stmt = delete(Favorite).where(Favorite.user_id == user_id)
    res = await db.execute(stmt)
    await db.commit()
    return res.rowcount or 0
