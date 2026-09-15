"""回测框架测试（AGENTS.md §6.9）：指标口径、校准曲线、分组、报告落盘、样本构造。"""

from __future__ import annotations

import json

import pytest

from app.core.backtest import (
    THRESHOLDS,
    BacktestSample,
    build_samples,
    run_backtest,
    write_report,
)
from app.core.models import Confidence, ModelParams, Tier
from app.core.rules import get_rule

from factories import make_history, make_student, make_unit


def _sample(
    tier: Tier,
    admitted: bool,
    probability: float | None,
    *,
    plan_count: int = 20,
    level_tags: tuple[str, ...] = (),
    student: str = "s1",
    unit_key: str = "zhejiang-1001-NA-100111",
) -> BacktestSample:
    return BacktestSample(
        province="zhejiang",
        student_id=student,
        unit_key=unit_key,
        college_id="zhejiang-1001",
        level_tags=level_tags,
        plan_count=plan_count,
        probability=probability,
        tier=tier,
        confidence=Confidence.HIGH if probability is not None else Confidence.NO_DATA,
        admitted=admitted,
    )


def test_thresholds_match_spec() -> None:
    assert THRESHOLDS["safety_failure_rate"] == 0.0
    assert THRESHOLDS["wen_hit_rate_min"] == 0.85
    assert THRESHOLDS["chong_hit_rate_range"] == (0.10, 0.40)
    assert THRESHOLDS["brier_max"] == 0.15


def test_metrics_math_is_exact() -> None:
    samples = [
        _sample(Tier.DIAN, True, 0.98, level_tags=("985", "211", "双一流")),
        _sample(Tier.DIAN, False, 0.95, level_tags=("985", "211", "双一流")),
        _sample(Tier.WEN, True, 0.60, plan_count=3),
        _sample(Tier.CHONG, True, 0.20),
        _sample(Tier.NO_DATA, False, None, plan_count=2),
    ]
    report = run_backtest(samples, province="zhejiang", year=2025)

    assert report.sample_count == 5
    assert report.evaluated_count == 4
    assert report.no_data_count == 1
    # 保底失效：2 个 BAO/DIAN 中 1 个未投档 → 50%
    assert report.safety_failure_rate == pytest.approx(0.5)
    assert report.wen_hit_rate == pytest.approx(1.0)
    assert report.chong_hit_rate == pytest.approx(1.0)
    # Brier = mean[(p - y)^2]，NO_DATA 不参与
    expected = ((0.98 - 1) ** 2 + (0.95 - 0) ** 2 + (0.6 - 1) ** 2 + (0.2 - 1) ** 2) / 4
    assert report.brier == pytest.approx(expected, rel=1e-9)

    assert report.confusion["DIAN"] == {"admitted": 1, "not_admitted": 1}
    assert report.confusion["WEN"] == {"admitted": 1, "not_admitted": 0}
    assert "NO_DATA" not in report.confusion  # 无概率样本不进混淆矩阵
    assert report.tier_counts["NO_DATA"] == 1

    # 校准曲线：0.9-1.0 桶（2 例，观测 0.5）、0.5-0.6 桶、0.2-0.3 桶
    buckets = {(round(b["low"], 1), round(b["high"], 1)): b for b in report.calibration}
    assert buckets[(0.9, 1.0)]["count"] == 2
    assert buckets[(0.9, 1.0)]["observed_rate"] == pytest.approx(0.5)
    assert buckets[(0.2, 0.3)]["observed_rate"] == pytest.approx(1.0)

    # 分组：计划数分档与院校层次（NO_DATA 样本不参与 evaluated 分组）
    assert report.by_plan_band["<5"]["count"] == 1  # 仅 plan_count=3 的 WEN 样本
    assert report.by_level["985"]["count"] == 2
    assert report.by_level["其他"]["count"] == 2

    checks = report.checks()
    assert checks["safety_failure_rate"]["passed"] is False
    assert checks["chong_hit_rate"]["passed"] is False  # 100% > 40%
    assert checks["brier"]["passed"] is False
    assert report.all_passed() is False


def test_all_passed_case() -> None:
    samples = [
        _sample(Tier.DIAN, True, 0.96),
        _sample(Tier.BAO, True, 0.85),
        _sample(Tier.WEN, True, 0.70),
        _sample(Tier.WEN, True, 0.65),
        _sample(Tier.CHONG, True, 0.35),
        _sample(Tier.CHONG, False, 0.35),
        _sample(Tier.CHONG, False, 0.35),
        _sample(Tier.CHONG, False, 0.35),
    ]
    report = run_backtest(samples, province="zhejiang", year=2025)
    assert report.safety_failure_rate == 0.0
    assert report.wen_hit_rate == 1.0
    assert report.chong_hit_rate == pytest.approx(0.25)
    assert report.brier is not None and report.brier <= 0.15
    assert report.all_passed() is True


def test_empty_samples_are_reported_as_failures() -> None:
    report = run_backtest([], province="zhejiang", year=2025)
    assert report.sample_count == 0
    assert report.evaluated_count == 0
    assert report.safety_failure_rate is None
    assert report.brier is None
    assert all(not item["passed"] for item in report.checks().values())
    assert report.all_passed() is False


def test_report_serialisation_and_files(tmp_path) -> None:
    samples = [_sample(Tier.DIAN, True, 0.9), _sample(Tier.WEN, True, 0.6)]
    report = run_backtest(samples, province="zhejiang", year=2025)

    payload = report.to_dict()
    assert payload["province"] == "zhejiang"
    assert payload["metrics"]["brier"] == report.brier
    assert "checks" in payload and "calibration" in payload
    json.dumps(payload, ensure_ascii=False)  # 必须可 JSON 序列化

    markdown = report.to_markdown()
    assert "四项硬指标" in markdown and "校准曲线" in markdown
    assert "模拟数据" in markdown  # 免责声明必须存在

    json_path = tmp_path / "backtest_report.json"
    md_path = tmp_path / "backtest_report.md"
    write_report(report, str(json_path), str(md_path))
    assert json.loads(json_path.read_text(encoding="utf-8"))["year"] == 2025
    assert "回测报告" in md_path.read_text(encoding="utf-8")


def test_build_samples_end_to_end_and_deterministic() -> None:
    rule = get_rule("zhejiang")
    batch = rule.main_batch()
    students = [make_student(9000, id="stu-1"), make_student(5000, id="stu-2")]
    unit_a = make_unit(college="6001")
    unit_b = make_unit(college="6002", major="100602")
    key_a = "zhejiang-6001-NA-100111"
    key_b = "zhejiang-6002-NA-100602"
    history = {
        key_a: make_history(key_a, {2024: 9000, 2023: 9500, 2022: 9200}),
        key_b: make_history(key_b, {2024: 4000, 2023: 4200, 2022: 4100}),
    }
    actual = {key_a: 9100, key_b: 4000}

    def _run() -> list[BacktestSample]:
        return build_samples(
            students=students,
            units=[unit_a, unit_b],
            history_by_key=history,
            actual_min_rank=actual,
            rule=rule,
            batch=batch,
            params=ModelParams(),
            current_total_candidates=400_000,
            level_tags_by_college={"zhejiang-6001": ["985", "211", "双一流"]},
            samples_per_student=2,
            seed=7,
        )

    samples = _run()
    assert len(samples) == 4  # 2 考生 × 2 单位
    admission = {(s.student_id, s.unit_key): s.admitted for s in samples}
    # 考生 9000 <= 实际 9100 → 投档；9000 > 4000 → 未投档；考生 5000 对两个单位都投档
    assert admission[("stu-1", key_a)] is True
    assert admission[("stu-1", key_b)] is False
    assert admission[("stu-2", key_b)] is False  # 5000 > 4000
    assert all(s.probability is not None for s in samples)
    assert _run() == samples  # 同 seed → 样本完全一致（可复现）


def test_build_samples_handles_missing_actual() -> None:
    rule = get_rule("zhejiang")
    batch = rule.main_batch()
    unit = make_unit(college="6101")
    samples = build_samples(
        students=[make_student(9000)],
        units=[unit],
        history_by_key={},
        actual_min_rank={},  # 无地面真值 → 该单位无法评估
        rule=rule,
        batch=batch,
        params=ModelParams(),
        current_total_candidates=400_000,
        samples_per_student=1,
    )
    assert samples == []
