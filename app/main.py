from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import ai, news, users, favorite, history
from app.core.exception_handlers import register_exception_handlers
from app.ai.agent.checkpointer import RedisCheckpointManager
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    manager = RedisCheckpointManager(
        settings.agent_checkpointer_redis_url,
        ttl_seconds=settings.ai_agent_memory_ttl_seconds,
    )
    await manager.initialize()
    application.state.agent_checkpoint_manager = manager
    try:
        yield
    finally:
        await manager.close()

app = FastAPI(lifespan=lifespan)

# 注册全局异常处理器
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    # allow_origins=["*"],  # 允许访问的源
    allow_credentials=True,  # 允许携带cookie
    allow_methods=["*"],  # 允许所有请求方法
    allow_headers=["*"],  # 允许所有请求头
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
)


@app.get('/')
async def root():
    return {'message': 'Hello World'}


# 挂载路由/注册路由
app.include_router(news.router)
app.include_router(users.router)
app.include_router(favorite.router)
app.include_router(history.router)
app.include_router(ai.router)
