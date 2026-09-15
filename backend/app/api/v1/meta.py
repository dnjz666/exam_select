"""元数据端点（AGENTS.md §7）。

- ``GET /meta/provinces``：各省规则（含 source_url 与核实状态，供首屏横幅）
- ``GET /meta/provinces/{province}/rule``：单省规则（批次级）
- ``GET /meta/tiers``：分层区间、配额、安全闸门与免责声明
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import Envelope
from app.core.rules import PROVINCES
from app.services import meta_service

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/provinces", response_model=Envelope[list[dict]], summary="各省规则（含 source_url）")
def list_provinces() -> Envelope[list[dict]]:
    provinces = meta_service.provinces_meta()
    warnings: list[str] = []
    for item in provinces:
        if item["requires_banner"]:
            warnings.append(
                f"{item['province']}：全部批次均未达 PRIMARY，UI 必须显示「规则待核实」横幅，"
                "其推荐结果不得用于真实填报。"
            )
        elif item["has_caution"]:
            warnings.append(f"{item['province']}：存在未达 PRIMARY 的批次，需按批次提示核实状态。")
    evidence = [
        {"what": "province_rule", "province": item["province"], "source_url": batch["source_url"]}
        for item in provinces
        for batch in item["batches"]
    ]
    return Envelope[list[dict]](data=provinces, evidence=evidence, warnings=sorted(warnings))


@router.get("/provinces/{province}/rule", response_model=Envelope[dict], summary="单省规则（批次级）")
def get_rule(province: str) -> Envelope[dict]:
    meta = meta_service.province_rule_meta(province)  # 未知省份 → KeyError → 404（见 main 处理器）
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
    evidence = [
        {"what": "province_rule", "batch_code": batch["batch_code"], "source_url": batch["source_url"]}
        for batch in meta["batches"]
    ]
    return Envelope[dict](data=meta, evidence=evidence, warnings=warnings)


@router.get("/tiers", response_model=Envelope[dict], summary="分层/配额/安全闸门定义")
def get_tiers() -> Envelope[dict]:
    return Envelope[dict](
        data=meta_service.tiers_meta(),
        evidence=[{"what": "model_params", "source": "docs/DOMAIN_RULES.md §3"}],
        warnings=[],
    )


__all__ = ["PROVINCES", "router"]
