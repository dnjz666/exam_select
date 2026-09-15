"""志愿表编排（L4，AGENTS.md §7 ``/plans/*``）。

- ``generate``：复用 ``recommend_service.evaluate_candidates``（同一套过滤/打分/概率口径）
  → ``core.planner`` 生成 → ``core.risk`` 扫描 → 落库；
- ``patch_items``：手改顺序/增删（**只允许在生成时的候选池内调整**，避免绕过过滤与证据链）；
- 每次改动都重算 ``violations``（批次规则）与 ``risks``（§6.8），不允许出现"改完不校验"。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.models import (
    FilterCriteria,
    ModelParams,
    PlanItem,
    Risk,
    StudentProfile,
    Tier,
    VolunteerPlan,
    unit_key_of,
)
from app.core.planner import generate_plan
from app.core.risk import scan_risks
from app.core.rules import batch_by_code, get_rule
from app.db import models as db
from app.db import repositories as repo
from app.services import recommend_service, student_service


class PlanNotFound(Exception):
    """志愿表不存在。"""


class UnknownUnits(Exception):
    """手改时引用了不在该志愿表候选池内的单位（M3 只允许池内调整）。"""

    def __init__(self, unit_ids: list[str]) -> None:
        self.unit_ids = unit_ids
        super().__init__(f"以下单位不在该志愿表的候选池内：{'、'.join(unit_ids[:5])}")


@dataclass
class PlanBundle:
    plan: VolunteerPlan
    risks: list[Risk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)


def _scan(
    session: Session,
    profile: StudentProfile,
    plan: VolunteerPlan,
    *,
    params: ModelParams,
    history: dict,
    total_current: int | None,
    risk_meta: dict,
) -> list[Risk]:
    _, batch = batch_by_code(plan.rule.batch_code)
    return scan_risks(
        plan,
        student=profile,
        histories=history,
        params=params,
        batch=batch,
        current_total_candidates=total_current,
        group_majors=risk_meta.get("group_majors"),
        college_level_tags=risk_meta.get("level_tags_by_college"),
    )


def _persist(session: Session, bundle: PlanBundle, payload: dict) -> None:
    risks_payload = [risk.model_dump(mode="json") for risk in bundle.risks]
    row = repo.get_plan(session, bundle.plan.id)
    if row is None:
        repo.save_plan(
            session,
            plan_id=bundle.plan.id,
            student_id=bundle.plan.student_id,
            province=bundle.plan.province,
            batch_code=bundle.plan.rule.batch_code,
            is_parallel=bundle.plan.rule.is_parallel,
            payload=payload,
            risks=risks_payload,
        )
    else:
        repo.update_plan(session, row, payload=payload, risks=risks_payload)


def generate(
    session: Session,
    student_row: db.Student,
    *,
    criteria: FilterCriteria | None = None,
    weights: dict | None = None,
    params: ModelParams | None = None,
    plan_id: str | None = None,
    preference_order: list[str] | None = None,
    obey_adjustment: bool | None = None,
) -> PlanBundle:
    """生成志愿表并落库（含风险扫描）。"""
    params = params or ModelParams()
    bundle_in = recommend_service.evaluate_candidates(
        session, student_row, criteria=criteria, weights=weights, params=params
    )
    # TOO_RISKY（概率 <0.10）默认不进志愿表（§6.3），planner 的分层元组里也没有它
    candidates = [scored for scored, result in bundle_in.pairs if result.tier is not Tier.TOO_RISKY]
    excluded_too_risky = len(bundle_in.pairs) - len(candidates)
    plan_id = plan_id or f"plan-{repo.now_iso().replace(':', '').replace('-', '')}"
    plan = generate_plan(
        bundle_in.profile,
        candidates,
        bundle_in.rule,
        bundle_in.batch,
        params,
        plan_id=plan_id,
        preference_order=preference_order,
        obey_adjustment=obey_adjustment,
    )
    risks = _scan(
        session,
        bundle_in.profile,
        plan,
        params=params,
        history=bundle_in.history,
        total_current=bundle_in.total_current,
        risk_meta=bundle_in.risk_factory,
    )
    bundle = PlanBundle(
        plan=plan,
        risks=risks,
        warnings=sorted(set(plan.warnings) | {risk.message for risk in risks if risk.level.value == "HIGH"}),
        stats={
            "candidates_evaluated": len(candidates),
            "excluded_too_risky": excluded_too_risky,
            "no_data_count": bundle_in.no_data_count,
            "data_coverage": bundle_in.data_coverage(),
            "tier_distribution": plan.tier_distribution,
            "violations": [violation.model_dump(mode="json") for violation in plan.violations],
        },
        evidence=_plan_evidence(plan, bundle_in.history),
    )
    _persist(session, bundle, plan.model_dump(mode="json"))
    return bundle


def _plan_evidence(plan: VolunteerPlan, history: dict) -> list[dict]:
    """志愿表级证据：批次规则来源 + 每个志愿所依据的历史来源（逐项可追溯）。

    证据是**派生数据**：从历史记录重算，fresh 生成与从库读回两条路径口径一致，
    避免把证据副本存进 ``plans`` 表后与历史脱节。
    """
    evidence: list[dict] = [
        {
            "what": "province_rule",
            "batch_code": plan.rule.batch_code,
            "verified_status": plan.rule.verified_status.value,
            "source_url": plan.rule.source_url,
        }
    ]
    for item in plan.items:
        records = history.get(unit_key_of(item.unit.unit_id), ())
        if not records:
            evidence.append(
                {
                    "what": "unit_history",
                    "unit_id": item.unit.unit_id,
                    "source_url": "",
                    "note": "无本单位历史（新增专业），概率来自 Step 0 同类单位类比",
                }
            )
            continue
        for record in sorted(records, key=lambda r: -r.year)[:3]:
            evidence.append(
                {
                    "what": "unit_history",
                    "unit_id": item.unit.unit_id,
                    "year": record.year,
                    "min_rank": record.min_rank,
                    "data_quality": record.data_quality.value,
                    "source_url": record.source_url,
                }
            )
    return evidence


def load(session: Session, plan_id: str) -> PlanBundle:
    """读取志愿表（payload 即完整 VolunteerPlan；逐项证据由历史重算，保证可追溯）。"""
    row = repo.get_plan(session, plan_id)
    if row is None:
        raise PlanNotFound(plan_id)
    plan = VolunteerPlan.model_validate_json(row.payload)
    risks = [Risk.model_validate(r) for r in _loads(row.risks)]
    return PlanBundle(
        plan=plan,
        risks=risks,
        warnings=sorted({risk.message for risk in risks if risk.level.value == "HIGH"}),
        stats={
            "tier_distribution": plan.tier_distribution,
            "violations": [violation.model_dump(mode="json") for violation in plan.violations],
        },
        evidence=_plan_evidence(plan, repo.load_history(session, plan.province)),
    )


def _loads(raw: str) -> list:
    import json

    return json.loads(raw or "[]")


def patch_items(
    session: Session,
    plan_id: str,
    *,
    items: list[dict],
    obey_adjustment: bool | None = None,
) -> PlanBundle:
    """手改志愿表：按给定的 ``[{unit_id, obey_adjustment?}]`` 重排/增删。

    只允许使用该志愿表生成时的候选池（其单位与当时的概率/分层一起存在 payload 里），
    避免绕过硬约束与证据链。改完立即重算违规与风险。
    """
    current = load(session, plan_id)
    pool = {item.unit.unit_id: item for item in current.plan.items}
    unknown = [entry["unit_id"] for entry in items if entry["unit_id"] not in pool]
    if unknown:
        raise UnknownUnits(unknown)

    student_row = repo.get_student(session, current.plan.student_id)
    if student_row is None:
        raise PlanNotFound(f"student:{current.plan.student_id}")
    profile = student_service.require_complete(student_row)

    new_items: list[PlanItem] = []
    for index, entry in enumerate(items, start=1):
        source = pool[entry["unit_id"]]
        chosen = entry.get("obey_adjustment", source.obey_adjustment)
        if obey_adjustment is not None:
            chosen = obey_adjustment
        new_items.append(
            PlanItem(
                position=index,
                unit=source.unit,
                tier=source.tier,
                probability=source.probability,
                utility=source.utility,
                obey_adjustment=chosen,
                notes=list(source.notes),
            )
        )

    rule = get_rule(current.plan.province)
    _, batch = batch_by_code(current.plan.rule.batch_code)
    distribution: dict[str, int] = {}
    for item in new_items:
        distribution[item.tier.value] = distribution.get(item.tier.value, 0) + 1
    plan = current.plan.model_copy(
        update={
            "items": new_items,
            "tier_distribution": distribution,
            "total_utility": round(sum(item.utility for item in new_items), 6),
            "violations": rule.validate_plan(
                current.plan.model_copy(update={"items": new_items}), batch
            ),
        }
    )

    histories = repo.load_history(session, plan.province)
    units = repo.load_units(session, plan.province, profile.year)
    majors = repo.load_majors(session)
    colleges = repo.load_colleges(session)
    params = ModelParams()
    risks = _scan(
        session,
        profile,
        plan,
        params=params,
        history=histories,
        total_current=repo.get_province_stats(session, plan.province).get(profile.year),
        risk_meta={
            "group_majors": recommend_service._group_majors(units, majors),
            "level_tags_by_college": {cid: tuple(c.level_tags) for cid, c in colleges.items()},
        },
    )

    bundle = PlanBundle(
        plan=plan,
        risks=risks,
        warnings=sorted({risk.message for risk in risks if risk.level.value == "HIGH"}),
        stats={
            "tier_distribution": distribution,
            "violations": [violation.model_dump(mode="json") for violation in plan.violations],
        },
        evidence=current.evidence,
    )
    _persist(session, bundle, plan.model_dump(mode="json"))
    return bundle


def validate(session: Session, plan_id: str) -> PlanBundle:
    """只重跑规则校验与风险扫描（不改变志愿内容）。"""
    bundle = load(session, plan_id)
    student_row = repo.get_student(session, bundle.plan.student_id)
    if student_row is None:
        raise PlanNotFound(f"student:{bundle.plan.student_id}")
    profile = student_service.require_complete(student_row)

    units = repo.load_units(session, bundle.plan.province, profile.year)
    majors = repo.load_majors(session)
    colleges = repo.load_colleges(session)
    _, batch = batch_by_code(bundle.plan.rule.batch_code)
    rule = get_rule(bundle.plan.province)
    bundle.plan.violations = rule.validate_plan(bundle.plan, batch)
    bundle.risks = _scan(
        session,
        profile,
        bundle.plan,
        params=ModelParams(),
        history=repo.load_history(session, bundle.plan.province),
        total_current=repo.get_province_stats(session, bundle.plan.province).get(profile.year),
        risk_meta={
            "group_majors": recommend_service._group_majors(units, majors),
            "level_tags_by_college": {cid: tuple(c.level_tags) for cid, c in colleges.items()},
        },
    )
    bundle.stats = {
        "tier_distribution": bundle.plan.tier_distribution,
        "violations": [violation.model_dump(mode="json") for violation in bundle.plan.violations],
    }
    bundle.warnings = sorted({risk.message for risk in bundle.risks if risk.level.value == "HIGH"})
    repo.update_plan(
        session,
        repo.get_plan(session, plan_id),  # type: ignore[arg-type]
        payload=bundle.plan.model_dump(mode="json"),
        risks=[risk.model_dump(mode="json") for risk in bundle.risks],
    )
    return bundle


def dian_floor(batch_code: str, params: ModelParams | None = None) -> int:
    """垫底志愿下限（供前端提示"还差几个保底"）。"""
    from app.core.planner import dian_required

    _, batch = batch_by_code(batch_code)
    return dian_required(batch, params or ModelParams())


__all__ = [
    "PlanBundle",
    "PlanNotFound",
    "UnknownUnits",
    "dian_floor",
    "generate",
    "load",
    "patch_items",
    "validate",
]
