"""回测报告端点（AGENTS.md §7 ``GET /backtest/report``）。

报告由离线脚本产出（``scripts/run_backtest.py``）；本端点只读取并校验省份/年份，
不存在或不匹配时返回 404 + 复现命令（不返回"看起来像"的旧数据）。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.schemas import Envelope
from app.services import backtest_service

router = APIRouter(tags=["backtest"])


@router.get("/backtest/report", response_model=Envelope[dict], summary="回测报告")
def backtest_report(
    province: str | None = Query(default=None, description="省份代码，如 zhejiang"),
    year: int | None = Query(default=None, description="回测目标年，如 2025"),
) -> Envelope[dict]:
    report = backtest_service.load_report(province, year)
    warnings: list[str] = []
    checks = report.get("checks", {})
    failed = [name for name, item in checks.items() if not item.get("passed")]
    if failed:
        warnings.append("未达标指标：" + "、".join(sorted(failed)) + "（详见 checks 字段）。")
    warnings.append(
        "本报告基于确定性模拟数据（is_synthetic=1），仅用于验证算法，不得用于真实填报。"
    )
    evidence = [
        {
            "what": "backtest_report",
            "province": report.get("province"),
            "year": report.get("year"),
            "report_path": report.get("report_path"),
            "regenerate_hint": report.get("regenerate_hint"),
        }
    ]
    return Envelope[dict](data=report, evidence=evidence, warnings=warnings)


__all__ = ["router"]
