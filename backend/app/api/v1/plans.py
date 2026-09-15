"""志愿表端点（AGENTS.md §7 ``/plans/*``）。

- ``POST /plans/generate``：生成志愿表（含风险扫描与逐项证据）
- ``GET /plans/{id}``：读取（含分层分布、违规、风险）
- ``PATCH /plans/{id}/items``：手改顺序/增删（改完立即重算违规与风险）
- ``POST /plans/{id}/validate``：只重跑校验与风险扫描
- ``GET /plans/{id}/export?format=pdf|xlsx``：导出报告（含免责声明与来源清单）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import DbDep
from app.api.schemas import Envelope, PlanGenerateRequest, PlanPatchRequest
from app.db import repositories as repo
from app.services import backtest_service, plan_service, report_service

router = APIRouter(prefix="/plans", tags=["plans"])


def _bundle_payload(bundle: plan_service.PlanBundle) -> dict:
    return {
        "plan": bundle.plan.model_dump(mode="json"),
        "risks": [risk.model_dump(mode="json") for risk in bundle.risks],
        "stats": bundle.stats,
    }


@router.post("/generate", response_model=Envelope[dict], summary="生成志愿表")
def generate_plan(payload: PlanGenerateRequest, session: DbDep) -> Envelope[dict]:
    row = repo.get_student(session, payload.student_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"档案不存在：{payload.student_id}")

    bundle = plan_service.generate(
        session,
        row,
        criteria=payload.filters.to_criteria(),
        weights=payload.weights,
        plan_id=payload.plan_id,
        preference_order=payload.preference_order,
        obey_adjustment=payload.obey_adjustment,
    )
    return Envelope[dict](
        data=_bundle_payload(bundle), evidence=bundle.evidence, warnings=bundle.warnings
    )


@router.get("/{plan_id}", response_model=Envelope[dict], summary="读取志愿表")
def get_plan(plan_id: str, session: DbDep) -> Envelope[dict]:
    bundle = plan_service.load(session, plan_id)
    return Envelope[dict](
        data=_bundle_payload(bundle), evidence=bundle.evidence, warnings=bundle.warnings
    )


@router.patch("/{plan_id}/items", response_model=Envelope[dict], summary="手改志愿表（覆盖式）")
def patch_items(plan_id: str, payload: PlanPatchRequest, session: DbDep) -> Envelope[dict]:
    items = [entry.model_dump() for entry in payload.items]
    bundle = plan_service.patch_items(
        session, plan_id, items=items, obey_adjustment=payload.obey_adjustment
    )
    return Envelope[dict](
        data=_bundle_payload(bundle), evidence=bundle.evidence, warnings=bundle.warnings
    )


@router.post("/{plan_id}/validate", response_model=Envelope[dict], summary="风险扫描（重跑）")
def validate_plan(plan_id: str, session: DbDep) -> Envelope[dict]:
    bundle = plan_service.validate(session, plan_id)
    return Envelope[dict](
        data=_bundle_payload(bundle), evidence=bundle.evidence, warnings=bundle.warnings
    )


@router.get("/{plan_id}/export", summary="导出报告（pdf | xlsx）")
def export_plan(
    plan_id: str,
    session: DbDep,
    format: str = Query(default="pdf", pattern="^(pdf|xlsx)$", description="pdf 或 xlsx"),
) -> Response:
    content, media_type, filename = report_service.export(session, plan_id, format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["backtest_service", "router"]
