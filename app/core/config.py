from functools import lru_cache
from typing import Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """统一管理 MySQL 和 Redis 配置，支持环境变量和 .env 文件。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "news_app"
    mysql_charset: str = "utf8mb4"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = Field(default=30, ge=1, le=120)
    ai_summary_max_characters: int = Field(default=400, ge=50, le=2000)
    ai_summary_cache_ttl_seconds: int = Field(default=60 * 60 * 24 * 30, ge=60)
    ai_qa_retrieval_limit: int = Field(default=5, ge=1, le=20)
    ai_qa_max_context_chars: int = Field(default=6000, ge=200, le=20000)
    ai_agent_history_max_rounds: int = Field(default=5, ge=1, le=20)
    ai_agent_history_max_tokens: int = Field(default=3000, ge=100, le=100000)
    ai_agent_tool_result_max_tokens: int = Field(default=4000, ge=100, le=100000)
    ai_agent_input_max_tokens: int = Field(default=10000, ge=1000, le=200000)
    ai_agent_memory_ttl_seconds: int = Field(default=86400, ge=60)
    ai_agent_max_iterations: int = Field(default=6, ge=1, le=20)

    @computed_field
    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset={self.mysql_charset}"
        )

    @computed_field
    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

