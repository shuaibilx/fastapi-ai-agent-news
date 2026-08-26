from cache.news_cache import get_cached_categories, set_cache_categories, get_cached_news_list, set_cache_news_list
from fastapi.encoders import jsonable_encoder
from schemas.base import NewsItemBase
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.news import Category, News


# 1. 获取新闻分类
async def get_categories(db: AsyncSession, skip: int = 0, limit: int = 100):
    # 先尝试从缓存中 获取数据
    cached_categories = await get_cached_categories()
    if cached_categories is not None:
        return cached_categories

    stmt = select(Category).offset(skip).limit(limit)
    results = await db.execute(stmt)  # SQLAlchemy 的 Result 对象
    categories = results.scalars().all()  # 提取 ORM 对象

    # 写入缓存
    if categories:
        categories = jsonable_encoder(categories)
        await set_cache_categories(categories)

    return categories


# 2.1 获取对应新闻类别的新闻列表
async def get_news_list(db: AsyncSession, category_id: int, skip: int = 0, limit: int = 10):
    # 先尝试从缓存获取新闻列表
    page = skip // limit + 1
    cached_list = await get_cached_news_list(category_id, page, limit)  # 缓存数据json
    if cached_list is not None:
        return [News(**item) for item in cached_list]  # 要的是 ORM 模型类:List[News]

    # 分页规则
    stmt = select(News).where(News.category_id == category_id).offset(skip).limit(limit)
    results = await db.execute(stmt)
    news_list = results.scalars().all()

    # 写入缓存
    if news_list:
        # 先把 ORM 数据转换成字典才能写入缓存
        # ORM 转成 Pydantic，再转成字典
        # by_alias = False 不使用别名。保存 Python 风格，因为 Redis 数据是给后端用的
        # NewsItemBase.model_validate(item):把 ORM对象 item 转成Pydantic模型类 NewsItemBase
        # model_dump : Pydantic -> Dict
        news_data = [NewsItemBase.model_validate(item).model_dump(mode="json", by_alias=False)

                     for item in news_list]  # List[Dict]
        await set_cache_news_list(category_id, page, limit, news_data)
    return news_list


# 2.2 获取对应类别的新闻数量
async def get_news_count(db: AsyncSession, category_id: int):
    #  条件1：news表中id为非空的行数  条件2：category_id为指定id
    stmt = select(func.count(News.id)).where(News.category_id == category_id)
    result = await db.execute(stmt)
    return result.scalar_one()


# 3. 查询新闻详情
async def get_news_detail(db: AsyncSession, news_id: int):
    stmt = select(News).where(News.id == news_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()  # 返回完整的数据表 news 的字段


# 4. 浏览量 +1
async def increase_news_views(db: AsyncSession, news_id: int):
    # update(News)：指定要更新的ORM模型
    # .where(News.id == news_id) ： 限定更新条件
    # .values(views=News.views + 1) ： 设置更新表达式：列自身 + 1
    stmt = update(News).where(News.id == news_id).values(views=News.views + 1)
    result = await db.execute(stmt)
    await db.commit()

    # 更新 -》 检查数据库是否真的命中了数据 -》 命中了返回True
    return result.rowcount > 0


# 5. 获取相关新闻
async def get_related_news(db: AsyncSession, category_id: int, id: int, limit: int = 5):
    stmt = (select(News).
            where(News.category_id == category_id, News.id != id).
            limit(limit).
            order_by(News.views.desc(),
                     # 默认是升序，  desc() 是降序
                     News.publish_time.desc()))
    result = await db.execute(stmt)
    related_news = result.scalars().all()
    return [
        {"id": news_detail.id,
         "title": news_detail.title,
         "content": news_detail.content,
         "image": news_detail.image,
         "author": news_detail.author,
         "publishTime": news_detail.publish_time,
         "categoryId": news_detail.category_id,
         "views": news_detail.views}
        for news_detail in related_news
    ]
