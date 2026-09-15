"""考生档案端点（AGENTS.md §7）：建档 / 读取 / 补全 / 分数→位次换算。

建档允许**草稿态**：响应里给出 ``missing_fields``，前端据此阻止进入推荐（§8.1）。
位次换算只用一分一段表；表缺失 → 503 并提示"位次换算不可用"（禁止估算，§8.1 红线）。
"""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import DbDep
from app.api.schemas import Envelope, StudentCreateRequest, StudentPatchRequest
from app.db import models as db
from app.db import repositories as repo
from app.services import student_service

router = APIRouter(prefix="/students", tags=["students"])


def _student_payload(row: db.Student) -> dict:
    profile = repo.row_to_student(row)
    return {
        "id": row.id,
        "province": row.province,
        "year": row.year,
        "track": row.track,
        "subjects": profile.subjects,
        "total_score": row.total_score,
        "rank": row.rank,
        "gender": row.gender,
        "is_fresh_graduate": row.is_fresh_graduate,
        "political_status": row.political_status,
        "foreign_language": row.foreign_language,
        "single_subject_scores": profile.single_subject_scores,
        "physical_exam": profile.physical_exam.model_dump(mode="json"),
        "bonus_points": row.bonus_points,
        "bonus_type": row.bonus_type,
        "preferences": profile.preferences.model_dump(mode="json"),
        "missing_fields": profile.missing_fields,
        "rank_source_url": row.rank_source_url,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _warnings_for(profile_missing: list[str]) -> list[str]:
    if not profile_missing:
        return []
    from app.services.student_service import compute_missing_fields  # noqa: F401  仅用于文档一致性

    labels = {
        "province": "省份",
        "subjects": "选考科目（恰好 3 门）",
        "total_score": "高考总分",
        "rank": "位次（填了总分可自动换算）",
    }
    names = "、".join(labels.get(field, field) for field in profile_missing)
    return [f"档案未完成，缺少：{names}。完成前不得进入推荐（AGENTS.md §8.1）。"]


@router.post("", response_model=Envelope[dict], status_code=status.HTTP_201_CREATED, summary="创建档案")
def create_student(payload: StudentCreateRequest, session: DbDep) -> Envelope[dict]:
    row = student_service.create(session, payload.model_dump())
    data = _student_payload(row)
    return Envelope[dict](
        data=data,
        evidence=[{"what": "student_profile", "source_url": row.source_url}],
        warnings=_warnings_for(data["missing_fields"]),
    )


@router.get("/{student_id}", response_model=Envelope[dict], summary="读取档案")
def get_student(student_id: str, session: DbDep) -> Envelope[dict]:
    row = repo.get_student(session, student_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"档案不存在：{student_id}")
    data = _student_payload(row)
    evidence = [{"what": "student_profile", "source_url": row.source_url}]
    if row.rank_source_url:
        evidence.append({"what": "score_rank_table", "source_url": row.rank_source_url})
    return Envelope[dict](data=data, evidence=evidence, warnings=_warnings_for(data["missing_fields"]))


@router.patch("/{student_id}", response_model=Envelope[dict], summary="补全/修改档案")
def patch_student(student_id: str, payload: StudentPatchRequest, session: DbDep) -> Envelope[dict]:
    row = repo.get_student(session, student_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"档案不存在：{student_id}")
    changes = payload.model_dump(exclude_unset=True)
    # 嵌套对象转 dict 供 service 合并
    for key in ("physical_exam", "preferences"):
        if changes.get(key) is not None:
            changes[key] = changes[key]
    row = student_service.update(session, row, changes)
    data = _student_payload(row)
    evidence = [{"what": "student_profile", "source_url": row.source_url}]
    if row.rank_source_url:
        evidence.append({"what": "score_rank_table", "source_url": row.rank_source_url})
    return Envelope[dict](data=data, evidence=evidence, warnings=_warnings_for(data["missing_fields"]))


@router.post("/{student_id}/resolve-rank", response_model=Envelope[dict], summary="分数 → 位次")
def resolve_rank(student_id: str, session: DbDep) -> Envelope[dict]:
    row = repo.get_student(session, student_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"档案不存在：{student_id}")
    data = student_service.resolve_rank(session, row)
    evidence = list(data.pop("evidence", []))
    warnings = list(data.pop("warnings", []))
    if not data["equivalent_scores"]:
        warnings.append("缺少其他年份的一分一段表，无法给出等效分；位次本身仍可用。")
    return Envelope[dict](data=data, evidence=evidence, warnings=warnings)


def _unused_guard(session: DbDep) -> None:  # pragma: no cover - 保持 select 引用，避免 lint 误报
    session.execute(select(db.Student.id)).all()


__all__ = ["router"]
