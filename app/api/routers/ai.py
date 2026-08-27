from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent import (
    AgentExecutionLimitExceeded,
    AgentProviderUnavailable,
    AgentService,
    ContextWindowExceeded,
    ConversationMemoryStore,
    LangChainNewsAgentRunner,
    SqlAgentReader,
    TokenBudgetPolicy,
)
from app.ai.rag import (
    LangChainQaGateway,
    NewsRetrievalService,
    QaProviderUnavailable,
    QaService,
)
from app.ai.summarization import (
    LangChainSummaryGateway,
    NewsSummaryService,
    SummaryCache,
    SummaryProviderUnavailable,
)
from app.core.auth import get_current_user
from app.core.cache import redis_client
from app.core.config import get_settings
from app.core.database import get_db
from app.core.responses import success_response
from app.models.users import User
from app.schemas.ai import (
    AgentRequest,
    AgentResponse,
    AgentToolCallResponse,
    NewsSummaryResponse,
    QaCitationResponse,
    QaRequest,
    QaResponse,
    SummaryCacheStatus,
)
from app.services import news


router = APIRouter(prefix="/api/ai", tags=["ai"])


def get_news_summary_service() -> NewsSummaryService:
    settings = get_settings()
    return NewsSummaryService(
        cache=SummaryCache(redis_client, ttl_seconds=settings.ai_summary_cache_ttl_seconds),
        gateway=LangChainSummaryGateway(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_characters=settings.ai_summary_max_characters,
        ),
    )


@router.post("/news/{news_id}/summary")
async def summarize_news(
    news_id: int,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    summary_service: NewsSummaryService = Depends(get_news_summary_service),
):
    article = await news.get_news_detail(db, news_id)
    if article is None:
        raise HTTPException(status_code=404, detail="新闻不存在")

    try:
        result = await summary_service.summarize(article.id, article.title, article.content)
    except SummaryProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="摘要服务暂时不可用") from exc

    response_data = NewsSummaryResponse(
        newsId=article.id,
        summary=result.summary,
        cacheStatus=SummaryCacheStatus(result.cache_status),
    )
    return success_response(message="获取新闻摘要成功", data=response_data)


class SqlNewsSearch:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def search_news(self, question: str, limit: int) -> list:
        from sqlalchemy import or_, select

        from app.models.news import News

        keywords = [kw for kw in question.replace("？", " ").replace("?", " ").split() if kw.strip()]
        filters = []
        for keyword in keywords[:3]:
            like = f"%{keyword}%"
            filters.append(or_(
                News.title.like(like),
                News.description.like(like),
                News.content.like(like),
            ))
        if not filters:
            return []
        stmt = select(News).where(or_(*filters)).order_by(News.views.desc()).limit(limit)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())


def get_qa_service(db: AsyncSession = Depends(get_db)) -> QaService:
    settings = get_settings()
    return QaService(
        retrieval=NewsRetrievalService(
            search_port=SqlNewsSearch(db),
            default_limit=settings.ai_qa_retrieval_limit,
        ),
        gateway=LangChainQaGateway(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
    )


def get_agent_service() -> AgentService:
    settings = get_settings()
    return AgentService(
        runner=LangChainNewsAgentRunner(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_iterations=settings.ai_agent_max_iterations,
            max_input_tokens=settings.ai_agent_input_max_tokens,
            tool_result_max_tokens=settings.ai_agent_tool_result_max_tokens,
        ),
        memory_store=ConversationMemoryStore(
            redis_client,
            ttl_seconds=settings.ai_agent_memory_ttl_seconds,
            max_rounds=settings.ai_agent_history_max_rounds,
        ),
        budget_policy=TokenBudgetPolicy(
            max_rounds=settings.ai_agent_history_max_rounds,
            max_history_tokens=settings.ai_agent_history_max_tokens,
            max_input_tokens=settings.ai_agent_input_max_tokens,
        ),
        max_iterations=settings.ai_agent_max_iterations,
        retrieval_limit=settings.ai_qa_retrieval_limit,
        page_size_limit=10,
        tool_result_max_tokens=settings.ai_agent_tool_result_max_tokens,
    )


@router.post("/qa")
async def ask_news_question(
    payload: QaRequest,
    _: User = Depends(get_current_user),
    qa_service: QaService = Depends(get_qa_service),
):
    try:
        result = await qa_service.ask(payload.question)
    except QaProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="问答服务暂时不可用") from exc

    response_data = QaResponse(
        answer=result.answer,
        citations=[
            QaCitationResponse(newsId=item.news_id, title=item.title, excerpt=item.excerpt)
            for item in result.citations
        ],
    )
    return success_response(message="获取新闻回答成功", data=response_data)


@router.post("/agent")
async def ask_news_agent(
    payload: AgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_service: AgentService = Depends(get_agent_service),
):
    settings = get_settings()
    reader = SqlAgentReader(
        db,
        NewsRetrievalService(
            search_port=SqlNewsSearch(db),
            default_limit=settings.ai_qa_retrieval_limit,
        ),
    )
    try:
        result = await agent_service.ask(
            user_id=user.id,
            message=payload.message,
            conversation_id=(
                str(payload.conversation_id) if payload.conversation_id is not None else None
            ),
            reader=reader,
        )
    except ContextWindowExceeded as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (AgentProviderUnavailable, AgentExecutionLimitExceeded) as exc:
        raise HTTPException(status_code=503, detail="Agent 服务暂时不可用") from exc

    response_data = AgentResponse(
        answer=result.answer,
        conversationId=result.conversation_id,
        citations=[
            QaCitationResponse(
                newsId=item.news_id,
                title=item.title,
                excerpt=item.excerpt,
            )
            for item in result.citations
        ],
        toolCalls=[
            AgentToolCallResponse(
                name=item.name,
                status=item.status,
                summary=item.summary,
            )
            for item in result.tool_calls
        ],
        memoryStatus=result.memory_status.value,
    )
    return success_response(message="获取 Agent 回答成功", data=response_data)
