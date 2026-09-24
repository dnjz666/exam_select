"""推荐编排（L4，AGENTS.md §7 ``POST /recommend``）。

流水线：**硬约束过滤 → 软偏好打分 → 概率估算 → 分层排序 → 组装证据链**。
core 全程纯函数，本模块只做"查库 → 组装 → 调 core"（ADR-003）。

契约铁律（§7）在本模块强制：
1. 每个返回项**必须**含非空 ``evidence``（Step 0 类比证据用 ``note`` 标注为类比，不得伪装成
   本单位历史）；
2. ``probability is None`` ⇔ ``confidence == NO_DATA`` 且 ``reasons`` 说明原因（此类项不进推荐）；
3. 响应中不出现无来源的数字——所有证据条目都带 ``source_url``。

``evaluate_candidates`` 同时被 ``plan_service`` 复用，保证推荐与志愿表口径完全一致。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.filters import FilterResult, filter_units, rejection_summary
from app.core.models import (
    AdmissionRecord,
    College,
    FilterCriteria,
    Major,
    ModelParams,
    Preferences,
    ProbabilityResult,
    ScoredUnit,
    StudentProfile,
    Tier,
    unit_key_of,
)
from app.core.probability import analog_key, estimate_probability, probability_interval
from app.core.rules import get_rule
from app.core.rules.base import BatchRule, ProvinceRule, distribute_quota
from app.core.scoring import score_unit
from app.db import models as db
from app.db import repositories as repo
from app.etl.synthetic import CURRENT_YEAR
from app.services import cache_service, student_service

#: 推荐列表的分层排序（冲 → 稳 → 保 → 垫 → 基本无望）
TIER_ORDER: tuple[Tier, ...] = (Tier.CHONG, Tier.WEN, Tier.BAO, Tier.DIAN, Tier.TOO_RISKY)

RED_LINE = (
    "该省全部批次均未达 PRIMARY（转载源），按 DOMAIN_RULES §1.3 红线，"
    "其推荐结果不得用于真实填报，UI 必须显示「规则待核实」横幅。"
)

#: 展示位分配时参与"首轮配额"的层（TOO_RISKY 不在配额里，只在显式开启时兜余量）
_QUOTA_TIERS: tuple[Tier, ...] = (Tier.CHONG, Tier.WEN, Tier.BAO, Tier.DIAN)

#: 展示位分配的迭代上限（水填充分配，每轮至少填满一层，正常 2–3 轮收敛）
_ALLOCATION_MAX_ROUNDS = 8


def allocate_display_slots(
    pools: Mapping[Tier, Sequence[object]],
    limit: int,
    weights: Mapping[str, float],
    *,
    include_too_risky: bool,
) -> tuple[dict[Tier, int], dict[Tier, int]]:
    """把 ``limit`` 个**展示位**按分层配额分给各层（ADR-020）。

    ## 为什么需要它

    原实现是"按 ``(tier, -utility)`` 排序后取前 N"，而 ``TIER_ORDER`` 把 CHONG 排在最前，
    于是 ``limit`` 小于 CHONG 候选数时**返回的整页全是"冲"**（实测 limit=8/20/60 全部如此，
    即使全池有 62 个保、7,824 个垫）。考生会以为"一个稳的都没有"，这是**误导性展示**。

    ## 算法（水填充 / water-filling）

    1. 用**批次配额权重**把 ``limit`` 按最大余额法分给冲稳保垫（确定性）；
    2. 某层候选不足 → 其份额按权重转给**仍有余量**的层，重复直到分完或没有余量；
    3. ``include_too_risky=True`` 时，余量才给 TOO_RISKY（它不在配额里）；
    4. 所有层都取空仍有余量 → **如实返回少于 limit 条**，绝不用低质量候选凑数。

    ★ 与 ``planner._allocate`` 的区别（刻意不同）：
    志愿表的借位规则是"**向更保守方向借**"（保底是安全承诺）；
    而这里只是**浏览列表的取样**，要的是"各档都能看到"，故按权重**比例**再分配。

    :return: ``(allocation, shortfall)`` —— 每层实际取几位 / 每层差几位（配额减去实得）。
    """
    if limit <= 0:
        return {tier: 0 for tier in TIER_ORDER}, {tier: 0 for tier in TIER_ORDER}

    capacity: dict[Tier, int] = {tier: len(pools.get(tier, ()) or ()) for tier in TIER_ORDER}
    allocation: dict[Tier, int] = {tier: 0 for tier in TIER_ORDER}

    active = {
        tier
        for tier in _QUOTA_TIERS
        if capacity[tier] > 0 and weights.get(tier.value, 0.0) > 0
    }
    budget = limit
    for _ in range(_ALLOCATION_MAX_ROUNDS):
        if budget <= 0 or not active:
            break
        sub_weights = {tier.value: float(weights[tier.value]) for tier in active}
        share = distribute_quota(sub_weights, budget)
        progressed = False
        for tier in sorted(active, key=TIER_ORDER.index):
            room = capacity[tier] - allocation[tier]
            take = min(share.get(tier.value, 0), room)
            if take > 0:
                allocation[tier] += take
                budget -= take
                progressed = True
            if allocation[tier] >= capacity[tier]:
                active.discard(tier)
        if not progressed:
            break

    # 余量：仅在考生**显式要求**看过险档时才给它，绝不默认塞给用户
    if budget > 0 and include_too_risky:
        room = capacity[Tier.TOO_RISKY] - allocation[Tier.TOO_RISKY]
        take = min(budget, max(0, room))
        allocation[Tier.TOO_RISKY] += take
        budget -= take

    # 缺口 = 按配额**本应**展示几位 − 实际候选数（负值归零）。
    # ★ 这是"保底/垫底缺失"的判据：真实浙江数据在 2 年窗口下一条 BAO/DIAN 都给不出，
    #   必须让调用方拿到这个信号去提示考生，而不是让他看到一个没有垫底的列表。
    ideal = distribute_quota(
        {tier.value: float(weights[tier.value]) for tier in _QUOTA_TIERS if weights.get(tier.value, 0.0) > 0},
        limit,
    ) if any(weights.get(tier.value, 0.0) > 0 for tier in _QUOTA_TIERS) else {}
    shortfall = {
        tier: max(0, ideal.get(tier.value, 0) - capacity[tier]) for tier in TIER_ORDER
    }
    return allocation, shortfall


@dataclass
class EvaluationBundle:
    """过滤 + 打分 + 概率 的完整评估结果（推荐与志愿表共用）。"""

    profile: StudentProfile
    rule: ProvinceRule
    batch: BatchRule
    pairs: list[tuple[ScoredUnit, ProbabilityResult]] = field(default_factory=list)
    filtered: FilterResult = field(default_factory=FilterResult)
    colleges: dict[str, College] = field(default_factory=dict)
    majors: dict[str, Major] = field(default_factory=dict)
    history: dict[str, list[AdmissionRecord]] = field(default_factory=dict)
    total_current: int | None = None
    no_data_count: int = 0
    no_evidence_count: int = 0
    risk_factory: dict = field(default_factory=dict)  # 供 risk.py 复用的元数据

    def tier_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _, result in self.pairs:
            counts[result.tier.value] = counts.get(result.tier.value, 0) + 1
        return dict(sorted(counts.items()))

    def data_coverage(self) -> float:
        if not self.filtered.passed:
            return 0.0
        return round(len(self.pairs) / len(self.filtered.passed), 4)


@dataclass
class RecommendOutcome:
    items: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)


def _with_weights(
    profile: StudentProfile,
    weights: dict | None,
    criteria: FilterCriteria | None = None,
) -> Preferences:
    """把请求里的权重与**意向筛选**合并进考生偏好。

    ★ M6 实测缺陷（ADR-017）：原先只覆盖 ``weights``，``criteria.regions`` /
    ``criteria.major_categories`` **完全不参与打分**。后果是推荐页的筛选面板
    "不勾硬约束时形同虚设"——勾了"意向地区=浙江"，列表顺序与效用值一模一样
    （因为 ``region_score`` 读的是 ``preferences.intended_regions``，而它一直是空的）。
    现在把两者合并：建档向导里填的意向（档案级）与推荐页勾的意向（本次查询级）取并集。
    """
    prefs = profile.preferences.model_copy(deep=True)
    if criteria is not None:
        if criteria.regions:
            prefs.intended_regions = sorted({*prefs.intended_regions, *criteria.regions})
        if criteria.major_categories:
            prefs.intended_major_categories = sorted(
                {*prefs.intended_major_categories, *criteria.major_categories}
            )
    if not weights:
        return prefs
    mapping = {
        "region": "weight_region",
        "college_level": "weight_college_level",
        "major": "weight_major",
        "city": "weight_city",
        "misc": "weight_misc",
    }
    for key, attr in mapping.items():
        if key in weights and weights[key] is not None:
            setattr(prefs, attr, max(0.0, float(weights[key])))
    return prefs


def criteria_from_profile(profile: StudentProfile) -> FilterCriteria:
    """把**档案里的偏好**转成硬约束（ADR-022）。

    ★ 为什么需要它：筛选与偏好现在只填一次（建档向导第 4 步）并持久化到档案，
    推荐页与志愿表都直接按它生成，不再让考生重填一遍。

    语义：
    * ``intent_as_hard=False``（默认）→ 返回**空** criteria：意向只影响排序（软偏好 §6.5）；
    * ``intent_as_hard=True`` → 把意向地区/层次/专业升级为硬约束（一票否决）。

    ``excluded_majors`` 不在这里处理：它由 ``risk.py`` 的 ``GROUP_UNACCEPTABLE`` 使用
    （"组内含排斥专业"是风险提示，不是整条否决）。
    """
    prefs = profile.preferences
    if not prefs.intent_as_hard:
        return FilterCriteria()
    return FilterCriteria(
        regions=list(prefs.intended_regions),
        levels=list(prefs.intended_levels),
        major_categories=list(prefs.intended_major_categories),
    )


def evaluate_candidates(
    session: Session,
    student_row: db.Student,
    *,
    criteria: FilterCriteria | None = None,
    weights: dict | None = None,
    params: ModelParams | None = None,
    allowed_batches: list[str] | None = None,
    intent_as_hard: bool | None = None,
) -> EvaluationBundle:
    """跑完整评估流水线（过滤 → 打分 → 概率），返回可复用的评估包。

    :param criteria: 硬约束。``None``（默认）→ 按**档案偏好**推导（ADR-022）；
        显式传入则作为高级覆盖（如 agent 工具临时收窄范围）。
    :param intent_as_hard: ``None``（默认）→ 取档案里的 ``preferences.intent_as_hard``。
    """
    params = params or ModelParams()
    profile = student_service.ensure_rank(session, student_row)  # 缺位次但有分数 → 自动换算
    rule = get_rule(profile.province)
    batch = rule.main_batch()
    plan_year = None if profile.year == CURRENT_YEAR else profile.year

    # ★ ADR-022：筛选/偏好来自档案；显式 criteria 仅作覆盖
    if criteria is None:
        criteria = criteria_from_profile(profile)
    if intent_as_hard is None:
        intent_as_hard = bool(profile.preferences.intent_as_hard)

    units = repo.load_units(session, profile.province, profile.year, plan_year=plan_year)
    colleges = repo.load_colleges(session)
    majors = repo.load_majors(session)
    history = repo.load_history(session, profile.province)
    analog_index = repo.build_analog_index(units, history, colleges, majors)
    stats = repo.get_province_stats(session, profile.province)
    total_current = stats.get(profile.year)
    level_tags_by_college = {cid: tuple(c.level_tags) for cid, c in colleges.items()}
    # ★ 地区硬约束必须用**院校所在地**（College.province），不能用 unit_id 的第一段
    #   （那是招生省；ADR-017 勘误）
    college_province_by_college = {cid: c.province for cid, c in colleges.items()}

    filtered = filter_units(
        units,
        profile,
        criteria=criteria,
        majors=majors,
        level_tags_by_college=level_tags_by_college,
        college_province_by_college=college_province_by_college,
        allowed_batches=allowed_batches or [batch.batch_code],
        intent_as_hard=intent_as_hard,
    )
    preferences = _with_weights(profile, weights, criteria)

    bundle = EvaluationBundle(
        profile=profile,
        rule=rule,
        batch=batch,
        filtered=filtered,
        colleges=colleges,
        majors=majors,
        history=history,
        total_current=total_current,
        risk_factory={
            "level_tags_by_college": level_tags_by_college,
            "group_majors": _group_majors(units, majors),
        },
    )

    for unit in filtered.passed:
        college = colleges.get(unit.college_id)
        major = majors.get(unit.major_id or "")
        scored = score_unit(
            unit,
            preferences=preferences,
            college=college,
            major=major,
            level_tags=tuple(college.level_tags) if college else (),
            # ★ ADR-019：地区维度需要考生本省（本省认可度 + 地区高教资源密度）
            home_province=profile.province,
        )
        bucket = analog_index.get(
            analog_key(
                college.province if college else None,
                tuple(college.level_tags) if college else (),
                major.discipline if major else None,
            ),
            [],
        )
        result = estimate_probability(
            profile,
            unit,
            history.get(unit_key_of(unit.unit_id), ()),
            rule,
            params,
            current_total_candidates=total_current,
            analog_pool=bucket,
        )
        if result.probability is None:
            bundle.no_data_count += 1
            continue
        if not result.evidence:  # 契约铁律 1
            bundle.no_evidence_count += 1
            continue
        # 把概率/分层回填到 ScoredUnit，供 planner 直接复用（口径完全一致）
        scored.probability = result.probability
        scored.tier = result.tier
        scored.confidence = result.confidence
        scored.probability_result = result
        bundle.pairs.append((scored, result))
    return bundle


def _group_majors(units, majors: dict[str, Major]) -> dict[tuple[str, str], list[str]]:
    """``(college_id, group_code) -> 组内专业名``（供 GROUP_UNACCEPTABLE 风险使用）。"""
    grouped: dict[tuple[str, str], list[str]] = {}
    for unit in units:
        if not unit.group_code:
            continue
        names = grouped.setdefault((unit.college_id, unit.group_code), [])
        name = unit.major_name or (majors.get(unit.major_id or "").name if unit.major_id in majors else "")
        if name and name not in names:
            names.append(name)
    return grouped


def _college_block(college: College | None) -> dict | None:
    if college is None:
        return None
    return {
        "id": college.id,
        "name": college.name,
        "province": college.province,
        "city": college.city,
        "level_tags": list(college.level_tags),
        "is_public": college.is_public,
        "college_type": college.college_type,
        "affiliation": college.affiliation,
        "source_url": college.source_url,
    }


def _major_block(major: Major | None) -> dict | None:
    if major is None:
        return None
    return {
        "id": major.id,
        "name": major.name,
        "category": major.category,
        "discipline": major.discipline,
        "duration": major.duration,
        "source_url": major.source_url,
    }


def item_payload(
    bundle: EvaluationBundle, scored: ScoredUnit, result: ProbabilityResult, params: ModelParams
) -> dict:
    """单个推荐项的响应体（unit + college + major + 概率/区间 + 完整证据链）。"""
    unit = scored.unit
    interval = probability_interval(result, params)
    return {
        "unit": unit.model_dump(mode="json"),
        "college": _college_block(bundle.colleges.get(unit.college_id)),
        "major": _major_block(bundle.majors.get(unit.major_id or "")),
        "probability": result.probability,
        "probability_interval": list(interval) if interval else None,
        "tier": result.tier.value,
        "confidence": result.confidence.value,
        "utility": round(scored.utility, 6),
        "score_breakdown": scored.score_breakdown.model_dump(),
        "predicted_min_rank": result.predicted_min_rank,
        "sigma": result.sigma,
        "evidence": [entry.model_dump(mode="json") for entry in result.evidence],
        "adjustments": [adj.model_dump(mode="json") for adj in result.adjustments],
        "reasons": list(result.reasons),
        "warnings": list(result.warnings),
    }


def rule_block(batch: BatchRule, rule: ProvinceRule) -> dict:
    return {
        "province": rule.province,
        "batch_code": batch.batch_code,
        "batch_name": batch.batch_name,
        "unit_type": batch.unit_type.value,
        "max_volunteers": batch.max_volunteers,
        "has_major_adjustment": batch.has_major_adjustment,
        "is_parallel": batch.is_parallel,
        "majors_per_group": batch.majors_per_group,
        "verified_status": batch.verified_status.value,
        "verified_year": batch.verified_year,
        "source_url": batch.source_url,
        "requires_banner": batch.verified_status.value in {"SECONDARY", "UNVERIFIED"},
    }


def rule_warnings(batch: BatchRule) -> list[str]:
    if batch.verified_status.value in {"SECONDARY", "UNVERIFIED"}:
        return [RED_LINE]
    if batch.verified_status.value == "PRIMARY_GOV":
        return [
            "该省规则为 PRIMARY-GOV（政府门户转述），建议按批次核实状态提示用户，并以考试院原文为准。"
        ]
    return []


def recommend(
    session: Session,
    student_row: db.Student,
    *,
    criteria: FilterCriteria | None = None,
    limit: int = 60,
    include_too_risky: bool = False,
    weights: dict | None = None,
    params: ModelParams | None = None,
    allowed_batches: list[str] | None = None,
    intent_as_hard: bool | None = None,
    use_cache: bool = True,
) -> RecommendOutcome:
    """按 §7 生成推荐列表（含每项证据链与整体统计）。

    ★ ADR-019：带**持久缓存**。键覆盖 ``(数据代次, 省, 年, 位次, 筛选, 权重, 参数, limit,
    批次, 是否含过险)`` —— 结果与考生身份无关，因此"同位次 + 同筛选"的另一位考生
    可直接复用（详见 ``services/cache_service.py``）。

    ★ ADR-022：``criteria`` / ``intent_as_hard`` 默认 ``None`` → **按档案偏好推导**。
    注意缓存键必须用**推导后**的 criteria，否则"同档案"的两次调用会算出不同键而漏命中。
    """
    params = params or ModelParams()
    profile_for_key = student_service.ensure_rank(session, student_row)
    if criteria is None:
        criteria = criteria_from_profile(profile_for_key)
    if intent_as_hard is None:
        intent_as_hard = bool(profile_for_key.preferences.intent_as_hard)

    # 先定位次（缓存键要用它；ensure_rank 是幂等的）
    profile = profile_for_key
    rank = profile.rank
    cache_hit = False
    cache_key: str | None = None
    if use_cache and rank is not None:
        data_version = cache_service.get_data_version(session)
        cache_key, label = cache_service.fingerprint_recommend(
            data_version=data_version,
            province=profile.province,
            year=profile.year,
            rank=rank,
            criteria=criteria,
            weights=weights,
            params=params,
            limit=limit,
            include_too_risky=include_too_risky,
            allowed_batches=allowed_batches,
            intent_as_hard=intent_as_hard,
        )
        cached = cache_service.cache_get(session, cache_key, data_version)
        if cached is not None:
            outcome = RecommendOutcome(
                items=cached.get("items", []),
                stats=cached.get("stats", {}),
                warnings=cached.get("warnings", []),
                evidence=cached.get("evidence", []),
            )
            outcome.stats["cache"] = {
                "hit": True,
                "data_version": data_version,
                "label": label,
            }
            return outcome

    bundle = evaluate_candidates(
        session,
        student_row,
        criteria=criteria,
        weights=weights,
        params=params,
        allowed_batches=allowed_batches,
        intent_as_hard=intent_as_hard,
    )
    outcome = RecommendOutcome()

    selectable = [
        (scored, result)
        for scored, result in bundle.pairs
        if include_too_risky or result.tier is not Tier.TOO_RISKY
    ]
    # 层内按效用降序（确定性：效用相同再按 unit_id）
    selectable.sort(key=lambda pair: (-pair[0].utility, pair[0].unit.unit_id))

    pools: dict[Tier, list[tuple[ScoredUnit, ProbabilityResult]]] = {
        tier: [] for tier in TIER_ORDER
    }
    for pair in selectable:
        pools[pair[1].tier].append(pair)

    # ★ ADR-020：按分层配额**取样**，而不是"排序后取前 N"。
    #   原做法在 limit 小于 CHONG 候选数时返回整页"冲"，考生会以为一个稳的都没有。
    weights = bundle.rule.quota_weights(bundle.batch) or dict(params.quota)
    allocation, shortfall = allocate_display_slots(
        pools, limit, weights, include_too_risky=include_too_risky
    )
    chosen: list[tuple[ScoredUnit, ProbabilityResult]] = []
    for tier in TIER_ORDER:
        chosen.extend(pools[tier][: allocation.get(tier, 0)])
    # 最终顺序仍是 冲→稳→保→垫（前端按梯度阅读），层内效用降序
    chosen.sort(
        key=lambda pair: (TIER_ORDER.index(pair[1].tier), -pair[0].utility, pair[0].unit.unit_id)
    )
    for scored, result in chosen:
        outcome.items.append(item_payload(bundle, scored, result, params))

    returned_counts: dict[str, int] = {}
    for item in outcome.items:
        returned_counts[item["tier"]] = returned_counts.get(item["tier"], 0) + 1

    # 未能凑够 limit 时如实披露（不给低质量候选凑数）
    unfilled = limit - len(outcome.items)

    # 候选池的院校所在地分布（供前端"意向地区"筛选器生成选项，ADR-017）。
    # 按数量降序；所在地缺失的院校不列入（否则会出现一个没有意义的空选项）。
    region_options: dict[str, int] = {}
    for unit in bundle.filtered.passed:
        college = bundle.colleges.get(unit.college_id)
        province = college.province if college else None
        if province:
            region_options[province] = region_options.get(province, 0) + 1

    outcome.stats = {
        "units_considered": len(bundle.filtered.passed) + len(bundle.filtered.rejected),
        "hard_filtered_out": len(bundle.filtered.rejected),
        "filtered_out_reasons": rejection_summary(bundle.filtered),
        "evaluated_count": len(bundle.pairs),
        "no_data_count": bundle.no_data_count,
        "no_evidence_count": bundle.no_evidence_count,
        "data_coverage": bundle.data_coverage(),
        "tier_distribution": returned_counts,
        "tier_distribution_all": bundle.tier_counts(),
        # ★ ADR-020：本次取样给各层分了多少展示位，以及哪些层**给不出**应得的量
        "tier_allocation": {
            tier.value: allocation.get(tier, 0) for tier in TIER_ORDER if allocation.get(tier, 0)
        },
        "tier_shortfall": {
            tier.value: shortfall.get(tier, 0) for tier in TIER_ORDER if shortfall.get(tier, 0)
        },
        "returned": len(outcome.items),
        "limit": limit,
        "include_too_risky": include_too_risky,
        "rule": rule_block(bundle.batch, bundle.rule),
        "region_options": dict(
            sorted(region_options.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
    }

    warnings: list[str] = list(rule_warnings(bundle.batch))
    if bundle.no_data_count:
        warnings.append(
            f"{bundle.no_data_count} 个候选因无可用历史数据（NO_DATA）被排除：宁可不答，不可编造概率。"
        )
    if bundle.no_evidence_count:
        warnings.append(
            f"{bundle.no_evidence_count} 个候选因无法组装非空证据链被排除（§7 契约铁律 1）。"
        )
    if len(selectable) > limit:
        warnings.append(
            f"可推荐 {len(selectable)} 个，已按**分层配额**取样 {limit} 个"
            "（各档都会取样，不是只给「冲」档）；提高 limit 或缩小筛选范围可看到更多候选。"
        )
    if unfilled > 0:
        warnings.append(
            f"候选池不足以填满 {limit} 个展示位（实际返回 {len(outcome.items)} 个）："
            "没有用低质量候选凑数。"
        )
    # ★ ADR-020 / M7-11：保底、垫底缺失必须**明说**，不能给一个没有垫底的列表
    missing_safety = [
        tier.value for tier in (Tier.DIAN, Tier.BAO) if shortfall.get(tier, 0) > 0
    ]
    if missing_safety:
        warnings.append(
            f"⚠️ 本次取样缺少 {'、'.join(missing_safety)} 档候选（配额要求的数量给不出）："
            "常见原因是可用历史年数不足、安全闸门把「保/垫」降级为「稳」，"
            "或筛选条件过窄。**不要据此认为已有保底**。"
        )
    if bundle.data_coverage() < 0.99 and bundle.filtered.passed:
        warnings.append(
            f"数据覆盖率 {bundle.data_coverage():.1%}：部分单位缺少可用历史，未纳入推荐。"
        )
    outcome.warnings = sorted(warnings)

    outcome.evidence = [
        {
            "what": "province_rule",
            "province": bundle.rule.province,
            "batch_code": bundle.batch.batch_code,
            "verified_status": bundle.batch.verified_status.value,
            "source_url": bundle.batch.source_url,
        },
        {
            "what": "score_rank_table",
            "province": bundle.profile.province,
            "year": bundle.profile.year,
            "total_candidates": bundle.total_current,
            "source_url": student_row.rank_source_url or "unknown://score_rank_table",
        },
    ]

    # ★ 写持久缓存（ADR-019）：下一次"相似问题"直接复用，跨进程重启也有效
    if use_cache and cache_key is not None:
        outcome.stats["cache"] = {
            "hit": cache_hit,
            "data_version": cache_service.get_data_version(session),
            "label": label,
        }
        cache_service.cache_put(
            session,
            cache_key,
            data_version=cache_service.get_data_version(session),
            kind="recommend",
            label=label,
            payload={
                "items": outcome.items,
                "stats": {k: v for k, v in outcome.stats.items() if k != "cache"},
                "warnings": outcome.warnings,
                "evidence": outcome.evidence,
            },
        )
    return outcome


__all__ = [
    "RED_LINE",
    "TIER_ORDER",
    "EvaluationBundle",
    "RecommendOutcome",
    "allocate_display_slots",
    "criteria_from_profile",
    "evaluate_candidates",
    "item_payload",
    "recommend",
    "rule_block",
    "rule_warnings",
]
