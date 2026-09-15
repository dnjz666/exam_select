"""参数标定：网格扫描关键 ``ModelParams`` 并输出回测四项指标（DOMAIN_RULES.md §3.1）。

用法::

    backend\\.venv\\Scripts\\python.exe scripts\\calibrate_params.py --province zhejiang --year 2025

纪律（§3.1）
------------
1. 默认值来自经验先验，**不是真理**；必须用回测选出在回测上最优且不过拟合的取值；
2. 每次参数改动都要附**改动前后**指标对比（本脚本输出的表格即为该证据）；
3. 结论写入 ``docs/DECISIONS.md``。

只扫描**与校准直接相关**的参数（σ 下限、波动阈值、计划弹性）；分层边界（§6.3）与
仓位配额不属于本脚本范围。
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_ROOT / "backend"))

from app.core.backtest import build_samples, run_backtest  # noqa: E402
from app.core.models import ModelParams  # noqa: E402
from app.etl.synthetic import GROUND_TRUTH_YEAR  # noqa: E402
from app.services.backtest_data import load_backtest_context  # noqa: E402

GRID: dict[str, list[float | int]] = {
    # 跨省稳定性验证：只在 safety_margin 上比较（其余参数保持文档默认值，避免过拟合）
    "safety_margin": [0.25, 0.30],
    "min_sigma_abs": [300.0],
    "min_sigma_rel": [0.03],
    "cv_threshold": [0.15],
    "plan_beta": [0.4],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ModelParams 网格标定（回测驱动）")
    parser.add_argument("--province", default="zhejiang")
    parser.add_argument("--year", type=int, default=GROUND_TRUTH_YEAR)
    parser.add_argument("--students", type=int, default=60, help="扫描用考生数（小于验收规模以控时）")
    parser.add_argument("--samples-per-student", type=int, default=100)
    parser.add_argument("--top", type=int, default=12, help="打印前 N 个组合")
    args = parser.parse_args(argv)

    ctx = load_backtest_context(args.province, args.year)
    students = ctx.make_students(args.students)

    keys = list(GRID)
    rows: list[dict[str, object]] = []
    for combo in itertools.product(*(GRID[key] for key in keys)):
        params = ModelParams(**dict(zip(keys, combo)))  # type: ignore[arg-type]
        started = time.time()
        samples = build_samples(
            students=students,
            units=ctx.units,
            history_by_key=ctx.history_by_key,
            actual_min_rank=ctx.actual_min_rank,
            rule=ctx.rule,  # type: ignore[arg-type]
            batch=ctx.batch,  # type: ignore[arg-type]
            params=params,
            current_total_candidates=ctx.total_candidates,
            analog_units=ctx.analog_units,
            level_tags_by_college=ctx.level_tags_by_college,
            samples_per_student=args.samples_per_student,
        )
        report = run_backtest(samples, province=args.province, year=args.year)
        rows.append(
            {
                **dict(zip(keys, combo)),
                "safety": report.safety_failure_rate,
                "wen": report.wen_hit_rate,
                "chong": report.chong_hit_rate,
                "brier": report.brier,
                "n_bao_dian": report.confusion.get("BAO", {}).get("admitted", 0)
                + report.confusion.get("BAO", {}).get("not_admitted", 0)
                + report.confusion.get("DIAN", {}).get("admitted", 0)
                + report.confusion.get("DIAN", {}).get("not_admitted", 0),
                "seconds": round(time.time() - started, 1),
            }
        )

    def score(row: dict[str, object]) -> tuple:
        """排序：保底失效（必须 0）→ 稳档是否 ≥85% → 冲档是否落到 [0.10,0.40] → Brier。"""
        safety = row["safety"] if row["safety"] is not None else 1.0
        wen = row["wen"] if row["wen"] is not None else -1.0
        chong = row["chong"] if row["chong"] is not None else -1.0
        wen_penalty = max(0.0, 0.85 - float(wen))
        chong_penalty = 0.0 if 0.10 <= float(chong) <= 0.40 else min(abs(float(chong) - 0.10), abs(float(chong) - 0.40))
        brier = row["brier"] if row["brier"] is not None else 1.0
        return (float(safety), wen_penalty, float(chong_penalty), float(brier))

    rows.sort(key=score)
    header = " | ".join(f"{key[:14]:>14}" for key in keys)
    print(f"{header} | {'保底失效':>9} | {'稳档':>7} | {'冲档':>7} | {'Brier':>7} | {'B/D样本':>7}")
    print("-" * (len(header) + 50))
    for row in rows[: args.top]:
        cells = " | ".join(f"{row[key]!s:>14}" for key in keys)
        print(
            f"{cells} | {row['safety']:>9.4f} | {row['wen'] if row['wen'] is None else round(row['wen'], 3):>7} "
            f"| {row['chong'] if row['chong'] is None else round(row['chong'], 3):>7} "
            f"| {row['brier']:>7.4f} | {row['n_bao_dian']:>7}"
        )
    print("-" * (len(header) + 50))
    print(f"共 {len(rows)} 个组合；上表为按「保底失效 → 冲档落在区间 → Brier」排序的前 {args.top} 个。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
