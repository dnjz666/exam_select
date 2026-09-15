"""推荐端点（AGENTS.md §7 ``POST /recommend``）。

响应形状：``data = {items: [...], stats: {...}}``，每个 item 都带
``probability / probability_interval / tier / confidence / utility / evidence / adjustments /
reasons / warnings``（§7 + §8"概率必须显示为区间"）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import DbDep
from app.api.schemas import Envelope, RecommendRequest
from app.db import repositories as repo
from app.services import recommend_service

router = APIRouter(tags=["recommend"])


@router.post("/recommend", response_model=Envelope[dict], summary="核心推荐")
def recommend(payload: RecommendRequest, session: DbDep) -> Envelope[dict]:
    row = repo.get_student(session, payload.student_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"档案不存在：{payload.student_id}")

    outcome = recommend_service.recommend(
        session,
        row,
        criteria=payload.filters.to_criteria(),
        limit=payload.limit,
        include_too_risky=payload.include_too_risky,
        weights=payload.weights,
        intent_as_hard=payload.filters.intent_as_hard,
    )
    return Envelope[dict](
        data={"items": outcome.items, "stats": outcome.stats},
        evidence=outcome.evidence,
        warnings=outcome.warnings,
    )


__all__ = ["router"]
