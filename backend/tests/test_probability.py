"""录取概率模型测试（AGENTS.md §6.2 / §7.2）。

包含 hypothesis 性质测试（方向性断言）。⚠️ §7.2 原文"历史位次整体变小（更难）→ 概率不下降"
与 §2.1 位次口径及 §6.2 公式矛盾（位次变小=更难=概率应下降），本文件按**公式与统一口径**断言
并注明；详见 ADR-009 与 tests/golden/golden_probability.json 的 G-018。
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.core.models import Confidence, ModelParams, Tier
from app.core.probability import (
    W_ANALOG_POOL,
    W_COLLECTED_ONLY,
    W_DERIVED_DATA,
    W_MISSING_RANK_IGNORED,
    W_NO_HISTORY,
    W_NO_NORMALIZATION_BASIS,
    W_SAFETY_MARGIN_NOT_MET,
    W_SAFETY_YEARS_NOT_ENOUGH,
    W_SINGLE_YEAR_DATA,
    W_SMALL_PLAN,
    W_SUSPECT_IGNORED,
    W_VOLATILE_HISTORY,
    AnalogUnit,
    build_analog_index,
    estimate_probability,
    probability_interval,
)
from app.core.rules import get_rule

from factories import PROVINCE, make_history, make_student, make_unit

RULE = get_rule(PROVINCE)
PARAMS = ModelParams()
UNIT = make_unit()  # 2026 年视图
KEY = "zhejiang-1001-NA-100111"
STANDARD_RANKS = {2025: 9000, 2024: 9500, 2023: 9200}  # 对应 G-001


def _estimate(ranks: dict[int, int | None] | None = None, *, rank: int | None = 9000, **kwargs):
    history = make_history(KEY, ranks if ranks is not None else STANDARD_RANKS)
    return estimate_probability(
        make_student(rank),
        UNIT,
        history,
        RULE,
        PARAMS,
        current_total_candidates=kwargs.pop("current_total_candidates", 400_000),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Step 1~8 基本行为
# ---------------------------------------------------------------------------
def test_weighted_prediction_and_sigma_floor() -> None:
    result = _estimate()
    # 人工推导：R0=9190 → 趋势 -100*0.5 → 9140；σ_raw=205.5 → σ 被下限抬到 300
    assert result.predicted_min_rank == pytest.approx(9140, abs=1)
    assert result.sigma == pytest.approx(PARAMS.min_sigma_abs)
    assert result.probability == pytest.approx(0.6796, abs=0.01)
    assert result.tier is Tier.WEN
    assert result.confidence is Confidence.HIGH
    assert len(result.evidence) == 3
    assert all(item.source_url for item in result.evidence)
    assert any(adjustment.name == "trend" for adjustment in result.adjustments)


def test_evidence_and_reasons_are_complete() -> None:
    result = _estimate()
    assert [item.year for item in result.evidence] == [2025, 2024, 2023]
    assert all(item.min_rank for item in result.evidence)
    assert result.reasons and "位次" in result.reasons[0]
    assert {a.name for a in result.adjustments} <= {"trend", "plan_count", "volatility_shrinkage"}


def test_trend_direction_hot_vs_cold() -> None:
    """单位越来越热（位次逐年变小）→ 预测位次前移 → 同一考生概率更低。"""
    hot = _estimate({2025: 9000, 2024: 9250, 2023: 9500})
    cold = _estimate({2025: 9500, 2024: 9250, 2023: 9000})
    assert hot.predicted_min_rank < cold.predicted_min_rank
    assert hot.probability < cold.probability


def test_plan_increase_raises_probability() -> None:
    base = _estimate({2025: 9000, 2024: 9000, 2023: 9000}, rank=10000)
    increased = estimate_probability(
        make_student(10000),
        make_unit(plan_count=30),
        make_history(KEY, {2025: 9000, 2024: 9000, 2023: 9000}, plan_count=20),
        RULE,
        PARAMS,
        current_total_candidates=400_000,
    )
    assert increased.predicted_min_rank > base.predicted_min_rank
    assert increased.probability > base.probability
    assert any(a.name == "plan_count" for a in increased.adjustments)


def test_probability_clipping_never_extreme() -> None:
    very_safe = _estimate(STANDARD_RANKS, rank=1)
    very_risky = _estimate(STANDARD_RANKS, rank=399_999)
    assert very_safe.probability == PARAMS.prob_clip_high
    assert very_risky.probability == PARAMS.prob_clip_low
    assert very_safe.tier is Tier.DIAN
    assert very_risky.tier is Tier.TOO_RISKY


def test_volatility_shrinkage_moves_toward_half() -> None:
    """波动收缩 = 放大 σ（降低自信），而不是把点估计压进分层中段（ADR-009 勘误）。"""
    volatile = _estimate({2025: 7000, 2024: 12000, 2023: 7500}, rank=8500)
    assert W_VOLATILE_HISTORY in volatile.warnings
    assert any(a.name == "volatility_shrinkage" for a in volatile.adjustments)
    # 关闭收缩的对照组：收缩后必须更接近 0.5，但**不得**被压进 [0.5κ, 1-0.5κ] 的中段
    no_shrink = estimate_probability(
        make_student(8500),
        UNIT,
        make_history(KEY, {2025: 7000, 2024: 12000, 2023: 7500}),
        RULE,
        ModelParams(shrinkage_max=0.0),
        current_total_candidates=400_000,
    )
    assert volatile.probability is not None and no_shrink.probability is not None
    assert abs(volatile.probability - 0.5) < abs(no_shrink.probability - 0.5) + 1e-12
    assert volatile.sigma > no_shrink.sigma  # σ 被放大
    assert volatile.confidence is Confidence.MEDIUM  # cv 超阈值 → 不得 HIGH


def test_extreme_probabilities_survive_volatility_shrinkage() -> None:
    """波动单位也必须能触达两端：毫不沾边的考生不得被"托"到 12% 以上（ADR-009 回归）。"""
    hopeless = _estimate({2025: 10739, 2024: 15930, 2023: 8328}, rank=300_000)
    certain = _estimate({2025: 10739, 2024: 15930, 2023: 8328}, rank=100)
    assert hopeless.probability == PARAMS.prob_clip_low
    assert certain.probability == PARAMS.prob_clip_high
    assert hopeless.tier is Tier.TOO_RISKY
    assert certain.tier is Tier.DIAN


def test_single_year_and_small_plan_warnings() -> None:
    result = _estimate({2025: 9000}, rank=9000)
    assert W_SINGLE_YEAR_DATA in result.warnings
    assert result.confidence is Confidence.LOW

    small = estimate_probability(
        make_student(9000),
        make_unit(plan_count=3),
        make_history(KEY, STANDARD_RANKS),
        RULE,
        PARAMS,
        current_total_candidates=400_000,
    )
    assert W_SMALL_PLAN in small.warnings
    assert small.confidence is Confidence.LOW


def test_collected_only_and_derived_warnings() -> None:
    collected = estimate_probability(
        make_student(9000),
        make_unit(),
        make_history(KEY, STANDARD_RANKS, data_quality="COLLECTED", is_collected=True),
        RULE,
        PARAMS,
        current_total_candidates=400_000,
    )
    assert W_COLLECTED_ONLY in collected.warnings
    derived = estimate_probability(
        make_student(9000),
        make_unit(),
        make_history(KEY, STANDARD_RANKS, data_quality="DERIVED"),
        RULE,
        PARAMS,
        current_total_candidates=400_000,
    )
    assert W_DERIVED_DATA in derived.warnings


def test_suspect_and_missing_rank_are_discarded() -> None:
    history = [
        *make_history(KEY, {2025: None}, data_quality="MISSING_RANK"),
        *make_history(KEY, {2024: 9000}, data_quality="SUSPECT"),
        *make_history(KEY, {2023: 9200}, data_quality="OK"),
    ]
    result = estimate_probability(
        make_student(9200), make_unit(), history, RULE, PARAMS, current_total_candidates=400_000
    )
    assert W_MISSING_RANK_IGNORED in result.warnings
    assert W_SUSPECT_IGNORED in result.warnings
    assert len(result.evidence) == 1
    assert result.confidence is Confidence.LOW


def test_no_normalization_basis_is_flagged_and_caps_confidence() -> None:
    result = estimate_probability(
        make_student(9000),
        make_unit(),
        make_history(KEY, {2025: 9000, 2024: 9500, 2023: 9200}, total_candidates=None),
        RULE,
        PARAMS,
        current_total_candidates=None,
    )
    assert W_NO_NORMALIZATION_BASIS in result.warnings
    assert result.confidence is not Confidence.HIGH
    assert any("归一化" in reason for reason in result.reasons)


def test_normalization_shifts_prediction_by_candidate_growth() -> None:
    history = make_history(KEY, {2025: 10000}, total_candidates=400_000)
    result = estimate_probability(
        make_student(10000), make_unit(), history, RULE, PARAMS, current_total_candidates=440_000
    )
    assert result.predicted_min_rank == pytest.approx(11000, abs=1)  # ×(440000/400000)


# ---------------------------------------------------------------------------
# Step 0：无历史回退
# ---------------------------------------------------------------------------
def _analog_pool(count: int, ranks: list[int]) -> list[AnalogUnit]:
    analogs: list[AnalogUnit] = []
    for index in range(count):
        key = f"zhejiang-{2001 + index}-NA-10011{index}"
        unit = make_unit(college=f"{2001 + index}", major=f"10011{index}")
        analogs.append(
            AnalogUnit(
                unit=unit,
                records=make_history(key, {2025: ranks[index]}),
                level_tags=("211", "双一流"),
                discipline="计算机类",
                college_province="zhejiang",
            )
        )
    return analogs


def test_no_history_without_analogs_is_no_data() -> None:
    result = estimate_probability(
        make_student(9000),
        UNIT,
        [],
        RULE,
        PARAMS,
        current_total_candidates=400_000,
        analog_pool=_analog_pool(2, [9000, 9500]),
    )
    assert result.probability is None
    assert result.tier is Tier.NO_DATA
    assert result.confidence is Confidence.NO_DATA
    assert W_NO_HISTORY in result.warnings
    assert any("类比池不足" in reason for reason in result.reasons)
    assert probability_interval(result, PARAMS) is None


def test_no_history_with_analogs_uses_median_and_low_confidence() -> None:
    result = estimate_probability(
        make_student(9000),
        UNIT,
        [],
        RULE,
        PARAMS,
        current_total_candidates=400_000,
        analog_pool=_analog_pool(3, [9000, 9500, 9200]),
    )
    assert result.probability is not None
    assert result.predicted_min_rank == pytest.approx(9200, abs=1)  # 中位数
    assert result.confidence is Confidence.LOW
    assert {W_NO_HISTORY, W_ANALOG_POOL} <= set(result.warnings)


def test_analog_index_buckets_by_key() -> None:
    index = build_analog_index(_analog_pool(2, [9000, 9500]))
    assert len(index) == 1
    (key, bucket), = index.items()
    assert key == ("zhejiang", ("211", "双一流"), "计算机类")
    assert len(bucket) == 2


# ---------------------------------------------------------------------------
# 防数据泄漏
# ---------------------------------------------------------------------------
def test_current_year_records_are_ignored() -> None:
    clean = _estimate(STANDARD_RANKS, rank=9000)
    leaked = estimate_probability(
        make_student(9000),
        UNIT,
        make_history(KEY, {**STANDARD_RANKS, 2026: 100}),  # 当年结果（地面真值）不得进入预测
        RULE,
        PARAMS,
        current_total_candidates=400_000,
    )
    assert leaked.probability == pytest.approx(clean.probability)
    assert [item.year for item in leaked.evidence] == [2025, 2024, 2023]


def test_missing_rank_returns_no_data_with_reason() -> None:
    result = _estimate(STANDARD_RANKS, rank=None)
    assert result.probability is None
    assert result.confidence is Confidence.NO_DATA
    assert any("位次缺失" in reason for reason in result.reasons)


# ---------------------------------------------------------------------------
# 概率区间（UI 强制显示区间）
# ---------------------------------------------------------------------------
def test_probability_interval_brackets_point_estimate() -> None:
    result = _estimate()
    interval = probability_interval(result, PARAMS)
    assert interval is not None
    low, high = interval
    assert low <= result.probability <= high
    assert PARAMS.prob_clip_low <= low <= high <= PARAMS.prob_clip_high


# ---------------------------------------------------------------------------
# hypothesis 性质测试（§7.2；P3 方向按 §2.1 + §6.2 修正）
# ---------------------------------------------------------------------------
HISTORY_RANKS = st.dictionaries(
    keys=st.sampled_from([2025, 2024, 2023]), values=st.integers(500, 300_000), min_size=3, max_size=3
)


@settings(max_examples=60, deadline=None)
@given(rank=st.integers(1, 300_000), delta=st.integers(1, 60_000), ranks=HISTORY_RANKS)
def test_property_better_student_rank_never_lowers_probability(
    rank: int, delta: int, ranks: dict[int, int]
) -> None:
    """考生位次变小（更强）→ 概率不下降。"""
    assume(rank + delta <= 400_000)
    better = estimate_probability(
        make_student(rank), UNIT, make_history(KEY, ranks), RULE, PARAMS,
        current_total_candidates=400_000,
    )
    worse = estimate_probability(
        make_student(rank + delta), UNIT, make_history(KEY, ranks), RULE, PARAMS,
        current_total_candidates=400_000,
    )
    assert better.probability is not None and worse.probability is not None
    assert better.probability >= worse.probability - 1e-12


@settings(max_examples=60, deadline=None)
@given(plan=st.integers(1, 120), ranks=HISTORY_RANKS)
def test_property_more_plan_never_lowers_probability(plan: int, ranks: dict[int, int]) -> None:
    """计划数增加 → 概率不下降（方向写反是经典事故，必须由性质测试守住）。"""
    base_history = make_history(KEY, ranks, plan_count=20)
    base = estimate_probability(
        make_student(20_000), make_unit(plan_count=20), base_history, RULE, PARAMS,
        current_total_candidates=400_000,
    )
    more = estimate_probability(
        make_student(20_000), make_unit(plan_count=plan), base_history, RULE, PARAMS,
        current_total_candidates=400_000,
    )
    assert base.probability is not None and more.probability is not None
    if plan >= 20:
        assert more.probability >= base.probability - 1e-12


@settings(max_examples=60, deadline=None)
@given(factor=st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False))
def test_property_harder_unit_never_raises_probability(factor: float) -> None:
    """单位历史位次整体变小（更难）→ 概率**不上升**。

    §7.2 原文写作"概率不下降"，与 §2.1（位次数值越小越靠前=越难考）及 §6.2 公式矛盾；
    这里按公式断言（详见 ADR-009）。
    """
    base_ranks = {2025: 9000, 2024: 9500, 2023: 9200}
    scaled = {year: max(1, int(round(value * factor))) for year, value in base_ranks.items()}
    base = estimate_probability(
        make_student(9000), UNIT, make_history(KEY, base_ranks), RULE, PARAMS,
        current_total_candidates=400_000,
    )
    scaled_result = estimate_probability(
        make_student(9000), UNIT, make_history(KEY, scaled), RULE, PARAMS,
        current_total_candidates=400_000,
    )
    assert base.probability is not None and scaled_result.probability is not None
    if factor <= 1.0:  # 更难（位次变小）→ 概率不得上升
        assert scaled_result.probability <= base.probability + 1e-9
    else:  # 更易 → 概率不得下降
        assert scaled_result.probability >= base.probability - 1e-9


@settings(max_examples=40, deadline=None)
@given(
    total_from=st.integers(100_000, 1_000_000),
    total_to=st.integers(100_000, 1_000_000),
)
def test_property_normalization_is_proportional(total_from: int, total_to: int) -> None:
    """位次归一化严格按人数比例缩放（跨年可比性的基石）。"""
    history = make_history(KEY, {2025: 12_000}, total_candidates=total_from)
    result = estimate_probability(
        make_student(12_000), UNIT, history, RULE, PARAMS, current_total_candidates=total_to
    )
    assert result.predicted_min_rank == pytest.approx(12_000 * total_to / total_from, rel=1e-6)


# ---------------------------------------------------------------------------
# Step 8.6 安全闸门（★ 名师铁律 4「保底要真保底」，M6/ADR-015 缺陷 6）
# ---------------------------------------------------------------------------
def test_baodian_requires_enough_history_years() -> None:
    """★ 只有 1 年历史时，即使概率打进 DIAN 区间，也**不得**判为保底。

    真实数据回测里 6 例保底失效**全部**是"只有 1–2 年历史，把某一年的低位当长期底线"
    （兰州工业学院 148,172 → 21,548 这种）。所以年份不足必须降级，而不是照概率标签给。
    """
    one_year = _estimate({2025: 20_000}, rank=1000)  # 考生远优于唯一那一年 → 概率≈0.98
    assert W_SAFETY_YEARS_NOT_ENOUGH in one_year.warnings
    assert one_year.tier is Tier.WEN
    assert one_year.probability is not None and one_year.probability > 0.93  # 原始概率如实保留
    assert any("年可用历史" in reason for reason in one_year.reasons)
    # 原始分层若按概率区间本应是 DIAN —— 降级是刻意的保守
    assert one_year.tier is not Tier.DIAN


def test_two_years_is_still_not_enough_by_default() -> None:
    """2 年历史同样不足（真实数据 2025 回测的窗口正好是 2 年）。"""
    two_years = _estimate({2025: 20_000, 2024: 21_000}, rank=1000)
    assert W_SAFETY_YEARS_NOT_ENOUGH in two_years.warnings
    assert two_years.tier is Tier.WEN


def test_three_years_with_margin_is_allowed_to_be_dian() -> None:
    """三年历史 + 余量足够 → 正常给出 DIAN（不能把闸门做成"永远不给保底"）。"""
    three_years = _estimate({2025: 20_000, 2024: 21_000, 2023: 19_500}, rank=1000)
    assert three_years.tier is Tier.DIAN
    assert W_SAFETY_YEARS_NOT_ENOUGH not in three_years.warnings
    assert W_SAFETY_MARGIN_NOT_MET not in three_years.warnings


def test_three_years_without_margin_is_downgraded() -> None:
    """三年历史但给不出 60% 余量 → 仍降级为 WEN（原有闸门不能被新闸门取代）。

    场景：近三年 1,400/1,420/1,380（考生 1,000 → 概率落在 BAO 区间），
    但最难一年 1,380 < 1,000 × 1.6 = 1,600 → 余量不足，必须降级。
    """
    tight = _estimate({2025: 1_400, 2024: 1_420, 2023: 1_380}, rank=1000)
    assert tight.tier is Tier.WEN
    assert W_SAFETY_MARGIN_NOT_MET in tight.warnings
    assert W_SAFETY_YEARS_NOT_ENOUGH not in tight.warnings
    assert tight.probability is not None and tight.probability >= 0.75  # 原始概率如实保留


def test_min_baodian_years_is_configurable() -> None:
    """参数可调：把门槛降到 1 年时，单年历史可以评上 DIAN（证明闸门读的是 ModelParams）。"""
    history = make_history(KEY, {2025: 20_000})
    relaxed = estimate_probability(
        make_student(1000),
        UNIT,
        history,
        RULE,
        ModelParams(min_baodian_years=1),
        current_total_candidates=400_000,
    )
    assert relaxed.tier is Tier.DIAN
    assert W_SAFETY_YEARS_NOT_ENOUGH not in relaxed.warnings
