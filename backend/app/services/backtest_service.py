"""回测报告查询（L4，AGENTS.md §7 ``GET /backtest/report``）。

报告由 ``scripts/run_backtest.py`` 产出（``backtest_report.json``，仓库根）。
本服务只做**读取与校验**：不重跑回测（那是离线任务），报告不存在或与查询的省份/年份
不符时明确报错并给出复现命令——不返回"看起来像"的旧数据。
"""

from __future__ import annotations

import json
from pathlib import Path

#: backend/app/services/backtest_service.py → 仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT = REPO_ROOT / "backtest_report.json"
REGENERATE_HINT = (
    "请先运行：backend\\.venv\\Scripts\\python.exe scripts\\run_backtest.py "
    "--province <province> --year <year>"
)


class ReportUnavailable(Exception):
    """回测报告不存在或与查询条件不匹配。"""


def load_report(province: str | None = None, year: int | None = None, path: Path | None = None) -> dict:
    """读取回测报告；``province`` / ``year`` 给出时必须匹配，否则报错。"""
    report_path = path or DEFAULT_REPORT
    if not report_path.exists():
        raise ReportUnavailable(f"回测报告不存在（{report_path.name}）。{REGENERATE_HINT}")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReportUnavailable(f"回测报告无法解析：{exc}") from None

    if province and payload.get("province") != province:
        raise ReportUnavailable(
            f"报告省份为 {payload.get('province')}，与查询的 {province} 不符。{REGENERATE_HINT}"
        )
    if year and int(payload.get("year", 0)) != int(year):
        raise ReportUnavailable(
            f"报告年份为 {payload.get('year')}，与查询的 {year} 不符。{REGENERATE_HINT}"
        )
    payload["report_path"] = str(report_path)
    payload["regenerate_hint"] = REGENERATE_HINT
    return payload


__all__ = ["DEFAULT_REPORT", "REGENERATE_HINT", "ReportUnavailable", "load_report"]
