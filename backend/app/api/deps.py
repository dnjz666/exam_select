"""FastAPI 依赖（L4，AGENTS.md §4.2）。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import SessionLocal


def get_db() -> Iterator[Session]:
    """每请求一个数据库会话（L4 才碰 DB；core 永远纯函数，ADR-003）。

    ★ M6 / ADR-016：本请求**真的写了库**时，提交后推进 L2 的代数号，
    让静态参考数据缓存（院校/专业/单位/历史/概率结果）失效。
    只读请求不推进——否则每次 GET 都会把缓存清掉，等于没缓存。
    """
    from app.db import repositories as repo

    session = SessionLocal()
    try:
        yield session
        wrote = bool(session.new or session.dirty or session.deleted)
        session.commit()
        if wrote:
            repo.bump_generation()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

__all__ = ["DbDep", "SettingsDep", "get_db"]
