"""元数据端点（AGENTS.md §7）。

- ``GET /meta/provinces``：各省规则（含 source_url、核实状态与选考科目池，供首屏）
- ``GET /meta/provinces/{province}/rule``：单省规则（批次级）
- ``GET /meta/provinces/{province}/subject-coverage``：选考组合的可报专业覆盖率（§8.1 Step 2）
- ``GET /meta/tiers``：分层区间、配额、安全闸门与免责声明
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import DbDep
from app.api.schemas import (
    Envelope,
    ProvinceMeta,
    SubjectCoveragePayload,
    TiersPayload,
)
from app.core.rules import PROVINCES
from app.services import meta_service

router = APIRouter(prefix="/meta", tags=["meta"])


def _pool_warnings(item: dict) -> list[str]:
    pool = item.get("subject_pool") or {}
    if pool.get("origin") == meta_service.POOL_ORIGIN_DATA_DERIVED:
        return [
            f"{item['province']}：选考科目池未核实到官方原文，当前列表由招生计划反推，"
            "不得当作官方科目池使用。"
        ]
    if pool.get("requires_caution"):
        return [
            f"{item['province']}：选考科目池来源等级为 {pool.get('verified_status')}"
            f"（未达 PRIMARY），使用时须按批次/来源提示核实状态。"
        ]
    return []


@router.get("/provinces", response_model=Envelope[list[ProvinceMeta]], summary="各省规则（含 source_url）")
def list_provinces(session: DbDep) -> Envelope[list[dict]]:
    provinces = meta_service.provinces_meta(session)
    warnings: list[str] = []
    for item in provinces:
        if item["requires_banner"]:
            warnings.append(
                f"{item['province']}：全部批次均未达 PRIMARY，UI 必须显示「规则待核实」横幅，"
                "其推荐结果不得用于真实填报。"
            )
        elif item["has_caution"]:
            warnings.append(f"{item['province']}：存在未达 PRIMARY 的批次，需按批次提示核实状态。")
        warnings.extend(_pool_warnings(item))
    evidence = [
        {"what": "province_rule", "province": item["province"], "source_url": batch["source_url"]}
        for item in provinces
        for batch in item["batches"]
    ]
    evidence.extend(
        {
            "what": "subject_pool",
            "province": item["province"],
            "origin": item["subject_pool"]["origin"],
            "source_url": item["subject_pool"]["source_url"],
        }
        for item in provinces
        if item.get("subject_pool")
    )
    return Envelope[list[dict]](data=provinces, evidence=evidence, warnings=sorted(warnings))


@router.get(
    "/provinces/{province}/rule",
    response_model=Envelope[ProvinceMeta],
    summary="单省规则（批次级）",
)
def get_rule(province: str, session: DbDep) -> Envelope[dict]:
    meta = meta_service.province_rule_meta(province, session)  # 未知省份 → KeyError → 404
    warnings = []
    if meta["requires_banner"]:
        warnings.append("该省全部批次未达 PRIMARY：不得用于真实填报，UI 显示「规则待核实」横幅。")
    elif meta["has_caution"]:
        warnings.append(
            "该省部分批次未达 PRIMARY（如提前批/综合评价）：主批次仍可用，"
            "但涉及这些批次时必须按批次提示核实状态。"
        )
    if meta["source_problems"]:
        warnings.append("来源纪律自检未通过：" + "；".join(meta["source_problems"]))
    warnings.extend(_pool_warnings(meta))
    evidence = [
        {"what": "province_rule", "batch_code": batch["batch_code"], "source_url": batch["source_url"]}
        for batch in meta["batches"]
    ]
    return Envelope[dict](data=meta, evidence=evidence, warnings=warnings)


@router.get(
    "/provinces/{province}/subject-coverage",
    response_model=Envelope[SubjectCoveragePayload],
    summary="选考组合的可报专业覆盖率",
)
def get_subject_coverage(
    province: str,
    session: DbDep,
    subjects: str = Query(default="", description="逗号分隔的选考科目，如 物理,化学,生物"),
) -> Envelope[dict]:
    """首屏 Step 2 的"实时可报专业覆盖率"（真实统计，非估算）。

    返回的每个数字都来自当年招生计划；``subject_pool.origin`` 标明科目池是
    官方规则（RULE）还是由招生计划反推（DATA_DERIVED）。
    """
    chosen = [s.strip() for s in subjects.split(",") if s.strip()]
    data = meta_service.subject_coverage(session, province, chosen)  # 未知省份 → 404
    evidence = [
        {
            "what": "province_rule",
            "batch_code": data["batch_code"],
            "source_url": data["source_url"],
        }
    ]
    pool = data.get("subject_pool")
    if pool:
        evidence.append(
            {
                "what": "subject_pool",
                "origin": pool["origin"],
                "source_url": pool["source_url"],
            }
        )
    warnings = list(data.get("warnings") or [])
    warnings.extend(_pool_warnings(data))
    return Envelope[dict](data=data, evidence=evidence, warnings=warnings)



@router.get(
    "/tiers", response_model=Envelope[TiersPayload], summary="分层/配额/安全闸门定义"
)
def get_tiers() -> Envelope[dict]:
    return Envelope[dict](
        data=meta_service.tiers_meta(),
        evidence=[{"what": "model_params", "source": "docs/DOMAIN_RULES.md §3"}],
        warnings=[],
    )


__all__ = ["PROVINCES", "router"]
