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
from app.core.rules.base import BatchRule, ProvinceRule
from app.core.scoring import score_unit
from app.db import models as db
from app.db import repositories as repo
from app.etl.synthetic import CURRENT_YEAR
from app.services import student_service

#: 推荐列表的分层排序（冲 → 稳 → 保 → 垫 → 基本无望）
TIER_ORDER: tuple[Tier, ...] = (Tier.CHONG, Tier.WEN, Tier.BAO, Tier.DIAN, Tier.TOO_RISKY)

RED_LINE = (
    "该省全部批次均未达 PRIMARY（转载源），按 DOMAIN_RULES §1.3 红线，"
    "其推荐结果不得用于真实填报，UI 必须显示「规则待核实」横幅。"
)


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
        "tuition": "weight_tuition",
        "city": "weight_city",
        "misc": "weight_misc",
    }
    for key, attr in mapping.items():
        if key in weights and weights[key] is not None:
            setattr(prefs, attr, max(0.0, float(weights[key])))
    return prefs


def evaluate_candidates(
    session: Session,
    student_row: db.Student,
    *,
    criteria: FilterCriteria | None = None,
    weights: dict | None = None,
    params: ModelParams | None = None,
    allowed_batches: list[str] | None = None,
    intent_as_hard: bool = False,
) -> EvaluationBundle:
    """跑完整评估流水线（过滤 → 打分 → 概率），返回可复用的评估包。"""
    params = params or ModelParams()
    criteria = criteria or FilterCriteria()

    profile = student_service.ensure_rank(session, student_row)  # 缺位次但有分数 → 自动换算
    rule = get_rule(profile.province)
    batch = rule.main_batch()
    plan_year = None if profile.year == CURRENT_YEAR else profile.year

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
    intent_as_hard: bool = False,
) -> RecommendOutcome:
    """按 §7 生成推荐列表（含每项证据链与整体统计）。"""
    params = params or ModelParams()
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
    selectable.sort(
        key=lambda pair: (TIER_ORDER.index(pair[1].tier), -pair[0].utility, pair[0].unit.unit_id)
    )
    for scored, result in selectable[:limit]:
        outcome.items.append(item_payload(bundle, scored, result, params))

    returned_counts: dict[str, int] = {}
    for item in outcome.items:
        returned_counts[item["tier"]] = returned_counts.get(item["tier"], 0) + 1

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
            f"可推荐 {len(selectable)} 个，按分层与效用截取前 {limit} 个；"
            "提高 limit 或缩小筛选范围可看到更多候选。"
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
    return outcome


__all__ = [
    "RED_LINE",
    "TIER_ORDER",
    "EvaluationBundle",
    "RecommendOutcome",
    "evaluate_candidates",
    "item_payload",
    "recommend",
    "rule_block",
    "rule_warnings",
]
