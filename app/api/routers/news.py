from app.core.database import get_db
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import news

# 把每个业务功能的接口拆分到独立的文件中，再统一挂再到主应用中
# 模块化路由  ：  1. 模块化目录结构  2. 编写独立路由模块  3. 在 main.py 中挂载路由
# 创建 APIRouter 实例s

router = APIRouter(prefix="/api/news", tags=["news"])


# 获取数据库里面的分类数据  ——> 定义模型类  ——>  封装查询数据的方法

# 获取新闻类别
@router.get("/categories")
async def get_categories(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    categories = await news.get_categories(db, skip, limit)
    return {
        "code": 200,
        "data": categories,
        "message": "获取新闻分类成功",
    }


# 获取新闻列表
@router.get("/list")
async def get_news_list(categories_id: int = Query(..., alias="categoryId"),
                        page: int = 1,
                        page_size: int = Query(10, alias="pageSize", le=100),
                        db: AsyncSession = Depends(get_db)):
    news_page = await news.get_news_page(db, categories_id, page, page_size)
    return {
        "code": 200,
        "message": "获取新闻列表成功",
        "data": {
            "total": news_page.total,
            "list": news_page.list,
            "hasMore": news_page.has_more,
        }
    }


# 获取新闻详情
@router.get("/detail")
async def get_news_detail(news_id: int = Query(..., alias="id"), db: AsyncSession = Depends(get_db)):
    # 需求 ： 获取新闻详情 + (浏览量+1) + 相关推荐
    news_detail = await news.get_news_detail(db, news_id)
    if not news_detail:
        raise HTTPException(status_code=404, detail="新闻不存在")

    views_res = await news.increase_news_views(db, news_id)
    if not views_res:
        raise HTTPException(status_code=404, detail="浏览量增加失败")

    related_news = await news.get_related_news(db, news_detail.category_id, news_detail.id, )

    return {
        "code": 200,
        "message": "success",
        "data": {
            "id": news_detail.id,
            "title": news_detail.title,
            "content": news_detail.content,
            "image": news_detail.image,
            "author": news_detail.author,
            "publishTime": news_detail.publish_time,
            "categoryId": news_detail.category_id,
            "views": news_detail.views,
            "relatedNews": related_news
        }
    }
