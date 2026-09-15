"""应用配置（L4 层）。

职责：把 `docs/DOMAIN_RULES.md` §3 的 `ModelParams` 默认值与环境变量接线。
铁律：本文件不得包含任何领域魔数——所有默认值都定义在 `app.core.models.ModelParams`
（其唯一权威来源是 DOMAIN_RULES.md §3），这里只做环境变量覆盖与装配。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.models import ModelParams


class Settings(BaseSettings):
    """运行时配置。全部字段可由环境变量 / `.env` 覆盖（示例见 `.env.example`）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # 允许 MODEL_PARAMS__PLAN_BETA=0.5 形式的嵌套覆盖
        env_nested_delimiter="__",
        extra="ignore",
    )

    # dev 时允许 Vite 开发服务器跨域；非 dev 禁止 ["*"]（AGENTS.md §4.3 硬性规则 4）
    app_environment: str = "dev"
    database_url: str = "sqlite:///./data/exam_select.db"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173"])

    # 模型参数：默认值全部来自 ModelParams（DOMAIN_RULES.md §3），可用环境变量按需覆盖
    model_params: ModelParams = Field(default_factory=ModelParams)

    @property
    def is_dev(self) -> bool:
        return self.app_environment == "dev"


@lru_cache
def get_settings() -> Settings:
    """FastAPI 依赖注入用单例（`app.api.deps` 亦复用此函数）。"""
    return Settings()
