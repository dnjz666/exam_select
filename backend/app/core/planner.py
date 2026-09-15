"""志愿表生成与优化（AGENTS.md §6.7）。

算法（贪心 + 分层配额 + 局部搜索 + 去重）
----------------------------------------
1. 按 §6.3 配额从各 Tier 取候选（层内按 ``utility`` 降序）；
2. 某层候选不足时**向更保守的方向借位**（保证兜底）；
3. 全局排序：投影为「考生意愿序」，但强制最后一档是 BAO/DIAN；
4. 局部搜索：在不破坏结构约束的前提下 swap 提升总效用；
5. 去重：专业+院校可同校多专业；**院校专业组一个组只能填一次**。

顺序志愿批次（``is_parallel=False``）**不做冲稳保配额校验**（ADR-006）：
第一志愿 = 效用最高（最想去），保底职责不得交给该批次。

``tier == NO_DATA`` 的候选（``probability is None``）**不参与志愿表生成**（§6.3）。
纯函数，无 IO（ADR-003）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.core.models import (
    BatchRule,
    ModelParams,
    PlanItem,
    ScoredUnit,
    StudentProfile,
    Tier,
    VolunteerPlan,
)
from app.core.rules.base import ProvinceRule

#: 平行志愿的默认递进顺序（冲 → 稳 → 保 → 垫）
_TIER_ORDER: tuple[Tier, ...] = (Tier.CHONG, Tier.WEN, Tier.BAO, Tier.DIAN)
#: 保守程度从高到低（借位时使用）
_CONSERVATIVE_FIRST: tuple[Tier, ...] = (Tier.DIAN, Tier.BAO, Tier.WEN, Tier.CHONG)
#: TOO_RISKY 的下界（仅用于文案；数值来自 ModelParams.tier_bounds 的语义）
_TOO_RISKY_FLOOR = 0.10


def _tier_index(tier: Tier) -> int:
    """分层排序位置；不在冲稳保垫之列（TOO_RISKY / NO_DATA）一律排到最后。"""
    return _TIER_ORDER.index(tier) if tier in _TIER_ORDER else len(_TIER_ORDER)

MAX_LOCAL_SEARCH_ITERATIONS = 20
LOCAL_SEARCH_POOL_LIMIT = 200


def dian_required(batch: BatchRule, params: ModelParams) -> int:
    """垫底志愿下限（§6.3 结构校验；专门用于"保底要真保底"）。"""
    if batch.max_volunteers < 10:
        return params.min_dian_when_small_plan
    return max(params.min_dian_abs, int(math.ceil(params.min_dian_ratio * batch.max_volunteers)))


def _dedup(candidates: Sequence[ScoredUnit], batch: BatchRule) -> tuple[list[ScoredUnit], list[str]]:
    """去重并剔除 NO_DATA / TOO_RISKY；返回 (候选, 警告)。"""
    warnings: list[str] = []
    no_data = [c for c in candidates if c.tier is Tier.NO_DATA or c.probability is None]
    too_risky = [c for c in candidates if c.tier is Tier.TOO_RISKY and c.probability is not None]
    usable = [
        c
        for c in candidates
        if c.tier not in (Tier.NO_DATA, Tier.TOO_RISKY) and c.probability is not None
    ]
    if no_data:
        warnings.append(
            f"{len(no_data)} 个候选因无可用历史数据（NO_DATA）被排除在志愿表之外（禁止编造概率）。"
        )
    if too_risky:
        # TOO_RISKY（概率 <0.10）默认不进志愿表（§6.3）；显式开启需调用方自行放入 "冲" 之外的位置
        warnings.append(
            f"{len(too_risky)} 个候选概率低于 {_TOO_RISKY_FLOOR:.0%}（TOO_RISKY），默认不参与志愿表生成。"
        )

    chosen: dict[str, ScoredUnit] = {}
    dropped = 0
    for candidate in sorted(usable, key=lambda c: (-c.utility, c.unit.unit_id)):
        key = (
            f"{candidate.unit.college_id}|{candidate.unit.group_code}"
            if batch.has_major_adjustment
            else candidate.unit.unit_id
        )
        if key in chosen:
            dropped += 1
            continue
        chosen[key] = candidate
    if dropped:
        reason = "同组重复" if batch.has_major_adjustment else "同一投档单位重复"
        warnings.append(f"{dropped} 个候选因{reason}被去重（院校专业组一个组只能填一次）。")
    return list(chosen.values()), warnings


def _allocate(
    candidates: Sequence[ScoredUnit], batch: BatchRule, rule: ProvinceRule, params: ModelParams
) -> tuple[list[ScoredUnit], list[str]]:
    """按配额选候选，候选不足时向更保守方向借位。"""
    warnings: list[str] = []
    quota = rule.default_quota(batch)
    if not quota:  # pragma: no cover - 平行志愿批次必有配额
        quota = {tier: 0 for tier in _TIER_ORDER}

    # 垫底下限优先满足（名师铁律 4）
    required_dian = dian_required(batch, params)
    if quota.get(Tier.DIAN, 0) < required_dian:
        deficit = required_dian - quota.get(Tier.DIAN, 0)
        for donor in (Tier.BAO, Tier.WEN, Tier.CHONG):
            if deficit <= 0:
                break
            movable = min(deficit, quota.get(donor, 0))
            if movable > 0:
                quota[donor] = quota.get(donor, 0) - movable
                quota[Tier.DIAN] = quota.get(Tier.DIAN, 0) + movable
                deficit -= movable
        warnings.append(f"垫底志愿下限 {required_dian} 个高于默认配额，已从更激进的层调入。")

    pools: dict[Tier, list[ScoredUnit]] = {tier: [] for tier in _TIER_ORDER}
    for candidate in candidates:
        if candidate.tier in pools:
            pools[candidate.tier].append(candidate)
    for tier in pools:
        pools[tier].sort(key=lambda c: (-c.utility, c.unit.unit_id))

    selected: list[ScoredUnit] = []
    used_ids: set[str] = set()
    shortfall: dict[Tier, int] = {}
    for tier in _TIER_ORDER:
        want = quota.get(tier, 0)
        pool = [c for c in pools[tier] if c.unit.unit_id not in used_ids]
        take = pool[:want]
        selected.extend(take)
        used_ids.update(c.unit.unit_id for c in take)
        shortfall[tier] = want - len(take)

    # 借位：**优先向更保守的方向借**
    # 保守顺序 = (DIAN, BAO, WEN, CHONG)；某层不足时先取比它更保守的层（索引更小者，
    # 由近及远），最保守层不足时才退向更激进的层。
    for tier in _TIER_ORDER:
        need = shortfall.get(tier, 0)
        if need <= 0:
            continue
        index = _CONSERVATIVE_FIRST.index(tier)
        more_conservative = list(reversed(_CONSERVATIVE_FIRST[:index]))
        less_conservative = list(_CONSERVATIVE_FIRST[index + 1 :])
        for donor in [*more_conservative, *less_conservative]:
            if need <= 0:
                break
            pool = [c for c in pools[donor] if c.unit.unit_id not in used_ids]
            take = pool[:need]
            if take:
                selected.extend(take)
                used_ids.update(c.unit.unit_id for c in take)
                need -= len(take)
                warnings.append(
                    f"{tier.value} 层候选不足，已从更保守的 {donor.value} 层借入 {len(take)} 个志愿。"
                )
        if need > 0:
            warnings.append(f"{tier.value} 层候选不足，且相邻层也无可用候选，缺 {need} 个。")

    # 若总量仍不足，用剩余任意候选补齐（同层优先）
    capacity = batch.max_volunteers
    if len(selected) < capacity:
        leftovers = sorted(
            (c for c in candidates if c.unit.unit_id not in used_ids),
            key=lambda c: (-c.utility, c.unit.unit_id),
        )
        fill = leftovers[: capacity - len(selected)]
        if fill:
            selected.extend(fill)
            warnings.append(f"配额借位后仍有空额，已按效用补入 {len(fill)} 个候选。")
    return selected[:capacity], warnings


def _order_parallel(
    selected: Sequence[ScoredUnit], preference_order: Sequence[str] | None
) -> list[ScoredUnit]:
    """全局排序：考生意愿序（若给出），否则按冲→稳→保→垫 + 层内效用降序；
    并强制**最后一档是 BAO/DIAN**。"""
    if preference_order:
        index = {unit_id: i for i, unit_id in enumerate(preference_order)}
        ordered = sorted(
            selected,
            key=lambda c: (index.get(c.unit.unit_id, len(index)), _tier_index(c.tier)),
        )
    else:
        ordered = sorted(
            selected, key=lambda c: (_tier_index(c.tier), -c.utility, c.unit.unit_id)
        )

    # 最后一档必须是 BAO/DIAN（§6.7 步骤 3）
    for _ in range(len(ordered)):
        if not ordered or ordered[-1].tier in (Tier.BAO, Tier.DIAN):
            break
        for i in range(len(ordered) - 1, -1, -1):
            if ordered[i].tier in (Tier.BAO, Tier.DIAN):
                item = ordered.pop(i)
                ordered.append(item)
                break
        else:
            break
    return ordered


def _local_search(
    selected: list[ScoredUnit],
    candidates: Sequence[ScoredUnit],
    batch: BatchRule,
    params: ModelParams,
) -> list[ScoredUnit]:
    """在结构约束内做 swap 提升总效用（§6.7 步骤 4）。

    结构约束：总量不超上限、垫底数量不低于下限、最后一档仍为 BAO/DIAN。
    """
    required_dian = dian_required(batch, params)
    chosen_ids = {c.unit.unit_id for c in selected}
    pool = sorted(
        (c for c in candidates if c.unit.unit_id not in chosen_ids),
        key=lambda c: (-c.utility, c.unit.unit_id),
    )[:LOCAL_SEARCH_POOL_LIMIT]

    def structure_ok(items: Sequence[ScoredUnit]) -> bool:
        dian = sum(1 for c in items if c.tier is Tier.DIAN)
        last_safe = bool(items) and items[-1].tier in (Tier.BAO, Tier.DIAN)
        return dian >= required_dian and len(items) <= batch.max_volunteers and last_safe

    improved = True
    iterations = 0
    while improved and iterations < MAX_LOCAL_SEARCH_ITERATIONS:
        improved = False
        iterations += 1
        for position, current in enumerate(list(selected)):
            for candidate in pool:
                if candidate.unit.unit_id in {c.unit.unit_id for c in selected}:
                    continue
                if candidate.utility <= current.utility:
                    continue
                trial = list(selected)
                trial[position] = candidate
                if structure_ok(trial):
                    selected = trial
                    improved = True
                    break
            if improved:
                break
    return selected


def generate_plan(
    student: StudentProfile,
    candidates: Sequence[ScoredUnit],
    rule: ProvinceRule,
    batch: BatchRule,
    params: ModelParams,
    *,
    plan_id: str = "plan",
    preference_order: Sequence[str] | None = None,
    obey_adjustment: bool | None = None,
) -> VolunteerPlan:
    """生成志愿表（有序 ``items`` + 分层分布 + 违规 + 警告）。"""
    pool, warnings = _dedup(candidates, batch)

    if batch.is_parallel:
        selected, alloc_warnings = _allocate(pool, batch, rule, params)
        warnings.extend(alloc_warnings)
        selected = _local_search(selected, pool, batch, params)
        ordered = _order_parallel(selected, preference_order)
    else:
        # 顺序志愿：第一志愿必须是最想去的；后续按递补价值（效用）排序
        ordered = sorted(pool, key=lambda c: (-c.utility, c.unit.unit_id))[: batch.max_volunteers]
        warnings.append(
            "顺序志愿批次：第一志愿命中率决定一切（第 2 志愿起近乎无效），"
            "本批次不接受冲稳保配额约束，保底职责必须由平行志愿批次承担。"
        )

    items = [
        PlanItem(
            position=index + 1,
            unit=candidate.unit,
            tier=candidate.tier,
            probability=candidate.probability,
            utility=candidate.utility,
            obey_adjustment=obey_adjustment if batch.has_major_adjustment else None,
            # 把概率模型的人话理由带进志愿项：报告/UI 的"每志愿依据"直接可读（§7/§8）
            notes=list(candidate.probability_result.reasons[:2]) if candidate.probability_result else [],
        )
        for index, candidate in enumerate(ordered)
    ]

    distribution: dict[str, int] = {}
    for item in items:
        distribution[item.tier.value] = distribution.get(item.tier.value, 0) + 1

    plan = VolunteerPlan(
        id=plan_id,
        student_id=student.id,
        province=student.province,
        rule=rule.rule_info(batch),
        items=items,
        tier_distribution=distribution,
        total_utility=round(sum(item.utility for item in items), 6),
        violations=[],
        warnings=warnings,
    )
    plan.violations = rule.validate_plan(plan, batch)
    return plan


__all__ = ["dian_required", "generate_plan"]
