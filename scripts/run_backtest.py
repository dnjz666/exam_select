"""跑回测并输出报告（AGENTS.md §6.9 / M2 验收命令）。

用法::

    backend\\.venv\\Scripts\\python.exe scripts\\run_backtest.py --province zhejiang --year 2025

流程：装载上下文（L4 service）→ 确定性考生队列 → 逐 (考生, 单位) 预测 →
与目标年**实际最低位次**比对（``admitted = 考生位次 <= 实际最低位次``）→ 落盘 JSON + MD。

退出码：四项硬指标全部达标 → 0，否则 1（不达标必须显式失败，不允许"看起来还行"）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_ROOT / "backend"))

from app.core.backtest import build_samples, run_backtest, write_report  # noqa: E402
from app.core.models import ModelParams  # noqa: E402
from app.etl.synthetic import GROUND_TRUTH_YEAR  # noqa: E402
from app.services.backtest_data import load_backtest_context  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回测：用 Y-1 及更早数据预测 Y 年实际结果")
    parser.add_argument("--province", default="zhejiang")
    parser.add_argument("--year", type=int, default=GROUND_TRUTH_YEAR)
    parser.add_argument("--students", type=int, default=150)
    parser.add_argument("--samples-per-student", type=int, default=150)
    parser.add_argument("--json", default="backtest_report.json")
    parser.add_argument("--md", default="backtest_report.md")
    args = parser.parse_args(argv)

    ctx = load_backtest_context(args.province, args.year)
    students = ctx.make_students(args.students)
    samples = build_samples(
        students=students,
        units=ctx.units,
        history_by_key=ctx.history_by_key,
        actual_min_rank=ctx.actual_min_rank,
        rule=ctx.rule,  # type: ignore[arg-type]
        batch=ctx.batch,  # type: ignore[arg-type]
        params=ModelParams(),
        current_total_candidates=ctx.total_candidates,
        analog_units=ctx.analog_units,
        level_tags_by_college=ctx.level_tags_by_college,
        samples_per_student=args.samples_per_student,
    )
    report = run_backtest(samples, province=args.province, year=args.year)
    write_report(report, args.json, args.md)

    print("=" * 66)
    print(f"回测：{args.province} · 预测 {args.year} 年（历史窗口 ≤ {args.year - 1}）")
    print(
        f"单位 {len(ctx.units)} 个 · 考生 {len(students)} 人 · 样本 {report.sample_count} "
        f"（可评估 {report.evaluated_count}，NO_DATA {report.no_data_count}）"
    )
    print(f"分层分布：{report.tier_counts}")
    print(f"置信度分布：{report.confidence_counts}")
    print("-" * 66)
    for name, item in report.checks().items():
        value = item["value"]
        shown = "—" if value is None else (f"{value:.4f}" if name == "brier" else f"{value:.2%}")
        print(f"  {'✅' if item['passed'] else '❌'} {name:<20} 实际 {shown:>9}   目标 {item['target']}")
    for note in report.notes():
        print(f"  ⚠️ {note}")
    print("-" * 66)

    failures = [s for s in samples if s.tier.value in ("BAO", "DIAN") and not s.admitted]
    if failures:
        print(f"⚠️ 保底失效率不为 0，共 {len(failures)} 例，按真实偏差排序（最多 10 条）：")
        for sample in sorted(failures, key=lambda s: s.z_true if s.z_true is not None else 0)[:10]:
            z = sample.z_true
            print(
                f"   - {sample.unit_key} | {sample.tier.value} | P={sample.probability:.3f} "
                f"| 预测 {sample.predicted_min_rank:,.0f} σ={sample.sigma:,.0f} "
                f"| 实际 {sample.actual_min_rank:,} | 考生 {sample.student_rank:,} | z_true={z:+.2f}"
            )

    print("-" * 66)
    print("分层校准（预测均值 → 实际命中率）：")
    for tier_name in sorted(report.confusion):
        rows = [s for s in samples if s.tier.value == tier_name and s.probability is not None]
        if not rows:
            continue
        predicted_mean = sum(s.probability or 0.0 for s in rows) / len(rows)
        observed = sum(1 for s in rows if s.admitted) / len(rows)
        print(
            f"  {tier_name:<9} n={len(rows):>5}  预测均值 {predicted_mean:.3f}  "
            f"实际命中 {observed:.3f}  偏差 {observed - predicted_mean:+.3f}"
        )
    safety_rows = [s for s in samples if s.tier.value in ("BAO", "DIAN") and s.probability is not None]
    z_values = sorted(z for s in safety_rows if (z := s.z_true) is not None)
    if z_values:
        print(
            f"  保底/垫档真实偏差 z_true：中位数 {z_values[len(z_values) // 2]:+.2f}、"
            f"最小 {z_values[0]:+.2f}（负值=实际比预测更难 → σ 低估真实波动）"
        )
    print("-" * 66)
    print(f"报告已写入：{args.json} / {args.md}")
    print(f"结论：{'全部达标 ✅' if report.all_passed() else '存在未达标指标 ❌'}")
    return 0 if report.all_passed() else 1


if __name__ == "__main__":
    sys.exit(main())
