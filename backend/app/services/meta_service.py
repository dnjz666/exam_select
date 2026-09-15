"""元数据编排（L4）：省份批次规则与分层定义。

铁律：返回的每个规则数字都必须带 ``source_url`` / ``verified_status`` / ``source_quote``
（AGENTS.md §6.6），**没有来源的数字不出现在响应里**（§7 契约铁律 3）。

另提供 AGENTS.md §8.1 Step 2 所需的两件事：
- 省份 **选考科目池**：有官方来源时直接用规则事实（``origin="RULE"``）；
  未核实到原文时**降级**为"由招生计划反推"并显式标注 ``origin="DATA_DERIVED"``
  ——宁可不答，不可编造。
- **可报专业覆盖率**：给定选考组合，用 ``core.filters.subject_matches`` 真实统计，
  不使用任何估计值。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.filters import subject_matches
from app.core.models import ModelParams
from app.core.rules import PROVINCES, all_rules, get_rule
from app.db import repositories as repo
from app.etl.synthetic import CURRENT_YEAR

#: 各省需要 UI 提示横幅的核实状态（DOMAIN_RULES §1.3 红线）
BANNER_STATUSES = {"SECONDARY", "UNVERIFIED"}
CAUTION_STATUSES = {"PRIMARY_GOV"}

#: 选考科目池的来源性质（前端据此决定是否显示"科目池非官方"提示）
POOL_ORIGIN_RULE = "RULE"
POOL_ORIGIN_DATA_DERIVED = "DATA_DERIVED"

_DERIVED_POOL_CAVEAT = (
    "该省选考科目池未核实到考试院官方原文，当前列表由现有招生计划的选考要求反推得出，"
    "只包含有招生计划的科目；不得当作官方科目池使用。"
)


def _batch_meta(batch) -> dict:
    return {
        "batch_code": batch.batch_code,
        "batch_name": batch.batch_name,
        "unit_type": batch.unit_type.value,
        "max_volunteers": batch.max_volunteers,
        "majors_per_group": batch.majors_per_group,
        "has_major_adjustment": batch.has_major_adjustment,
        "is_parallel": batch.is_parallel,
        "tiers_quota": batch.tiers_quota,
        "verified_status": batch.verified_status.value,
        "verified_year": batch.verified_year,
        "source_url": batch.source_url,
        "source_quote": batch.source_quote,
        "assumptions": list(batch.assumptions),
        "caveats": list(batch.caveats),
        "admission_ratio": batch.admission_ratio,
        "tie_break_rules": batch.tie_break_rules,
        "adjustment_scope": batch.adjustment_scope,
        "withdrawal_clause": batch.withdrawal_clause,
        # UI 直接用这个布尔量决定是否显示「规则待核实」横幅（红线，禁止靠前端自己判断）
        "requires_banner": batch.verified_status.value in BANNER_STATUSES,
    }


def subject_pool_meta(rule, session: Session | None = None) -> dict | None:
    """选考科目池（AGENTS.md §8.1 Step 2）。

    优先返回规则包里的**官方事实**；缺失且给了 session 时，降级为
    "由招生计划反推"的视图并标注 ``origin="DATA_DERIVED"``；两者都没有则返回 ``None``。
    """
    if rule.subject_pool is not None:
        data = rule.subject_pool.model_dump(mode="json")
        data["origin"] = POOL_ORIGIN_RULE
        # 科目池也受核实等级约束：非 PRIMARY 时前端必须给出提示
        data["requires_caution"] = data["verified_status"] != "PRIMARY"
        return data
    if session is None:
        return None

    units = repo.load_units(session, rule.province, CURRENT_YEAR)
    seen: set[str] = set()
    for unit in units:
        seen.update(unit.subject_requirement.subjects)
    if not seen:
        return None
    return {
        "province": rule.province,
        "mode": None,  # 反推不出"几选几"，不得编造
        "choose": 3,
        "subjects": sorted(seen),
        "source_url": "",
        "source_quote": "",
        "verified_status": "UNVERIFIED",
        "verified_year": None,
        "caveats": [_DERIVED_POOL_CAVEAT],
        "origin": POOL_ORIGIN_DATA_DERIVED,
        "requires_caution": True,
    }


def _rule_meta(rule, session: Session | None = None) -> dict:
    statuses = {batch.verified_status.value for batch in rule.batches}
    # 红线口径与 etl/validate.py 的 W_RULE_REDLINE 一致：**全部**批次都未达 PRIMARY 才算全省红线；
    # 仅部分批次未达 PRIMARY（如上海：本科普通批 PRIMARY，其余批次 SECONDARY）只能算"需按批次提示"。
    all_unverified = bool(statuses) and all(status in BANNER_STATUSES for status in statuses)
    return {
        "province": rule.province,
        "main_batch_code": rule.main_batch_code,
        "current_year": CURRENT_YEAR,
        "subject_pool": subject_pool_meta(rule, session),
        "batches": [_batch_meta(batch) for batch in rule.batches],
        "requires_banner": all_unverified,
        "has_caution": (not all_unverified) and any(status != "PRIMARY" for status in statuses),
        "source_problems": rule.source_problems(),  # 空列表 = 来源纪律合规（M1 测试同口径）
    }


def provinces_meta(session: Session | None = None) -> list[dict]:
    """全部省份的规则摘要（含核实状态与选考科目池，供首屏 Step 1 / Step 2 使用）。"""
    return [_rule_meta(rule, session) for rule in all_rules()]


def province_rule_meta(province: str, session: Session | None = None) -> dict:
    return _rule_meta(get_rule(province), session)


def subject_coverage(session: Session, province: str, subjects: list[str]) -> dict:
    """给定选考组合的**可报专业覆盖率**（AGENTS.md §8.1 Step 2，真实统计非估算）。

    口径：该省主批次当年全部投档单位中，``core.filters.subject_matches`` 判定通过的比例。
    每个数字都能追到招生计划来源（``evidence`` 列出各省主批次规则来源）。
    """
    rule = get_rule(province)
    batch = rule.main_batch()
    units = [u for u in repo.load_units(session, province, CURRENT_YEAR) if u.batch == batch.batch_code]
    if not units:
        return {
            "province": province,
            "year": CURRENT_YEAR,
            "batch_code": batch.batch_code,
            "subjects": list(subjects),
            "total_units": 0,
            "matched_units": 0,
            "coverage": None,
            "subject_pool": subject_pool_meta(rule, session),
            "by_subject": {},
            "unmatched_examples": [],
            "source_url": batch.source_url,
            "warnings": [f"该省主批次 {batch.batch_code} 没有可统计的招生计划，覆盖率不可用。"],
        }

    matched = [u for u in units if subject_matches(u.subject_requirement, subjects)]
    by_subject: dict[str, int] = {}
    for unit in units:
        for name in set(unit.subject_requirement.subjects):
            by_subject[name] = by_subject.get(name, 0) + 1

    unmatched = [u for u in units if u not in matched][:5]
    return {
        "province": province,
        "year": CURRENT_YEAR,
        "batch_code": batch.batch_code,
        "subjects": list(subjects),
        "total_units": len(units),
        "matched_units": len(matched),
        "coverage": round(len(matched) / len(units), 4),
        "subject_pool": subject_pool_meta(rule, session),
        "by_subject": dict(sorted(by_subject.items())),
        "unmatched_examples": [
            {
                "unit_id": u.unit_id,
                "college_id": u.college_id,
                "major_name": u.major_name,
                "requirement_mode": u.subject_requirement.mode.value,
                "requirement_subjects": list(u.subject_requirement.subjects),
            }
            for u in unmatched
        ],
        "source_url": batch.source_url,
        "warnings": (
            []
            if subjects
            else ["未提供选考科目，覆盖率按全部单位统计，仅作参考。"]
        ),
    }



def tiers_meta(params: ModelParams | None = None) -> dict:
    """分层区间、默认配额、安全闸门参数（前端色带与文案的唯一来源）。"""
    params = params or ModelParams()
    meanings = {
        "CHONG": "有机会但不稳",
        "WEN": "大概率能上",
        "BAO": "很稳",
        "DIAN": "绝对兜底",
        "TOO_RISKY": "基本无望，默认不推荐",
    }
    tiers = [
        {
            "tier": name,
            "low": bounds[0],
            "high": bounds[1],
            "meaning": meanings.get(name, ""),
        }
        for name, bounds in sorted(params.tier_bounds.items(), key=lambda kv: kv[1][0])
    ]
    return {
        "tiers": tiers,
        "quota": params.quota,
        "safety_margin": params.safety_margin,
        "safety_gate": {
            "rule": "min(近三年归一化最低位次) >= 考生位次 × (1 + safety_margin)",
            "affects": ["BAO", "DIAN"],
            "downgrade_to": "WEN",
            "warning_code": "SAFETY_MARGIN_NOT_MET",
            "note": "保/垫是安全承诺：概率够高但给不出余量时降级，无本单位历史者不得判为保/垫",
        },
        "probability_interval": "UI 必须显示区间（±1σ），禁止单一精确数字（AGENTS.md §8）",
        "disclaimer": "系统输出仅供参考，最终以各省考试院官方文件与招生章程为准。",
    }


__all__ = [
    "BANNER_STATUSES",
    "POOL_ORIGIN_DATA_DERIVED",
    "POOL_ORIGIN_RULE",
    "PROVINCES",
    "province_rule_meta",
    "provinces_meta",
    "subject_coverage",
    "subject_pool_meta",
    "tiers_meta",
]
