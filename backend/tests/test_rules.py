"""规则包测试（M1）：来源纪律、批次级分支、校验与配额。"""

from __future__ import annotations

import pytest

from app.core.models import (
    AdmissionUnit,
    BatchRule,
    PlanItem,
    SubjectRequirement,
    Tier,
    UnitType,
    VerifiedStatus,
    VolunteerPlan,
)
from app.core.rules import PROVINCES, RULES, all_rules, batch_by_code, get_rule
from app.core.rules.base import (
    ADJUSTMENT_NOT_APPLICABLE,
    ADJUSTMENT_UNSET,
    DUPLICATE_GROUP,
    DUPLICATE_UNIT,
    EMPTY_PLAN,
    EXCEED_MAX_VOLUNTEERS,
    UNIT_TYPE_MISMATCH,
    distribute_quota,
    validate_tier_quota,
)


def _unit(
    province: str,
    batch: BatchRule,
    *,
    college: str = "1001",
    group: str | None = None,
    major: str = "100111",
    unit_type: UnitType | None = None,
) -> AdmissionUnit:
    group_part = group or "NA"
    return AdmissionUnit(
        unit_id=f"{province}-2025-{college}-{group_part}-{major}",
        unit_type=unit_type or batch.unit_type,
        province=province,
        year=2025,
        batch=batch.batch_code,
        college_id=f"{province}-{college}",
        group_code=group,
        group_name=f"第{group}组" if group else None,
        major_id=f"工学-{major}",
        major_name="计算机科学与技术",
        subject_requirement=SubjectRequirement(),
        plan_count=20,
        tuition=6000,
    )


def _plan(rule_province: str, batch: BatchRule, items: list[PlanItem]) -> VolunteerPlan:
    rule = get_rule(rule_province)
    return VolunteerPlan(
        id="plan-1",
        student_id="stu-1",
        province=rule_province,
        rule=rule.rule_info(batch),
        items=items,
    )


def _item(position: int, unit: AdmissionUnit, obey: bool | None = None) -> PlanItem:
    return PlanItem(position=position, unit=unit, tier=Tier.WEN, probability=0.6, obey_adjustment=obey)


# ---------------------------------------------------------------------------
# 来源纪律
# ---------------------------------------------------------------------------
def test_six_provinces_registered() -> None:
    assert PROVINCES == ("beijing", "hainan", "shandong", "shanghai", "tianjin", "zhejiang")
    assert set(RULES) == set(PROVINCES)


def test_subject_pool_has_source_discipline() -> None:
    """选考科目池是**规则事实**（AGENTS.md §8.1 Step 2），与批次同受来源纪律约束。"""
    for rule in all_rules():
        pool = rule.subject_pool
        assert pool is not None, rule.province
        assert pool.province == rule.province
        assert pool.choose == 3
        assert len(pool.subjects) >= pool.choose
        assert len(set(pool.subjects)) == len(pool.subjects), rule.province
        assert pool.source_url, rule.province
        assert pool.source_quote, rule.province
        assert pool.verified_year is not None, rule.province


def test_only_zhejiang_has_technology_subject() -> None:
    """浙江独有"技术"科目；其余五省 6 选 3，混入"技术"即为错误配置。"""
    zhejiang = get_rule("zhejiang").subject_pool
    assert zhejiang is not None and zhejiang.mode == "7选3"
    assert "技术" in zhejiang.subjects
    assert len(zhejiang.subjects) == 7
    for province in ("shanghai", "beijing", "shandong", "tianjin", "hainan"):
        pool = get_rule(province).subject_pool
        assert pool is not None and pool.mode == "6选3"
        assert len(pool.subjects) == 6
        assert "技术" not in pool.subjects
        assert "信息技术" not in pool.subjects


def test_subject_pool_uses_plan_canonical_names() -> None:
    """科目名必须与招生计划选考要求字段同口径（统一用"生物"，而非官方行文的"生物学"）。

    官方行文"生物/生物学"并存，硬字符串匹配会漏 → 池内出现的科目必须能直接与
    ``AdmissionUnit.subject_requirement.subjects`` 比较。
    """
    for rule in all_rules():
        pool = rule.subject_pool
        assert pool is not None
        assert "生物学" not in pool.subjects, rule.province
        assert "生物" in pool.subjects, rule.province
        assert "政治" not in pool.subjects, rule.province
        assert "思想政治" in pool.subjects, rule.province



def test_every_batch_has_source_discipline() -> None:
    """任何规则数字必须带 source_url + source_quote + verified_year，且批次编码唯一。"""
    for rule in all_rules():
        assert rule.source_problems() == [], rule.province


def test_assumptions_never_marked_primary() -> None:
    """假设必须可见：带 assumptions 的批次不得标 PRIMARY。"""
    for rule in all_rules():
        for batch in rule.batches:
            if batch.assumptions:
                assert batch.verified_status is not VerifiedStatus.PRIMARY, batch.batch_code


def test_tianjin_hainan_are_secondary_redline() -> None:
    """天津/海南为转载源：升级 PRIMARY 前不得用于真实填报（UI 横幅依据）。"""
    for province in ("tianjin", "hainan"):
        assert all(
            b.verified_status is VerifiedStatus.SECONDARY for b in get_rule(province).batches
        ), province


def test_sequential_batches_have_no_quota_and_are_marked() -> None:
    sequential = [b for rule in all_rules() for b in rule.batches if not b.is_parallel]
    assert sequential, "至少应有一个顺序志愿批次（浙江提前批 / 上海提前批等）"
    for batch in sequential:
        assert batch.tiers_quota is None, batch.batch_code
        assert batch.verified_status is not VerifiedStatus.PRIMARY or not batch.assumptions


def test_main_batch_is_parallel() -> None:
    for rule in all_rules():
        assert rule.main_batch().is_parallel, rule.province


def test_adjustment_batches_are_major_group_only() -> None:
    for rule in all_rules():
        for batch in rule.batches:
            if batch.has_major_adjustment:
                assert batch.unit_type is UnitType.MAJOR_GROUP, batch.batch_code
                assert batch.majors_per_group is None or batch.majors_per_group > 0


def test_zhejiang_advance_is_sequential_five() -> None:
    """ADR-006 的立论案例：浙江提前批 5 个院校传统（顺序）志愿。"""
    _, batch = batch_by_code("zhejiang.advance.college")
    assert batch.is_parallel is False
    assert batch.max_volunteers == 5
    assert batch.majors_per_group == 6
    assert batch.has_major_adjustment is True


def test_unknown_province_and_batch_raise() -> None:
    with pytest.raises(KeyError):
        get_rule("jiangsu")
    with pytest.raises(KeyError):
        batch_by_code("zhejiang.not.exists")
    with pytest.raises(KeyError):
        get_rule("zhejiang").get_batch("nope")


def test_batch_by_code_roundtrip() -> None:
    rule, batch = batch_by_code("shanghai.undergrad.regular")
    assert rule.province == "shanghai"
    assert batch.max_volunteers == 24 and batch.majors_per_group == 4
    assert batch.admission_ratio == "1:1"
    assert batch.adjustment_scope is not None


# ---------------------------------------------------------------------------
# 配额
# ---------------------------------------------------------------------------
def test_distribute_quota_sums_to_total_and_is_deterministic() -> None:
    weights = {"CHONG": 0.25, "WEN": 0.40, "BAO": 0.25, "DIAN": 0.10}
    first = distribute_quota(weights, 80)
    assert sum(first.values()) == 80
    assert first == distribute_quota(weights, 80)
    assert first[Tier.WEN] >= first[Tier.CHONG]


def test_distribute_quota_edge_cases() -> None:
    weights = {"CHONG": 0.25, "WEN": 0.40, "BAO": 0.25, "DIAN": 0.10}
    assert sum(distribute_quota(weights, 0).values()) == 0
    assert sum(distribute_quota(weights, 7).values()) == 7
    with pytest.raises(ValueError):
        distribute_quota({"NOT_A_TIER": 1.0}, 10)  # 未知分层
    with pytest.raises(ValueError):
        distribute_quota({"CHONG": 0.0, "WEN": 0.0, "BAO": 0.0, "DIAN": 0.0}, 10)  # 权重全零
    with pytest.raises(ValueError):
        distribute_quota(weights, -1)


def test_validate_tier_quota_reports_problems() -> None:
    assert validate_tier_quota(None) == []
    assert validate_tier_quota({"CHONG": 0.5, "WEN": 0.5}) == []
    problems = validate_tier_quota({"CHONG": 0.5, "WEN": 0.6})
    assert problems and "1.0" in problems[0]
    assert validate_tier_quota({"CHONG": 0.5, "WEN": 0.5, "X": 0.0}) != []


def test_default_quota_parallel_vs_sequential() -> None:
    rule = get_rule("zhejiang")
    parallel = rule.default_quota(rule.main_batch())
    assert sum(parallel.values()) == 80
    sequential = rule.default_quota(rule.get_batch("zhejiang.advance.college"))
    assert sequential == {}


# ---------------------------------------------------------------------------
# 批次级校验
# ---------------------------------------------------------------------------
def test_validate_plan_clean_major_college_passes() -> None:
    rule = get_rule("zhejiang")
    batch = rule.main_batch()
    plan = _plan("zhejiang", batch, [_item(i + 1, _unit("zhejiang", batch, major=f"1002{i}")) for i in range(5)])
    assert rule.validate_plan(plan, batch) == []


def test_validate_plan_clean_major_group_passes() -> None:
    rule = get_rule("shanghai")
    batch = rule.main_batch()
    items = [
        _item(1, _unit("shanghai", batch, group="G1", major="100201"), obey=True),
        _item(2, _unit("shanghai", batch, group="G2", major="100202"), obey=True),  # 同组只能填一次
        _item(3, _unit("shanghai", batch, group="G3", major="100203"), obey=True),
    ]
    assert rule.validate_plan(_plan("shanghai", batch, items), batch) == []


def test_validate_plan_exceeds_max_volunteers() -> None:
    rule = get_rule("shanghai")
    batch = rule.main_batch()
    items = [
        _item(i + 1, _unit("shanghai", batch, group=f"G{i}", major=f"1003{i}"), obey=True)
        for i in range(batch.max_volunteers + 1)
    ]
    codes = {v.code for v in rule.validate_plan(_plan("shanghai", batch, items), batch)}
    assert EXCEED_MAX_VOLUNTEERS in codes


def test_validate_plan_duplicate_group_rejected() -> None:
    rule = get_rule("shanghai")
    batch = rule.main_batch()
    items = [
        _item(1, _unit("shanghai", batch, group="G1", major="100401"), obey=True),
        _item(2, _unit("shanghai", batch, group="G1", major="100402"), obey=True),
    ]
    codes = {v.code for v in rule.validate_plan(_plan("shanghai", batch, items), batch)}
    assert DUPLICATE_GROUP in codes


def test_validate_plan_duplicate_unit_rejected() -> None:
    rule = get_rule("shandong")
    batch = rule.main_batch()
    unit = _unit("shandong", batch, major="100501")
    items = [_item(1, unit), _item(2, unit)]
    codes = {v.code for v in rule.validate_plan(_plan("shandong", batch, items), batch)}
    assert DUPLICATE_UNIT in codes


def test_validate_plan_adjustment_rules() -> None:
    sh = get_rule("shanghai")
    sh_batch = sh.main_batch()
    unset = [_item(1, _unit("shanghai", sh_batch, group="G1"), obey=None)]
    assert ADJUSTMENT_UNSET in {v.code for v in sh.validate_plan(_plan("shanghai", sh_batch, unset), sh_batch)}

    zj = get_rule("zhejiang")
    zj_batch = zj.main_batch()
    wrong = [_item(1, _unit("zhejiang", zj_batch), obey=True)]  # 专业+院校无调剂概念
    assert ADJUSTMENT_NOT_APPLICABLE in {
        v.code for v in zj.validate_plan(_plan("zhejiang", zj_batch, wrong), zj_batch)
    }


def test_validate_plan_unit_type_and_empty() -> None:
    rule = get_rule("beijing")
    batch = rule.main_batch()
    mismatch = [_item(1, _unit("beijing", batch, unit_type=UnitType.MAJOR_COLLEGE), obey=True)]
    assert UNIT_TYPE_MISMATCH in {
        v.code for v in rule.validate_plan(_plan("beijing", batch, mismatch), batch)
    }
    assert EMPTY_PLAN in {v.code for v in rule.validate_plan(_plan("beijing", batch, []), batch)}


def test_sequential_batch_does_not_run_gradient_quota_checks() -> None:
    """顺序志愿批次：不做冲稳保梯度校验（ADR-006），仅做结构校验。"""
    rule = get_rule("zhejiang")
    batch = rule.get_batch("zhejiang.advance.college")
    items = [_item(i + 1, _unit("zhejiang", batch, college=f"20{i}", group=None, major=f"1006{i}"), obey=True) for i in range(3)]
    violations = rule.validate_plan(_plan("zhejiang", batch, items), batch)
    assert violations == []
