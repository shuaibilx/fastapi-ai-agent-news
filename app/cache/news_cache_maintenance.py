"""Controlled cache invalidation for imports and direct SQL maintenance."""

import argparse
import asyncio
from collections.abc import Iterable

from app.cache.news_cache import NewsCache, get_news_cache


async def invalidate_news_cache(
    cache: NewsCache,
    *,
    category_ids: Iterable[int],
    include_categories: bool = False,
) -> bool:
    ids = set(category_ids)
    if ids and await cache.invalidate_news_categories(ids) is None:
        return False
    if include_categories and await cache.invalidate_categories() is None:
        return False
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="失效指定新闻分类及分类列表缓存")
    parser.add_argument("--category-id", type=int, action="append", default=[])
    parser.add_argument("--include-categories", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    if not args.category_id and not args.include_categories:
        raise SystemExit("至少提供一个 --category-id 或 --include-categories")
    success = await invalidate_news_cache(
        get_news_cache(),
        category_ids=args.category_id,
        include_categories=args.include_categories,
    )
    if not success:
        raise SystemExit("新闻缓存失效失败，请在 Redis 恢复后重试")
    print("新闻缓存 generation 已更新")


if __name__ == "__main__":
    asyncio.run(main())
