"""模拟数据生成器测试（M1）：确定性、数据量、来源标记、注入规律可检出。"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

import pytest

from app.core.models import ModelParams
from app.etl.synthetic import (
    CURRENT_YEAR,
    GROUND_TRUTH_YEAR,
    HISTORY_YEARS,
    PLAN_YEARS,
    PROVINCE_PROFILES,
    SEED,
    generate,
)


@pytest.fixture(scope="module")
def dataset():
    return generate()


def test_determinism_same_seed_same_digest() -> None:
    """相同 seed 必须逐字节一致（M1 完成定义：数据可重复生成且一致）。"""
    assert generate(SEED).digest() == generate(SEED).digest()


def test_different_seed_changes_data() -> None:
    assert generate(SEED).digest() != generate(SEED + 1).digest()


def test_minimum_volumes(dataset) -> None:
    counts = dataset.counts()
    assert counts["colleges"] >= 300, counts  # M1：院校库 300+ 所
    assert counts["majors"] >= 500, counts  # M1：专业库 500+ 个
    assert counts["admission_units"] > 1000
    assert counts["admission_plans"] > counts["admission_units"]  # 每单位多年计划快照
    assert counts["admission_history"] > 1000
    assert set(PROVINCE_PROFILES) <= {u["province"] for u in dataset.admission_units}


def test_every_province_pool_contains_its_own_colleges(dataset) -> None:
    """★ 回归：每个省的候选院校池**必须包含本省院校**。

    原实现在合并 ``local + strong + sampled`` 之后按院校 id 排序再截断 ``[:MAX]``，
    而 id 以省名开头 → 排在后半段的省份本省院校被整段丢掉。
    实测后果：浙江/上海/山东/天津的考生候选池里**本省院校数为 0**
    （浙江考生永远看不到浙江大学），外省普通院校的抽样名额也被截断吃掉。
    这条测试锁住修复，防止上限或排序方式再被改回去。
    """
    colleges = {c["id"]: c for c in dataset.colleges}
    for province in PROVINCE_PROFILES:
        units = [u for u in dataset.admission_units if u["province"] == province]
        assert units, province
        local_colleges = {
            u["college_id"] for u in units if colleges[u["college_id"]]["province"] == province
        }
        assert local_colleges, (
            f"{province} 的候选池里没有任何本省院校——截断又把本省院校吃掉了（见 ADR-014）"
        )


def test_candidate_pool_keeps_out_of_province_sample(dataset) -> None:
    """外省普通院校的抽样名额也不能被截断吃掉（否则池子只剩 985/211，不符合真实分布）。"""
    import json

    colleges = {c["id"]: c for c in dataset.colleges}
    tiers = {"985", "211", "双一流"}
    for province in PROVINCE_PROFILES:
        ids = {u["college_id"] for u in dataset.admission_units if u["province"] == province}
        weak = [
            i
            for i in ids
            if colleges[i]["province"] != province
            and not (tiers & set(json.loads(colleges[i]["level_tags"])))
        ]
        assert weak, f"{province} 候选池里没有外省普通院校（抽样名额被截断吃掉？）"


def test_every_row_is_synthetic_with_source(dataset) -> None:
    """合规红线：所有行必须 is_synthetic=1、有 source_url、历史行 verified=0。"""
    for name in dataset._TABLES:
        rows = getattr(dataset, name)
        assert all(r["is_synthetic"] is True for r in rows), name
        assert all(str(r["source_url"]).startswith("synthetic://") for r in rows), name
    assert all(r["verified"] is False for r in dataset.admission_history)


def test_no_duplicate_keys(dataset) -> None:
    units = Counter(u["unit_id"] for u in dataset.admission_units)
    assert max(units.values()) == 1
    plans = Counter((p["unit_key"], p["year"]) for p in dataset.admission_plans)
    assert max(plans.values()) == 1
    history = Counter((h["unit_key"], h["year"], h["is_collected"]) for h in dataset.admission_history)
    assert max(history.values()) == 1


def test_score_table_is_monotonic_and_closes_to_total(dataset) -> None:
    stats = {(s["province"], s["year"]): s["total_candidates"] for s in dataset.province_year_stats}
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in dataset.score_rank_table:
        grouped[(row["province"], row["year"])].append(row)
    assert set(grouped) == set(stats)
    for key, rows in grouped.items():
        rows.sort(key=lambda r: -r["score"])
        cum = [r["cumulative_rank"] for r in rows]
        assert cum == sorted(cum), key  # 分数下降时累计位次不减
        assert all(r["count_at_score"] >= 0 for r in rows), key
        assert rows[-1]["cumulative_rank"] == stats[key], key


def test_units_respect_batch_mode_and_group_limits(dataset) -> None:
    """浙江/山东（专业+院校）group_code 必须为 None；院校专业组模式组内专业数不超上限。"""
    from app.core.rules import get_rule

    for province in ("zhejiang", "shandong"):
        batch = get_rule(province).main_batch()
        units = [u for u in dataset.admission_units if u["province"] == province]
        assert units
        assert all(u["group_code"] is None for u in units)
        assert all(u["unit_type"] == batch.unit_type.value for u in units)

    for province in ("shanghai", "beijing", "tianjin", "hainan"):
        batch = get_rule(province).main_batch()
        per_group = Counter(
            (u["college_id"], u["group_code"])
            for u in dataset.admission_units
            if u["province"] == province
        )
        assert per_group
        if batch.majors_per_group is not None:  # 天津组内专业数未核实（None）→ 不设断言
            assert max(per_group.values()) <= batch.majors_per_group, province


def test_injected_patterns_are_present(dataset) -> None:
    injections = dataset.injections
    for name in (
        "volatile",
        "trend_hot",
        "trend_cold",
        "plan_spike_live",
        "plan_spike_backtest",
        "new_major_2025",
        "new_major_2026",
        "small_plan",
        "collected",
        "derived",
    ):
        assert len(injections[name]) >= 50, (name, len(injections[name]))


def test_plan_changes_causally_shift_cutoff_rank(dataset) -> None:
    """M2 修复的真实缺陷：计划数必须**因果地**影响投档位次（否则 §6.2 Step 4 无从验证）。

    做法：对"计划突减"的注入单位，比较其 2025（突减年）与实际位次的关系，
    验证同层次随机单位里"计划增 → 位次后移"的方向性成立。
    """
    plans: dict[str, dict[int, int]] = defaultdict(dict)
    for row in dataset.admission_plans:
        plans[row["unit_key"]][row["year"]] = row["plan_count"]
    ranks = {(row["unit_key"], row["year"]): row["min_rank"] for row in dataset.admission_history}

    pairs: list[tuple[float, float]] = []  # (计划变动率, 位次变动率)
    for key, years in plans.items():
        if 2024 not in years or 2025 not in years:
            continue
        if (key, 2024) not in ranks or (key, 2025) not in ranks:
            continue
        if not years[2024] or not ranks[key, 2024]:
            continue
        plan_delta = (years[2025] - years[2024]) / years[2024]
        rank_delta = (ranks[key, 2025] - ranks[key, 2024]) / ranks[key, 2024]
        pairs.append((plan_delta, rank_delta))

    assert len(pairs) > 1000
    # 只挑出计划大幅变动的样本，方向必须为正相关（计划增 → 位次变大）
    big = [(p, r) for p, r in pairs if abs(p) >= 0.3]
    assert len(big) >= 100
    same_direction = sum(1 for p, r in big if p * r > 0)
    assert same_direction / len(big) > 0.55, f"计划与位次同向比例仅 {same_direction / len(big):.2f}"


def test_volatile_injection_is_detectable_as_big_small_year(dataset) -> None:
    """注入的"大小年"必须真的能被她 cv 检出（否则 M2 无从验证收缩逻辑）。"""
    params = ModelParams()
    hist: dict[str, list[dict]] = defaultdict(list)
    for row in dataset.admission_history:
        hist[row["unit_key"]].append(row)

    def cv(rows: list[dict]) -> float:
        values = [r["min_rank"] / r["total_candidates"] for r in rows]
        mean = statistics.fmean(values)
        return statistics.pstdev(values) / mean if mean else 0.0

    volatile = set(dataset.injections["volatile"])
    vol_cvs = [cv(rows) for key, rows in hist.items() if key in volatile and len(rows) >= 2]
    normal_cvs = [cv(rows) for key, rows in hist.items() if key not in volatile and len(rows) >= 2]

    assert len(vol_cvs) >= 100
    assert statistics.fmean(vol_cvs) > params.cv_threshold
    assert sum(1 for c in vol_cvs if c > params.cv_threshold) / len(vol_cvs) > 0.8
    assert statistics.fmean(normal_cvs) < params.cv_threshold


def _unit_key(unit_id: str) -> str:
    """unit_id = province-year-college-group-major → unit_key（去年份）。"""
    parts = unit_id.split("-")
    return "-".join([parts[0], *parts[2:]])


def test_new_major_injections_have_expected_history(dataset) -> None:
    """两类"新增专业"的语义必须严格区分（ADR-009）：

    - ``new_major_2026``：完全无历史行（2026 年新增，预测只能走 Step 0）；
    - ``new_major_2025``：只有 2025（地面真值年）行，2022–2024 为空
      → 回测时可用它检验 Step 0 类比回退。
    """
    rows_by_key: dict[str, list[dict]] = defaultdict(list)
    for row in dataset.admission_history:
        rows_by_key[row["unit_key"]].append(row)
    all_unit_keys = {_unit_key(u["unit_id"]) for u in dataset.admission_units}

    fresh_2026 = set(dataset.injections["new_major_2026"])
    fresh_2025 = set(dataset.injections["new_major_2025"])
    assert len(fresh_2026) >= 100 and len(fresh_2025) >= 100
    assert fresh_2026 <= all_unit_keys and fresh_2025 <= all_unit_keys
    assert not fresh_2026 & fresh_2025

    assert all(key not in rows_by_key for key in fresh_2026)
    for key in fresh_2025:
        years = {row["year"] for row in rows_by_key[key]}
        assert years == {GROUND_TRUTH_YEAR}, (key, years)


def test_timeline_supports_both_prediction_and_backtest(dataset) -> None:
    """时间轴（ADR-009）：填报年 2026、历史 2022–2025、计划快照 2022–2026。"""
    assert CURRENT_YEAR == 2026
    assert GROUND_TRUTH_YEAR == 2025
    assert set(HISTORY_YEARS) == {2022, 2023, 2024, 2025}
    years_with_history = {row["year"] for row in dataset.admission_history}
    assert years_with_history == set(HISTORY_YEARS)
    plan_years = {row["year"] for row in dataset.admission_plans}
    assert plan_years == set(PLAN_YEARS)
    assert {u["year"] for u in dataset.admission_units} == {CURRENT_YEAR}
    # 回测需要地面真值：2025 必须有实际行，且 2022–2024 也必须有（供 Y=2025 预测）
    counts = {year: sum(1 for r in dataset.admission_history if r["year"] == year) for year in HISTORY_YEARS}
    for year in (2022, 2023, 2024, GROUND_TRUTH_YEAR):
        assert counts[year] > 1000, counts


def test_plan_snapshot_matches_units_for_current_year(dataset) -> None:
    current = {p["unit_key"]: p["plan_count"] for p in dataset.admission_plans if p["year"] == CURRENT_YEAR}
    for unit in dataset.admission_units:
        assert current[_unit_key(unit["unit_id"])] == unit["plan_count"]


def test_history_years_and_quality_flags(dataset) -> None:
    assert {h["year"] for h in dataset.admission_history} == set(HISTORY_YEARS)
    for row in dataset.admission_history:
        assert row["data_quality"] in ("OK", "DERIVED", "COLLECTED")
        assert bool(row["is_collected"]) == (row["data_quality"] == "COLLECTED")
        assert row["total_candidates"] > 0
