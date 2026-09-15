"""应用配置（L4 层）。

职责：把 `docs/DOMAIN_RULES.md` §3 的 `ModelParams` 默认值与环境变量接线。
铁律：本文件不得包含任何领域魔数——所有默认值都定义在 `app.core.models.ModelParams`
（其唯一权威来源是 DOMAIN_RULES.md §3），这里只做环境变量覆盖与装配。

⚠️ **SQLite 路径锚定（M3 实测缺陷）**：默认库路径是相对路径，而 AGENTS.md §4.4 的验收命令
是 `Push-Location backend` 后再起服务——相对路径会解析到 `backend\\data\\...`（不存在 → 
``unable to open database file``；更坏的情况是静默生成第二个空库，让人误以为库里没数据）。
因此这里把 SQLite 相对路径**统一锚定到仓库根**，并确保父目录存在：
无论从仓库根还是从 ``backend/`` 启动，连的都是同一个库。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.models import ModelParams

#: backend/app/config.py → parents[0]=app, [1]=backend, [2]=仓库根
REPO_ROOT = Path(__file__).resolve().parents[2]

SQLITE_PREFIX = "sqlite:///"


def anchor_sqlite_url(url: str) -> str:
    """把 ``sqlite:///`` 的相对路径锚定到仓库根，并确保目录存在。"""
    if not url.startswith(SQLITE_PREFIX):
        return url
    raw = url[len(SQLITE_PREFIX) :]
    if raw in ("", ":memory:") or raw.startswith("file:"):
        return url
    path = Path(raw)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{SQLITE_PREFIX}{path.as_posix()}"


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

    @field_validator("database_url")
    @classmethod
    def _anchor_database_url(cls, value: str) -> str:
        return anchor_sqlite_url(value)

    @property
    def is_dev(self) -> bool:
        return self.app_environment == "dev"


@lru_cache
def get_settings() -> Settings:
    """FastAPI 依赖注入用单例（`app.api.deps` 亦复用此函数）。"""
    return Settings()
