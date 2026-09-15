"""单点风险速查端点（AGENTS.md §7 ``POST /risk/scan``）。

不生成志愿表，直接扫一组 unit_id；风险口径与志愿表完全一致（同一个 core.risk）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import DbDep
from app.api.schemas import Envelope, RiskScanPayload, RiskScanRequest
from app.db import repositories as repo
from app.services import risk_service

router = APIRouter(tags=["risk"])


@router.post(
    "/risk/scan", response_model=Envelope[RiskScanPayload], summary="志愿风险速查"
)
def scan_risks(payload: RiskScanRequest, session: DbDep) -> Envelope[dict]:
    row = repo.get_student(session, payload.student_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"档案不存在：{payload.student_id}")

    outcome = risk_service.scan(
        session,
        row,
        payload.unit_ids,
        obey_adjustment=payload.obey_adjustment,
        obey_adjustment_map=payload.obey_adjustment_map,
    )
    data = {
        "risks": [risk.model_dump(mode="json") for risk in outcome.risks],
        "scanned": outcome.scanned,
        "by_level": _by_level(outcome.risks),
    }
    return Envelope[dict](data=data, evidence=outcome.evidence, warnings=outcome.warnings)


def _by_level(risks) -> dict[str, int]:
    counts: dict[str, int] = {}
    for risk in risks:
        counts[risk.level.value] = counts.get(risk.level.value, 0) + 1
    return dict(sorted(counts.items()))


__all__ = ["router"]
