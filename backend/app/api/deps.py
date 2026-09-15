"""FastAPI 依赖（L4，AGENTS.md §4.2）。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import SessionLocal


def get_db() -> Iterator[Session]:
    """每请求一个数据库会话（L4 才碰 DB；core 永远纯函数，ADR-003）。"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

__all__ = ["DbDep", "SettingsDep", "get_db"]
