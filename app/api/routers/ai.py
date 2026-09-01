import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent import (
    AgentExecutionLimitExceeded,
    AgentProviderUnavailable,
    AgentService,
    CheckpointerMemoryRuntime,
    ContextWindowExceeded,
    LangChainNewsAgentRunner,
    SqlAgentReader,
    TokenBudgetPolicy,
)
from app.ai.agent.safety import SensitiveDataBlocked
from app.ai.embeddings import TeiEmbeddingClient
from app.ai.rag import (
    LangChainQaGateway,
    NewsRetrievalService,
    QaProviderUnavailable,
    QaService,
    RedisSemanticNewsSearch,
)
from app.ai.rag.vector_store import RedisNewsVectorStore
from app.ai.rag.chunking import BgeTokenCounter
from app.ai.rag.context import RetrievalContextBuilder
from app.ai.summarization import (
    LangChainSummaryGateway,
    NewsSummaryService,
    SummaryCache,
    SummaryProviderUnavailable,
)
from app.ai.streaming import SseEventEncoder, StreamEvent, iter_sse_events
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


@lru_cache(maxsize=4)
def get_bge_token_counter(tokenizer_path: str) -> BgeTokenCounter:
    return BgeTokenCounter(tokenizer_path)


def build_rag_context_builder() -> RetrievalContextBuilder:
    settings = get_settings()
    return RetrievalContextBuilder(
        token_counter=get_bge_token_counter(settings.embedding_tokenizer_path),
        max_tokens=settings.ai_qa_max_context_tokens,
    )


def sse_response(
    request: Request,
    events: AsyncIterator[StreamEvent],
    *,
    error_message: str,
) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        try:
            async for chunk in iter_sse_events(events, is_disconnected=request.is_disconnected):
                yield chunk
        except asyncio.CancelledError:
            raise
        except Exception:
            if not await request.is_disconnected():
                yield SseEventEncoder().encode(StreamEvent.error(error_message))

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


def build_news_retrieval(db: AsyncSession) -> NewsRetrievalService:
    """Build the single retrieval implementation shared by QA and the Agent."""
    settings = get_settings()
    return NewsRetrievalService(
        search_port=SqlNewsSearch(db),
        default_limit=settings.ai_qa_retrieval_limit,
        semantic_search=RedisSemanticNewsSearch(
            embedding_service=TeiEmbeddingClient(
                base_url=settings.embedding_base_url,
                timeout_seconds=settings.embedding_timeout_seconds,
                vector_dimensions=settings.ai_semantic_vector_dimensions,
            ),
            vector_store=RedisNewsVectorStore(
                redis_client=redis_client,
                index_alias=settings.ai_semantic_index_alias,
                index_prefix=settings.ai_semantic_index_prefix,
                key_prefix=settings.ai_semantic_chunk_key_prefix,
                vector_dimensions=settings.ai_semantic_vector_dimensions,
            ),
            minimum_score=settings.ai_semantic_score_threshold,
            candidate_chunk_limit=settings.ai_semantic_candidate_chunk_limit,
            max_chunks_per_news=settings.ai_semantic_max_chunks_per_news,
        ),
    )


def get_qa_service(db: AsyncSession = Depends(get_db)) -> QaService:
    settings = get_settings()
    return QaService(
        retrieval=build_news_retrieval(db),
        gateway=LangChainQaGateway(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
        context_builder=build_rag_context_builder(),
    )


def get_agent_service(request: Request) -> AgentService:
    settings = get_settings()
    checkpoint_manager = getattr(request.app.state, "agent_checkpoint_manager", None)
    checkpointer = checkpoint_manager.checkpointer if checkpoint_manager else None
    return AgentService(
        runner=LangChainNewsAgentRunner(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_iterations=settings.ai_agent_max_iterations,
            max_input_tokens=settings.ai_agent_input_max_tokens,
            tool_result_max_tokens=settings.ai_agent_tool_result_max_tokens,
            summary_trigger_tokens=settings.ai_agent_summary_trigger_tokens,
            summary_keep_tokens=settings.ai_agent_summary_keep_tokens,
            summary_model=settings.ai_agent_summary_model,
            checkpointer=checkpointer,
        ),
        memory_runtime=CheckpointerMemoryRuntime(
            lambda: checkpoint_manager.checkpointer if checkpoint_manager else None,
        ),
        max_iterations=settings.ai_agent_max_iterations,
        retrieval_limit=settings.ai_qa_retrieval_limit,
        page_size_limit=10,
        tool_result_max_tokens=settings.ai_agent_tool_result_max_tokens,
        rag_context_builder=build_rag_context_builder(),
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


@router.post("/qa/stream")
async def stream_news_question(
    payload: QaRequest,
    request: Request,
    _: User = Depends(get_current_user),
    qa_service: QaService = Depends(get_qa_service),
):
    return sse_response(
        request,
        qa_service.stream(payload.question),
        error_message="问答服务暂时不可用",
    )


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
        build_news_retrieval(db),
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
    except SensitiveDataBlocked:
        raise HTTPException(status_code=422, detail="请求包含不允许提交的敏感凭据") from None
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


@router.post("/agent/stream")
async def stream_news_agent(
    payload: AgentRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_service: AgentService = Depends(get_agent_service),
):
    try:
        # Perform credential screening before headers commit the response as SSE.
        agent_service.validate_input(
            payload.message,
            str(payload.conversation_id) if payload.conversation_id is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SensitiveDataBlocked:
        raise HTTPException(status_code=422, detail="请求包含不允许提交的敏感凭据") from None

    reader = SqlAgentReader(db, build_news_retrieval(db))
    return sse_response(
        request,
        agent_service.stream(
            user_id=user.id,
            message=payload.message,
            conversation_id=(
                str(payload.conversation_id) if payload.conversation_id is not None else None
            ),
            reader=reader,
        ),
        error_message="Agent 服务暂时不可用",
    )
