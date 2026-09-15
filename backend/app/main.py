"""FastAPI 入口（L4 服务层，AGENTS.md §4.2 / M0）。

M0 仅交付 /health 与配置装配；业务路由在 M3 按 AGENTS.md §7 实现。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="高考志愿填报智能体",
        version="0.1.0",
        description="基于位次法的可解释、可回测志愿推荐系统（数据层当前为模拟数据）",
    )

    # CORS 红线（AGENTS.md §4.3 硬性规则 4）：allow_origins=["*"] 禁止出现在任何非 dev 配置中
    if settings.is_dev:
        allow_origins = settings.cors_origins
    else:
        allow_origins = [o for o in settings.cors_origins if o != "*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        """健康检查：M0 验收命令依赖此端点返回 {"status":"ok"}。"""
        return {"status": "ok"}

    return app


app = create_app()
