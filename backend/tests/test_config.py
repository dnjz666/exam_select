"""配置测试（M3 实测缺陷回归）：SQLite 路径必须锚定到仓库根，与启动 CWD 无关。"""

from __future__ import annotations

import os
from pathlib import Path

from app.config import REPO_ROOT, Settings, anchor_sqlite_url, get_settings


def test_relative_sqlite_url_is_anchored_to_repo_root() -> None:
    url = anchor_sqlite_url("sqlite:///./data/exam_select.db")
    assert url.startswith("sqlite:///")
    assert url.endswith("/data/exam_select.db")
    assert Path(url[len("sqlite:///") :]).is_absolute()
    # 与启动 CWD 无关：锚定结果就是仓库根下的 data/
    assert Path(url[len("sqlite:///") :]).parent == REPO_ROOT / "data"


def test_anchor_is_idempotent_and_keeps_other_urls() -> None:
    once = anchor_sqlite_url("sqlite:///./data/exam_select.db")
    assert anchor_sqlite_url(once) == once  # 已是绝对路径 → 不变
    assert anchor_sqlite_url("sqlite:///:memory:") == "sqlite:///:memory:"
    postgres = "postgresql+psycopg://user:pass@localhost:5432/exam_select"
    assert anchor_sqlite_url(postgres) == postgres


def test_settings_anchors_database_url_regardless_of_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # 模拟"从 backend/ 启动"这类不同 CWD
    settings = Settings()
    assert Path(settings.database_url[len("sqlite:///") :]).is_absolute()
    assert Path(settings.database_url[len("sqlite:///") :]).parent == REPO_ROOT / "data"
    assert settings.is_dev is True  # 默认 dev（AGENTS.md §4.3：非 dev 禁止 CORS "*"）


def test_settings_env_override(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "prod")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/other.db")
    monkeypatch.setenv("CORS_ORIGINS", '["https://example.com"]')
    settings = Settings()
    assert settings.is_dev is False
    assert settings.cors_origins == ["https://example.com"]
    assert settings.database_url.endswith("data/other.db")


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


_ = os
