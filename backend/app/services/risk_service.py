"""单点风险速查（L4，AGENTS.md §7 ``POST /risk/scan``）。

不生成志愿表，直接对考生给定的一组 ``unit_id`` 做 §6.8 风险扫描。
风险口径与志愿表完全一致（同一个 ``core.risk.scan_risks``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.models import ModelParams, PlanItem, Risk, Tier, VolunteerPlan, unit_key_of
from app.core.probability import analog_key, estimate_probability
from app.core.risk import scan_risks
from app.core.rules import get_rule
from app.core.scoring import score_unit
from app.db import models as db
from app.db import repositories as repo
from app.etl.synthetic import CURRENT_YEAR
from app.services import recommend_service, student_service
from app.services.plan_service import UnknownUnits


@dataclass
class RiskScanOutcome:
    risks: list[Risk] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scanned: int = 0


def scan(
    session: Session,
    student_row: db.Student,
    unit_ids: list[str],
    *,
    obey_adjustment: bool | None = None,
    obey_adjustment_map: dict[str, bool] | None = None,
    params: ModelParams | None = None,
) -> RiskScanOutcome:
    """对给定单位集合做风险扫描（概率与分层按当前考生重算，绝不复用他人结果）。"""
    params = params or ModelParams()
    profile = student_service.ensure_rank(session, student_row)
    rule = get_rule(profile.province)
    batch = rule.main_batch()
    plan_year = None if profile.year == CURRENT_YEAR else profile.year

    units = repo.load_units(session, profile.province, profile.year, plan_year=plan_year)
    by_id = {unit.unit_id: unit for unit in units}
    unknown = [unit_id for unit_id in unit_ids if unit_id not in by_id]
    if unknown:
        raise UnknownUnits(unknown)

    colleges = repo.load_colleges(session)
    majors = repo.load_majors(session)
    history = repo.load_history(session, profile.province)
    analog_index = repo.build_analog_index(units, history, colleges, majors)
    total_current = repo.get_province_stats(session, profile.province).get(profile.year)
    preferences = profile.preferences

    items: list[PlanItem] = []
    evidence: list[dict] = []
    warnings: list[str] = []
    for index, unit_id in enumerate(unit_ids, start=1):
        unit = by_id[unit_id]
        college = colleges.get(unit.college_id)
        major = majors.get(unit.major_id or "")
        scored = score_unit(unit, preferences=preferences, college=college, major=major)
        result = estimate_probability(
            profile,
            unit,
            history.get(unit_key_of(unit.unit_id), ()),
            rule,
            params,
            current_total_candidates=total_current,
            analog_pool=analog_index.get(
                analog_key(
                    college.province if college else None,
                    tuple(college.level_tags) if college else (),
                    major.discipline if major else None,
                ),
                [],
            ),
        )
        obey = (obey_adjustment_map or {}).get(unit_id, obey_adjustment)
        items.append(
            PlanItem(
                position=index,
                unit=unit,
                tier=result.tier if result.tier is not None else Tier.NO_DATA,
                probability=result.probability,
                utility=scored.utility,
                obey_adjustment=obey if batch.has_major_adjustment else None,
                notes=list(result.reasons[:1]),
            )
        )
        for entry in result.evidence:
            evidence.append(
                {
                    "what": "unit_history",
                    "unit_id": unit.unit_id,
                    "year": entry.year,
                    "min_rank": entry.min_rank,
                    "data_quality": entry.data_quality.value,
                    "source_url": entry.source_url,
                    "note": entry.note,
                }
            )
        if result.probability is None:
            warnings.append(f"{unit.unit_id} 无可用历史（NO_DATA）：无法评估风险，禁止编造。")

    plan = VolunteerPlan(
        id="risk-scan",
        student_id=profile.id,
        province=profile.province,
        rule=rule.rule_info(batch),
        items=items,
        tier_distribution=_distribution(items),
        total_utility=round(sum(item.utility for item in items), 6),
    )
    risks = scan_risks(
        plan,
        student=profile,
        histories=history,
        params=params,
        batch=batch,
        current_total_candidates=total_current,
        group_majors=recommend_service._group_majors(units, majors),
        college_level_tags={cid: tuple(c.level_tags) for cid, c in colleges.items()},
    )
    return RiskScanOutcome(
        risks=risks,
        evidence=evidence,
        warnings=sorted(warnings),
        scanned=len(items),
    )


def _distribution(items: list[PlanItem]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for item in items:
        distribution[item.tier.value] = distribution.get(item.tier.value, 0) + 1
    return distribution


__all__ = ["RiskScanOutcome", "scan"]
