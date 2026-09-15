"""志愿表生成测试（AGENTS.md §6.7）：配额、借位、排序、局部搜索、去重、顺序志愿分支。"""

from __future__ import annotations

import pytest

from app.core.models import (
    BatchRule,
    Confidence,
    ModelParams,
    ScoredUnit,
    Tier,
    UnitType,
    VerifiedStatus,
)
from app.core.planner import dian_required, generate_plan
from app.core.rules import get_rule

from factories import make_student, make_unit

PARAMS = ModelParams()
ZJ = get_rule("zhejiang")
SH = get_rule("shanghai")


_DEFAULT_BATCH = {"zhejiang": "zhejiang.public.seg1", "shanghai": "shanghai.undergrad.regular"}


def _scored(
    index: int,
    tier: Tier,
    utility: float,
    *,
    province: str = "zhejiang",
    batch: str | None = None,
    **unit_kwargs,
) -> ScoredUnit:
    unit = make_unit(
        province=province,
        batch=batch or _DEFAULT_BATCH[province],
        college=f"{5000 + index}",
        major=f"1005{index:02d}",
        **unit_kwargs,
    )
    probability = {
        Tier.CHONG: 0.25,
        Tier.WEN: 0.6,
        Tier.BAO: 0.85,
        Tier.DIAN: 0.96,
        Tier.TOO_RISKY: 0.05,
        Tier.NO_DATA: None,
    }[tier]
    return ScoredUnit(
        unit=unit,
        probability=probability,
        tier=tier,
        confidence=Confidence.HIGH,
        utility=utility,
    )


def _pool(counts: dict[Tier, int], utility: float, offset: int = 0) -> list[ScoredUnit]:
    pool: list[ScoredUnit] = []
    index = offset
    for tier, count in counts.items():
        for _ in range(count):
            pool.append(_scored(index, tier, utility))
            index += 1
    return pool


def test_dian_required_rules() -> None:
    assert dian_required(ZJ.main_batch(), PARAMS) == 4  # max(3, ceil(0.05*80))
    assert dian_required(SH.main_batch(), PARAMS) == 3  # max(3, ceil(0.05*24)=2)
    tiny = BatchRule(
        batch_code="x.y",
        batch_name="小批次",
        unit_type=UnitType.MAJOR_COLLEGE,
        max_volunteers=6,
        has_major_adjustment=False,
        is_parallel=True,
        source_url="u",
        source_quote="q",
        verified_status=VerifiedStatus.PRIMARY,
        verified_year=2026,
    )
    assert dian_required(tiny, PARAMS) == PARAMS.min_dian_when_small_plan


def test_plan_structure_for_parallel_batch() -> None:
    batch = ZJ.main_batch()
    candidates = _pool({Tier.CHONG: 40, Tier.WEN: 60, Tier.BAO: 40, Tier.DIAN: 20}, utility=0.5)
    plan = generate_plan(make_student(), candidates, ZJ, batch, PARAMS, plan_id="p")
    assert 0 < len(plan.items) <= batch.max_volunteers
    assert plan.violations == []
    assert sum(plan.tier_distribution.values()) == len(plan.items)
    assert plan.tier_distribution.get(Tier.DIAN.value, 0) >= dian_required(batch, PARAMS)
    assert plan.items[-1].tier in (Tier.BAO, Tier.DIAN)  # 最后一档必须兜底
    assert plan.total_utility == pytest.approx(sum(item.utility for item in plan.items))
    assert plan.rule.max_volunteers == batch.max_volunteers


def test_plan_excludes_no_data_candidates() -> None:
    batch = ZJ.main_batch()
    candidates = _pool({Tier.WEN: 30, Tier.BAO: 10, Tier.DIAN: 5}, utility=0.5)
    candidates.append(_scored(999, Tier.NO_DATA, 0.0))
    plan = generate_plan(make_student(), candidates, ZJ, batch, PARAMS)
    assert all(item.tier is not Tier.NO_DATA for item in plan.items)
    assert any("NO_DATA" in warning for warning in plan.warnings)


def test_plan_dedups_major_groups() -> None:
    batch = SH.main_batch()
    candidates = [
        _scored(1, Tier.WEN, 0.6, province="shanghai", group="G1", unit_type=batch.unit_type),
        _scored(2, Tier.WEN, 0.9, province="shanghai", group="G1", unit_type=batch.unit_type),
        _scored(3, Tier.BAO, 0.7, province="shanghai", group="G2", unit_type=batch.unit_type),
        _scored(4, Tier.DIAN, 0.8, province="shanghai", group="G3", unit_type=batch.unit_type),
    ]
    # 同一组的两条候选（不同 unit_id 但同 college+group）→ 只保留效用更高者
    candidates[1].unit = candidates[1].unit.model_copy(
        update={"college_id": candidates[0].unit.college_id}
    )
    plan = generate_plan(
        make_student(province="shanghai"), candidates, SH, batch, PARAMS, obey_adjustment=True
    )
    groups = [(item.unit.college_id, item.unit.group_code) for item in plan.items]
    assert len(groups) == len(set(groups))
    assert plan.violations == []
    assert all(item.obey_adjustment is True for item in plan.items)


def test_plan_borrows_conservatively_when_tier_short() -> None:
    batch = ZJ.main_batch()
    # CHONG 层完全空缺 → 只能从更保守的层借位
    candidates = _pool({Tier.WEN: 40, Tier.BAO: 40, Tier.DIAN: 20}, utility=0.5)
    plan = generate_plan(make_student(), candidates, ZJ, batch, PARAMS)
    assert plan.tier_distribution.get(Tier.CHONG.value, 0) == 0
    assert any("借入" in warning for warning in plan.warnings)


def test_plan_respects_preference_order() -> None:
    batch = ZJ.main_batch()
    candidates = _pool({Tier.WEN: 30, Tier.BAO: 10, Tier.DIAN: 5}, utility=0.5)
    wanted = candidates[7].unit.unit_id
    plan = generate_plan(
        make_student(),
        candidates,
        ZJ,
        batch,
        PARAMS,
        preference_order=[wanted, *[c.unit.unit_id for c in candidates if c.unit.unit_id != wanted]],
    )
    assert plan.items[0].unit.unit_id == wanted


def test_local_search_improves_total_utility() -> None:
    batch = ZJ.main_batch()
    candidates = [
        *_pool({Tier.CHONG: 20}, utility=0.10, offset=0),
        *_pool({Tier.WEN: 32}, utility=0.20, offset=100),
        *_pool({Tier.BAO: 20}, utility=0.30, offset=200),
        *_pool({Tier.DIAN: 8}, utility=0.40, offset=300),
    ]
    high_utility = [_pool({Tier.DIAN: 5}, utility=0.95, offset=400)]
    plan = generate_plan(make_student(), [*candidates, *high_utility[0]], ZJ, batch, PARAMS)
    greedy_baseline = 20 * 0.10 + 32 * 0.20 + 20 * 0.30 + 8 * 0.40
    assert plan.total_utility > greedy_baseline  # swap 提升了总效用
    assert any(
        item.unit.unit_id in {c.unit.unit_id for c in high_utility[0]} for item in plan.items
    )


def test_sequential_batch_uses_utility_order_without_quota() -> None:
    batch = ZJ.get_batch("zhejiang.advance.college")
    candidates = [
        _scored(1, Tier.WEN, 0.30, batch=batch.batch_code, group="G1", unit_type=batch.unit_type),
        _scored(2, Tier.BAO, 0.95, batch=batch.batch_code, group="G2", unit_type=batch.unit_type),
        _scored(3, Tier.CHONG, 0.60, batch=batch.batch_code, group="G3", unit_type=batch.unit_type),
    ]
    plan = generate_plan(make_student(), candidates, ZJ, batch, PARAMS, obey_adjustment=True)
    assert len(plan.items) <= batch.max_volunteers
    assert plan.items[0].utility == max(candidate.utility for candidate in candidates)  # 最想去放第一
    assert any("顺序志愿" in warning for warning in plan.warnings)
    assert plan.violations == []


def test_sequential_batch_flags_missing_adjustment_choice() -> None:
    batch = ZJ.get_batch("zhejiang.advance.college")
    candidates = [
        _scored(1, Tier.WEN, 0.5, batch=batch.batch_code, group="G1", unit_type=batch.unit_type)
    ]
    plan = generate_plan(make_student(), candidates, ZJ, batch, PARAMS, obey_adjustment=None)
    assert {violation.code for violation in plan.violations} == {"ADJUSTMENT_UNSET"}


def test_empty_candidate_pool_yields_empty_plan() -> None:
    batch = ZJ.main_batch()
    plan = generate_plan(make_student(), [], ZJ, batch, PARAMS)
    assert plan.items == []
    assert plan.tier_distribution == {}
    assert {violation.code for violation in plan.violations} == {"EMPTY_PLAN"}
