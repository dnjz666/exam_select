"""FastAPI 入口（L4 服务层，AGENTS.md §4.2 / §7）。

- 业务路由统一前缀 ``/api/v1``（§7）；``/health`` 保持无前缀（M0 验收命令依赖）；
- CORS 红线：``allow_origins=["*"]`` 禁止出现在任何非 dev 配置中（§4.3 硬性规则 4）；
- 领域异常 → HTTP 状态码映射集中在 :func:`create_app` 的异常处理器，
  错误体统一为 ``{"error": {code, message, details}}``。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import backtest as backtest_router
from app.api.v1 import catalog as catalog_router
from app.api.v1 import chat as chat_router
from app.api.v1 import meta as meta_router
from app.api.v1 import plans as plans_router
from app.api.v1 import recommend as recommend_router
from app.api.v1 import risk as risk_router
from app.api.v1 import students as students_router
from app.config import get_settings
from app.services.backtest_service import ReportUnavailable
from app.services.plan_service import PlanNotFound, UnknownUnits
from app.services.student_service import ProfileIncomplete, RankUnavailable

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="高考志愿填报智能体",
        version="0.1.0",
        description=(
            "基于位次法的可解释、可回测志愿推荐系统（数据层当前为模拟数据，严禁真实填报）。"
            "所有响应含 data / evidence / warnings 三段。"
        ),
    )

    # CORS 红线（AGENTS.md §4.3 硬性规则 4）：allow_origins=["*"] 禁止出现在任何非 dev 配置中
    if settings.is_dev:
        allow_origins = settings.cors_origins
    else:
        allow_origins = [origin for origin in settings.cors_origins if origin != "*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        meta_router.router,
        students_router.router,
        catalog_router.router,
        recommend_router.router,
        plans_router.router,
        risk_router.router,
        chat_router.router,
        backtest_router.router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    # dev：启动即建表（含 M3 新增 students/plans）；生产用迁移工具（M7 引入 alembic）
    if settings.is_dev:
        from app.db.session import init_db

        init_db()

    # ---- 领域异常 → HTTP ----
    @app.exception_handler(ProfileIncomplete)
    async def _profile_incomplete(_: Request, exc: ProfileIncomplete) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "PROFILE_INCOMPLETE",
                    "message": str(exc),
                    "details": {"missing_fields": exc.missing},
                }
            },
        )

    @app.exception_handler(RankUnavailable)
    async def _rank_unavailable(_: Request, exc: RankUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "RANK_UNAVAILABLE",
                    "message": f"位次换算不可用：{exc}。请直接填写已知位次，系统不会用估算值糊弄。",
                    "details": {},
                }
            },
        )

    @app.exception_handler(PlanNotFound)
    async def _plan_not_found(_: Request, exc: PlanNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "PLAN_NOT_FOUND", "message": str(exc), "details": {}}},
        )

    @app.exception_handler(UnknownUnits)
    async def _unknown_units(_: Request, exc: UnknownUnits) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "UNKNOWN_UNITS",
                    "message": str(exc),
                    "details": {"unit_ids": exc.unit_ids},
                }
            },
        )

    @app.exception_handler(ReportUnavailable)
    async def _report_unavailable(_: Request, exc: ReportUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "REPORT_UNAVAILABLE", "message": str(exc), "details": {}}},
        )

    @app.exception_handler(KeyError)
    async def _unknown_key(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": str(exc).strip("'"), "details": {}}},
        )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """健康检查：M0 验收命令依赖此端点返回 {"status":"ok"}。"""
        return {"status": "ok"}

    return app


app = create_app()
