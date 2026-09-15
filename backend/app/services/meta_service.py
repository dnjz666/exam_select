"""元数据编排（L4）：省份批次规则与分层定义。

铁律：返回的每个规则数字都必须带 ``source_url`` / ``verified_status`` / ``source_quote``
（AGENTS.md §6.6），**没有来源的数字不出现在响应里**（§7 契约铁律 3）。
"""

from __future__ import annotations

from app.core.models import ModelParams
from app.core.rules import PROVINCES, all_rules, get_rule

#: 各省需要 UI 提示横幅的核实状态（DOMAIN_RULES §1.3 红线）
BANNER_STATUSES = {"SECONDARY", "UNVERIFIED"}
CAUTION_STATUSES = {"PRIMARY_GOV"}


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


def _rule_meta(rule) -> dict:
    statuses = {batch.verified_status.value for batch in rule.batches}
    # 红线口径与 etl/validate.py 的 W_RULE_REDLINE 一致：**全部**批次都未达 PRIMARY 才算全省红线；
    # 仅部分批次未达 PRIMARY（如上海：本科普通批 PRIMARY，其余批次 SECONDARY）只能算"需按批次提示"。
    all_unverified = bool(statuses) and all(status in BANNER_STATUSES for status in statuses)
    return {
        "province": rule.province,
        "main_batch_code": rule.main_batch_code,
        "batches": [_batch_meta(batch) for batch in rule.batches],
        "requires_banner": all_unverified,
        "has_caution": (not all_unverified) and any(status != "PRIMARY" for status in statuses),
        "source_problems": rule.source_problems(),  # 空列表 = 来源纪律合规（M1 测试同口径）
    }


def provinces_meta() -> list[dict]:
    """全部省份的规则摘要（含核实状态，供首屏 Step 1 与横幅使用）。"""
    return [_rule_meta(rule) for rule in all_rules()]


def province_rule_meta(province: str) -> dict:
    return _rule_meta(get_rule(province))


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


__all__ = ["BANNER_STATUSES", "PROVINCES", "province_rule_meta", "provinces_meta", "tiers_meta"]
