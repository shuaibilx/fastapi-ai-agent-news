from dataclasses import dataclass

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.news_cache import NewsCache, get_news_cache
from app.models.news import Category, News
from app.schemas.base import NewsItemBase
from app.schemas.news import NewsPageCachePayload


@dataclass(frozen=True)
class NewsPage:
    list: list[News]
    total: int
    has_more: bool


def _cache_payload_to_page(payload: NewsPageCachePayload) -> NewsPage:
    return NewsPage(
        list=[News(**item.model_dump()) for item in payload.list],
        total=payload.total,
        has_more=payload.has_more,
    )


def _page_to_cache_payload(page: NewsPage) -> NewsPageCachePayload:
    return NewsPageCachePayload(
        list=[NewsItemBase.model_validate(item) for item in page.list],
        total=page.total,
        hasMore=page.has_more,
    )


async def get_categories(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    *,
    cache: NewsCache | None = None,
):
    cache = cache or get_news_cache()
    generation = await cache.categories_generation()
    if generation is not None:
        cached = await cache.get_categories(generation, skip, limit)
        if cached is not None:
            return cached

    result = await db.execute(
        select(Category).order_by(Category.sort_order.asc(), Category.id.asc()).offset(skip).limit(limit)
    )
    categories = jsonable_encoder(result.scalars().all())
    if generation is not None:
        await cache.set_categories(generation, skip, limit, categories)
    return categories


async def get_news_page(
    db: AsyncSession,
    category_id: int,
    page: int = 1,
    page_size: int = 10,
    *,
    cache: NewsCache | None = None,
) -> NewsPage:
    cache = cache or get_news_cache()
    generation = await cache.news_generation(category_id)
    if generation is not None:
        cached = await cache.get_news_page(category_id, generation, page, page_size)
        if cached is not None:
            return _cache_payload_to_page(cached)

    offset = (page - 1) * page_size
    rows = await db.execute(
        select(News)
        .where(News.category_id == category_id)
        .order_by(News.publish_time.desc(), News.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    news_list = list(rows.scalars().all())
    total_result = await db.execute(
        select(func.count(News.id)).where(News.category_id == category_id)
    )
    total = total_result.scalar_one()
    result = NewsPage(
        list=news_list,
        total=total,
        has_more=offset + len(news_list) < total,
    )
    if generation is not None:
        await cache.set_news_page(
            category_id,
            generation,
            page,
            page_size,
            _page_to_cache_payload(result),
        )
    return result


async def get_news_list(db: AsyncSession, category_id: int, skip: int = 0, limit: int = 10):
    """Backward-compatible list-only adapter for internal callers."""
    page = skip // limit + 1
    return (await get_news_page(db, category_id, page, limit)).list


async def get_news_count(db: AsyncSession, category_id: int):
    result = await db.execute(select(func.count(News.id)).where(News.category_id == category_id))
    return result.scalar_one()


async def get_news_detail(db: AsyncSession, news_id: int):
    result = await db.execute(select(News).where(News.id == news_id))
    return result.scalar_one_or_none()


async def increase_news_views(db: AsyncSession, news_id: int):
    """Views are intentionally eventually consistent in cached news lists."""
    result = await db.execute(
        update(News).where(News.id == news_id).values(views=News.views + 1)
    )
    await db.commit()
    return result.rowcount > 0


async def get_related_news(db: AsyncSession, category_id: int, id: int, limit: int = 5):
    result = await db.execute(
        select(News)
        .where(News.category_id == category_id, News.id != id)
        .order_by(News.views.desc(), News.publish_time.desc())
        .limit(limit)
    )
    related_news = result.scalars().all()
    return [
        {
            "id": news_detail.id,
            "title": news_detail.title,
            "content": news_detail.content,
            "image": news_detail.image,
            "author": news_detail.author,
            "publishTime": news_detail.publish_time,
            "categoryId": news_detail.category_id,
            "views": news_detail.views,
        }
        for news_detail in related_news
    ]
