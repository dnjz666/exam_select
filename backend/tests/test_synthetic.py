"""模拟数据生成器测试（M1）：确定性、数据量、来源标记、注入规律可检出。"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

import pytest

from app.core.models import ModelParams
from app.etl.synthetic import (
    CURRENT_YEAR,
    HISTORY_YEARS,
    SEED,
    PROVINCE_PROFILES,
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
    for name in ("volatile", "plan_spike", "new_major", "small_plan", "collected", "derived"):
        assert len(injections[name]) >= 100, (name, len(injections[name]))


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


def test_new_major_injection_has_no_history(dataset) -> None:
    """新增专业必须完全没有历史行（M2 必须走 Step 0 回退，禁止编造概率）。"""
    units_with_history = {h["unit_key"] for h in dataset.admission_history}
    new_major = set(dataset.injections["new_major"])
    all_unit_keys = {_unit_key(u["unit_id"]) for u in dataset.admission_units}
    assert len(new_major) >= 100
    assert new_major <= all_unit_keys  # 注入清单必须指向真实存在的单位
    assert not (new_major & units_with_history)


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
