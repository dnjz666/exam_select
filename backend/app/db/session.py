"""数据库会话（L2 数据层）。

core/ 纯算法层禁止 import 本模块（AGENTS.md §3.2 / DECISIONS.md ADR-003）：
数据由 L4 服务层查好、组装好，作为参数传进 core。
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _make_engine(url: str):  # noqa: ANN202 - engine 类型随方言变化
    if url.startswith("sqlite"):
        # SQLite 需要允许跨线程（uvicorn 线程池）；PostgreSQL 无此参数
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


def make_engine(url: str | None = None):
    """按连接串构建引擎（dev: SQLite / prod: PostgreSQL，仅差连接串）。"""
    return _make_engine(url or get_settings().database_url)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每请求一个会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表（dev 起步用；迁移工具在后续 Phase 引入）。"""
    from app.db.models import Base  # 确保表定义已注册

    Base.metadata.create_all(bind=engine)
