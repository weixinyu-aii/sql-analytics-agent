import os
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["mock", "openai", "deepseek", "qwen", "glm"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "智能数据分析 Agent"
    app_version: str = "0.1.0"
    app_env: str = "development"
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:8501"

    database_url: str = "sqlite:///./data/analytics_demo.db"
    readonly_database_url: str | None = None
    auto_seed: bool = True
    seed_scale: float = 1.0
    allowed_tables: str = "categories,products,users,orders,order_items,sales"

    sql_max_rows: int = 200
    sql_timeout_seconds: int = 10
    sql_max_retries: int = 2
    sql_max_length: int = 12_000

    llm_provider: LLMProviderName = "mock"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_temperature: float = 0
    llm_timeout_seconds: int = 60

    @property
    def allowed_table_names(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.allowed_tables.split(",") if item.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def sql_dialect(self) -> str:
        url = self.database_url.lower()
        if url.startswith("postgresql"):
            return "postgresql"
        if url.startswith("mysql"):
            return "mysql"
        return "sqlite"

    @property
    def effective_readonly_database_url(self) -> str:
        return self.readonly_database_url or self.database_url

    @property
    def resolved_llm_base_url(self) -> str:
        presets = {
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "glm": "https://open.bigmodel.cn/api/paas/v4",
        }
        return (self.llm_base_url or presets.get(self.llm_provider, "")).rstrip("/")

    @property
    def resolved_llm_model(self) -> str:
        presets = {
            "openai": "gpt-4.1-mini",
            "deepseek": "deepseek-chat",
            "qwen": "qwen-plus",
            "glm": "glm-4-flash",
        }
        return self.llm_model or presets.get(self.llm_provider, "mock-analytics")

    @property
    def resolved_llm_api_key(self) -> str:
        configured = self.llm_api_key.get_secret_value().strip() if self.llm_api_key else ""
        if configured:
            return configured

        env_names = {
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "qwen": "DASHSCOPE_API_KEY",
            "glm": "ZHIPUAI_API_KEY",
        }
        return os.getenv(env_names.get(self.llm_provider, ""), "").strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

