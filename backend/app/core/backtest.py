"""回测框架（AGENTS.md §6.9）—— 证明算法可信的唯一方式。

做法
----
用 **Y-1 年及更早**的历史预测 **Y 年**实际结果，逐样本比对：

```text
admitted = (考生位次 <= 该单位 Y 年实际最低位次)
```

输出：混淆矩阵、四项硬指标、校准曲线，以及按计划数分档 / 按院校层次分组的报告。

四项硬指标（§1.3 成功判据，M2 验收项）
--------------------------------------
| 指标 | 阈值 |
|---|---|
| 保底失效率（BAO/DIAN 被判安全却未投档） | **0%** |
| 稳档命中率（WEN 实际投档比例） | ≥ 85% |
| 冲档命中率（CHONG 实际投档比例） | ∈ [10%, 40%] |
| 概率校准 Brier score | ≤ 0.15 |

纯函数：输入是已组装好的样本，输出报告；不读库、不发请求（ADR-003）。
"""

from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.core.models import (
    AdmissionRecord,
    AdmissionUnit,
    BatchRule,
    Confidence,
    ModelParams,
    StudentProfile,
    Tier,
)
from app.core.probability import AnalogUnit, analog_key, build_analog_index, estimate_probability
from app.core.rules.base import ProvinceRule

#: 四项硬指标的阈值（唯一来源：AGENTS.md §1.3 / §6.9）
THRESHOLDS: dict[str, object] = {
    "safety_failure_rate": 0.0,
    "wen_hit_rate_min": 0.85,
    "chong_hit_rate_range": (0.10, 0.40),
    "brier_max": 0.15,
}

_PLAN_BANDS: tuple[tuple[str, int, int], ...] = (
    ("<5", 0, 4),
    ("5-9", 5, 9),
    ("10-19", 10, 19),
    (">=20", 20, 10**9),
)


@dataclass(frozen=True)
class BacktestSample:
    """一个 (考生, 单位) 的预测与实际结果。

    ``student_rank`` / ``actual_min_rank`` / ``predicted_min_rank`` / ``sigma`` 用于诊断
    "为什么判错"（例如：σ 是否低估了真实波动），不参与指标计算。
    """

    province: str
    student_id: str
    unit_key: str
    college_id: str
    level_tags: tuple[str, ...]
    plan_count: int
    probability: float | None
    tier: Tier
    confidence: Confidence
    admitted: bool
    student_rank: int = 0
    actual_min_rank: int | None = None
    predicted_min_rank: float = 0.0
    sigma: float = 0.0

    @property
    def z_true(self) -> float | None:
        """真实结果相对预测的标准化偏差：``(实际位次 − 预测位次) / σ``。

        负值 = 实际比预测**更难**（位次更靠前）；正值 = 实际更容易。
        """
        if self.actual_min_rank is None or self.sigma <= 0:
            return None
        return (self.actual_min_rank - self.predicted_min_rank) / self.sigma


@dataclass
class BacktestReport:
    province: str
    year: int
    sample_count: int = 0
    evaluated_count: int = 0
    no_data_count: int = 0
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    safety_failure_rate: float | None = None
    wen_hit_rate: float | None = None
    chong_hit_rate: float | None = None
    brier: float | None = None
    calibration: list[dict[str, float]] = field(default_factory=list)
    by_plan_band: dict[str, dict[str, float]] = field(default_factory=dict)
    by_level: dict[str, dict[str, float]] = field(default_factory=dict)
    tier_counts: dict[str, int] = field(default_factory=dict)
    confidence_counts: dict[str, int] = field(default_factory=dict)

    # ---- 指标判定 ----
    def checks(self) -> dict[str, dict[str, object]]:
        chong_low, chong_high = THRESHOLDS["chong_hit_rate_range"]  # type: ignore[misc]
        return {
            "safety_failure_rate": {
                "value": self.safety_failure_rate,
                "target": "== 0%",
                "passed": self.safety_failure_rate is not None and self.safety_failure_rate == 0.0,
            },
            "wen_hit_rate": {
                "value": self.wen_hit_rate,
                "target": f">= {THRESHOLDS['wen_hit_rate_min']:.0%}",
                "passed": self.wen_hit_rate is not None
                and self.wen_hit_rate >= float(THRESHOLDS["wen_hit_rate_min"]),
            },
            "chong_hit_rate": {
                "value": self.chong_hit_rate,
                "target": f"∈ [{chong_low:.0%}, {chong_high:.0%}]",
                "passed": self.chong_hit_rate is not None and chong_low <= self.chong_hit_rate <= chong_high,
            },
            "brier": {
                "value": self.brier,
                "target": f"<= {THRESHOLDS['brier_max']}",
                "passed": self.brier is not None and self.brier <= float(THRESHOLDS["brier_max"]),
            },
        }

    def all_passed(self) -> bool:
        return all(bool(item["passed"]) for item in self.checks().values())

    def to_dict(self) -> dict[str, object]:
        return {
            "province": self.province,
            "year": self.year,
            "sample_count": self.sample_count,
            "evaluated_count": self.evaluated_count,
            "no_data_count": self.no_data_count,
            "tier_counts": self.tier_counts,
            "confidence_counts": self.confidence_counts,
            "confusion": self.confusion,
            "metrics": {
                "safety_failure_rate": self.safety_failure_rate,
                "wen_hit_rate": self.wen_hit_rate,
                "chong_hit_rate": self.chong_hit_rate,
                "brier": self.brier,
            },
            "checks": self.checks(),
            "calibration": self.calibration,
            "by_plan_band": self.by_plan_band,
            "by_level": self.by_level,
            "all_passed": self.all_passed(),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# 回测报告 · {self.province} · {self.year} 年",
            "",
            f"- 样本数：{self.sample_count}（其中可评估 {self.evaluated_count}，"
            f"NO_DATA {self.no_data_count}）",
            "",
            "## 四项硬指标",
            "",
            "| 指标 | 实际 | 目标 | 判定 |",
            "|---|---|---|---|",
        ]
        for name, item in self.checks().items():
            value = item["value"]
            shown = "—" if value is None else (
                f"{value:.2%}" if name != "brier" else f"{value:.4f}"
            )
            lines.append(f"| {name} | {shown} | {item['target']} | {'✅' if item['passed'] else '❌'} |")
        lines += ["", "## 混淆矩阵（预测分层 × 实际是否投档）", "", "| 分层 | 投档 | 未投档 | 命中率 |", "|---|---|---|---|"]
        for tier, row in sorted(self.confusion.items()):
            total = row["admitted"] + row["not_admitted"]
            rate = row["admitted"] / total if total else 0.0
            lines.append(f"| {tier} | {row['admitted']} | {row['not_admitted']} | {rate:.1%} |")
        lines += ["", "## 校准曲线（预测概率分桶 → 实际命中率）", "", "| 预测区间 | 样本 | 预测均值 | 实际命中率 |", "|---|---|---|---|"]
        for bucket in self.calibration:
            lines.append(
                f"| {bucket['low']:.1f}-{bucket['high']:.1f} | {int(bucket['count'])} | "
                f"{bucket['predicted_mean']:.3f} | {bucket['observed_rate']:.3f} |"
            )
        lines += ["", "## 按计划数分档", "", "| 计划数 | 样本 | 平均预测 | 实际命中率 |", "|---|---|---|---|"]
        for band, row in self.by_plan_band.items():
            lines.append(
                f"| {band} | {int(row['count'])} | {row['predicted_mean']:.3f} | {row['observed_rate']:.3f} |"
            )
        lines += ["", "## 按院校层次分组", "", "| 层次 | 样本 | 平均预测 | 实际命中率 |", "|---|---|---|---|"]
        for level, row in self.by_level.items():
            lines.append(
                f"| {level} | {int(row['count'])} | {row['predicted_mean']:.3f} | {row['observed_rate']:.3f} |"
            )
        lines += [
            "",
            "> ⚠️ 本报告基于**确定性模拟数据**（`is_synthetic=1`），仅用于验证算法，"
            "**不得用于真实志愿填报**。",
        ]
        return "\n".join(lines)


def _band_of(plan_count: int) -> str:
    for name, low, high in _PLAN_BANDS:
        if low <= plan_count <= high:
            return name
    return ">=20"  # pragma: no cover


def _level_of(level_tags: Sequence[str]) -> str:
    tags = set(level_tags)
    for tag in ("985", "211", "双一流"):
        if tag in tags:
            return tag
    return "其他"


def _rate_block(samples: Sequence[BacktestSample]) -> dict[str, float]:
    evaluated = [s for s in samples if s.probability is not None]
    if not evaluated:
        return {"count": 0.0, "predicted_mean": 0.0, "observed_rate": 0.0}
    return {
        "count": float(len(evaluated)),
        "predicted_mean": statistics.fmean(s.probability or 0.0 for s in evaluated),
        "observed_rate": statistics.fmean(1.0 if s.admitted else 0.0 for s in evaluated),
    }


def run_backtest(
    samples: Sequence[BacktestSample], *, province: str, year: int, bins: int = 10
) -> BacktestReport:
    """由样本计算报告（纯函数；指标口径见模块 docstring）。"""
    report = BacktestReport(province=province, year=year, sample_count=len(samples))
    evaluated = [s for s in samples if s.probability is not None]
    report.evaluated_count = len(evaluated)
    report.no_data_count = len(samples) - len(evaluated)

    confusion: dict[str, dict[str, int]] = defaultdict(lambda: {"admitted": 0, "not_admitted": 0})
    tier_counts: dict[str, int] = defaultdict(int)
    confidence_counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        tier_counts[sample.tier.value] += 1
        confidence_counts[sample.confidence.value] += 1
        if sample.probability is None:
            continue
        confusion[sample.tier.value]["admitted" if sample.admitted else "not_admitted"] += 1
    report.confusion = {tier: dict(row) for tier, row in sorted(confusion.items())}
    report.tier_counts = dict(sorted(tier_counts.items()))
    report.confidence_counts = dict(sorted(confidence_counts.items()))

    def hit_rate(tier: Tier) -> float | None:
        rows = [s for s in evaluated if s.tier is tier]
        if not rows:
            return None
        return statistics.fmean(1.0 if s.admitted else 0.0 for s in rows)

    safety_rows = [s for s in evaluated if s.tier in (Tier.BAO, Tier.DIAN)]
    report.safety_failure_rate = (
        statistics.fmean(0.0 if s.admitted else 1.0 for s in safety_rows) if safety_rows else None
    )
    report.wen_hit_rate = hit_rate(Tier.WEN)
    report.chong_hit_rate = hit_rate(Tier.CHONG)
    report.brier = (
        statistics.fmean((float(s.probability) - (1.0 if s.admitted else 0.0)) ** 2 for s in evaluated)
        if evaluated
        else None
    )

    # 校准曲线
    calibration: list[dict[str, float]] = []
    width = 1.0 / bins
    for index in range(bins):
        low, high = index * width, (index + 1) * width
        bucket = [
            s
            for s in evaluated
            if (low <= float(s.probability) < high) or (index == bins - 1 and float(s.probability) == high)
        ]
        if not bucket:
            continue
        calibration.append(
            {
                "low": low,
                "high": high,
                "count": float(len(bucket)),
                "predicted_mean": statistics.fmean(float(s.probability) for s in bucket),
                "observed_rate": statistics.fmean(1.0 if s.admitted else 0.0 for s in bucket),
            }
        )
    report.calibration = calibration

    # 分组
    bands: dict[str, list[BacktestSample]] = defaultdict(list)
    levels: dict[str, list[BacktestSample]] = defaultdict(list)
    for sample in evaluated:
        bands[_band_of(sample.plan_count)].append(sample)
        levels[_level_of(sample.level_tags)].append(sample)
    report.by_plan_band = {name: _rate_block(rows) for name, rows in sorted(bands.items())}
    report.by_level = {name: _rate_block(rows) for name, rows in sorted(levels.items())}
    return report


def build_samples(
    *,
    students: Sequence[StudentProfile],
    units: Sequence[AdmissionUnit],
    history_by_key: Mapping[str, Sequence[AdmissionRecord]],
    actual_min_rank: Mapping[str, int],
    rule: ProvinceRule,
    batch: BatchRule,
    params: ModelParams,
    current_total_candidates: int | None = None,
    analog_units: Sequence[AnalogUnit] = (),
    level_tags_by_college: Mapping[str, Sequence[str]] | None = None,
    samples_per_student: int = 120,
    seed: int = 20250915,
) -> list[BacktestSample]:
    """逐 (考生, 单位) 预测并与实际结果比对（确定性抽样）。

    ``actual_min_rank``：``unit_key -> Y 年实际最低位次``（**地面真值**）。
    """
    _ = batch  # 批次上下文由 rule 提供；保留参数以便调用方显式声明批次
    tags_map = level_tags_by_college or {}
    analog_index = build_analog_index(analog_units)
    rng = random.Random(seed)
    samples: list[BacktestSample] = []

    for student in students:
        if not units:
            break
        size = min(samples_per_student, len(units))
        picked = rng.sample(list(units), size) if size < len(units) else list(units)
        for unit in picked:
            history = history_by_key.get(_key(unit), ())
            level_tags = tuple(tags_map.get(unit.college_id, ()))
            discipline = None
            bucket = analog_index.get(analog_key(unit.college_id.split("-", 1)[0], level_tags, discipline), [])
            result = estimate_probability(
                student,
                unit,
                history,
                rule,
                params,
                current_total_candidates=current_total_candidates,
                analog_pool=bucket,
            )
            key = _key(unit)
            actual = actual_min_rank.get(key)
            if student.rank is None or actual is None:
                continue
            samples.append(
                BacktestSample(
                    province=student.province,
                    student_id=student.id,
                    unit_key=key,
                    college_id=unit.college_id,
                    level_tags=level_tags,
                    plan_count=unit.plan_count,
                    probability=result.probability,
                    tier=result.tier,
                    confidence=result.confidence,
                    admitted=student.rank <= actual,
                    student_rank=student.rank,
                    actual_min_rank=actual,
                    predicted_min_rank=result.predicted_min_rank,
                    sigma=result.sigma,
                )
            )
    return samples


def _key(unit: AdmissionUnit) -> str:
    from app.core.models import unit_key_of

    return unit_key_of(unit.unit_id)


def write_report(report: BacktestReport, json_path: str, md_path: str) -> None:
    """落盘 ``backtest_report.json`` + ``backtest_report.md``（§6.9 输出要求）。"""
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report.to_dict(), handle, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(report.to_markdown())


__all__ = [
    "THRESHOLDS",
    "BacktestReport",
    "BacktestSample",
    "build_samples",
    "run_backtest",
    "write_report",
]
