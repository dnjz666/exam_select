"""推荐端点（AGENTS.md §7 ``POST /recommend``）。

响应形状：``data = {items: [...], stats: {...}}``，每个 item 都带
``probability / probability_interval / tier / confidence / utility / evidence / adjustments /
reasons / warnings``（§7 + §8"概率必须显示为区间"）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import DbDep
from app.api.schemas import Envelope, RecommendPayload, RecommendRequest
from app.db import repositories as repo
from app.services import recommend_service

router = APIRouter(tags=["recommend"])


@router.post("/recommend", response_model=Envelope[RecommendPayload], summary="核心推荐")
def recommend(payload: RecommendRequest, session: DbDep) -> Envelope[dict]:
    row = repo.get_student(session, payload.student_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"档案不存在：{payload.student_id}")

    # ★ ADR-022：筛选与偏好**默认来自档案**（建档向导第 4 步）。
    #   只有调用方**显式**传了硬约束时才覆盖 —— 注意不能把 payload 的默认值
    #   （``intent_as_hard=False``、空列表）当成"考生要求不过滤"，
    #   否则档案里的意向会被无声抹掉（实测踩过：硬约束在 API 层被覆盖成 False）。
    filters = payload.filters
    explicit = bool(
        filters.regions or filters.levels or filters.majors or filters.exclude_unit_ids
    )
    outcome = recommend_service.recommend(
        session,
        row,
        criteria=filters.to_criteria() if explicit else None,
        limit=payload.limit,
        include_too_risky=payload.include_too_risky,
        weights=payload.weights,
        # None → 用档案里的 intent_as_hard（见 RecommendFilters 的说明）
        intent_as_hard=filters.intent_as_hard,
    )
    return Envelope[dict](
        data={"items": outcome.items, "stats": outcome.stats},
        evidence=outcome.evidence,
        warnings=outcome.warnings,
    )


__all__ = ["router"]
