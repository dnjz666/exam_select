"""考生档案编排（L4）：建档 / 补全 / 分数↔位次换算。

要点
----
- 档案**允许草稿态**：缺字段写进 ``missing_fields``，前端据此阻止进入推荐（AGENTS.md §8.1）。
- 位次换算只用一分一段表；表缺失时**明确报错**，严禁估算（§8.1 红线）。
- ``rank_source_url`` 记录位次的来源，保证响应里的位次可追溯。
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.models import StudentProfile
from app.core.rank import (
    InsufficientRankData,
    equivalent_score,
    rank_percentile,
    rank_to_score,
    score_to_rank,
)
from app.db import models as db
from app.db import repositories as repo


class ProfileIncomplete(Exception):
    """档案缺字段，无法进入计算（API 层转 409 并回传 missing_fields）。"""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"档案缺字段：{'、'.join(missing)}")


class RankUnavailable(Exception):
    """一分一段表缺失/为空——位次换算不可用（禁止估算）。"""


DRAFT_SOURCE = "draft://student-profile"
REQUIRED_SUBJECT_COUNT = 3  # 3+3 模式


def compute_missing_fields(
    *, subjects: list[str], total_score: int | None, rank: int | None
) -> list[str]:
    """缺字段清单（供前端追问；一次最多问 3 个由 agent 层负责，见 §9.2）。"""
    missing: list[str] = []
    if len(subjects) != REQUIRED_SUBJECT_COUNT:
        missing.append("subjects")
    has_score = total_score is not None and total_score > 0
    has_rank = rank is not None and rank > 0
    if not has_score:
        missing.append("total_score")
    if not has_score and not has_rank:
        missing.append("rank")  # 分数与位次都缺 → 必须补一个
    return missing


def _profile_from_payload(payload: dict, *, profile_id: str) -> StudentProfile:
    data = {
        "id": profile_id,
        "province": payload["province"],
        "year": payload["year"],
        "track": payload.get("track") or "综合",
        "subjects": list(payload.get("subjects") or []),
        "total_score": payload.get("total_score") or 0,
        "rank": payload.get("rank"),
        "gender": payload.get("gender"),
        "is_fresh_graduate": payload.get("is_fresh_graduate", True),
        "political_status": payload.get("political_status") or "群众",
        "foreign_language": payload.get("foreign_language") or "英语",
        "single_subject_scores": dict(payload.get("single_subject_scores") or {}),
        "bonus_points": payload.get("bonus_points", 0),
        "bonus_type": payload.get("bonus_type"),
        "missing_fields": compute_missing_fields(
            subjects=list(payload.get("subjects") or []),
            total_score=payload.get("total_score"),
            rank=payload.get("rank"),
        ),
    }
    # 嵌套对象交给 Pydantic 校验（体检 / 偏好）
    from app.core.models import PhysicalExam, Preferences

    return StudentProfile(
        physical_exam=PhysicalExam(**(payload.get("physical_exam") or {})),
        preferences=Preferences(**(payload.get("preferences") or {})),
        **data,  # type: ignore[arg-type]
    )


def create(session: Session, payload: dict, *, profile_id: str | None = None) -> db.Student:
    # 用 uuid 而非时间戳生成 id：秒级时间戳在同一秒内会撞主键（M3 实测缺陷）
    profile_id = profile_id or f"stu-{uuid.uuid4().hex[:12]}"
    profile = _profile_from_payload(payload, profile_id=profile_id)
    return repo.create_student(session, profile, rank_source_url=None)


def update(session: Session, row: db.Student, payload: dict) -> db.Student:
    merged = {
        "province": payload.get("province", row.province),
        "year": payload.get("year", row.year),
        "track": payload.get("track", row.track),
        "subjects": payload.get("subjects", _json_list(row.subjects)),
        "total_score": payload.get("total_score", row.total_score),
        "rank": payload.get("rank", row.rank),
        "gender": payload.get("gender", row.gender),
        "is_fresh_graduate": payload.get("is_fresh_graduate", bool(row.is_fresh_graduate)),
        "political_status": payload.get("political_status", row.political_status),
        "foreign_language": payload.get("foreign_language", row.foreign_language),
        "single_subject_scores": payload.get("single_subject_scores", _json_dict(row.single_subject_scores)),
        "physical_exam": payload.get("physical_exam", _json_dict(row.physical_exam)),
        "bonus_points": payload.get("bonus_points", row.bonus_points),
        "bonus_type": payload.get("bonus_type", row.bonus_type),
        "preferences": payload.get("preferences", _json_dict(row.preferences)),
    }
    profile = _profile_from_payload(merged, profile_id=row.id)
    rank_source = row.rank_source_url
    if "rank" in payload and payload["rank"] is not None:
        rank_source = "manual://student-provided"  # 考生自填位次，来源可追溯
    return repo.update_student(session, row, profile, rank_source_url=rank_source)


def _json_list(raw: str | None) -> list:
    import json

    return json.loads(raw or "[]")


def _json_dict(raw: str | None) -> dict:
    import json

    return json.loads(raw or "{}")


def require_complete(row: db.Student) -> StudentProfile:
    """计算路径专用：档案不完整直接拒绝，绝不替考生假设。"""
    from app.db import repositories as _repo

    profile = _repo.row_to_student(row)
    missing = compute_missing_fields(
        subjects=profile.subjects,
        total_score=row.total_score,
        rank=row.rank,
    )
    if missing:
        raise ProfileIncomplete(missing)
    return profile.model_copy(update={"missing_fields": missing})


def resolve_rank(session: Session, row: db.Student) -> dict:
    """分数 → 位次（并给出等效分与百分位）。

    返回的每个数字都带 ``source_url``（来自一分一段表），缺失时抛
    :class:`RankUnavailable`——首屏必须提示"位次换算不可用"，不得估算。
    """
    profile = repo.row_to_student(row)
    if profile.total_score <= 0:
        raise ProfileIncomplete(["total_score"])
    try:
        table = repo.get_rank_table(session, row.province, row.year, row.track)
    except (InsufficientRankData, ValueError) as exc:
        raise RankUnavailable(str(exc)) from None

    rank = score_to_rank(table, profile.total_score)
    source_url = _rank_source_url(session, row.province, row.year, row.track)
    stats = repo.get_province_stats(session, row.province)

    equivalents: list[dict] = []
    for other_year in sorted((y for y in stats if y != row.year), reverse=True)[:3]:
        try:
            other_table = repo.get_rank_table(session, row.province, other_year, row.track)
        except (InsufficientRankData, ValueError):
            continue
        equivalents.append(
            {
                "year": other_year,
                "score": rank_to_score(other_table, rank),
                "source_url": _rank_source_url(session, row.province, other_year, row.track),
            }
        )

    row.rank = rank
    row.rank_source_url = source_url
    row.updated_at = repo.now_iso()
    session.flush()

    return {
        "student_id": row.id,
        "total_score": profile.total_score,
        "rank": rank,
        "total_candidates": table.total_candidates,
        "percentile": round(rank_percentile(rank, table.total_candidates), 6),
        "score_range": {"min": table.min_score, "max": table.max_score},
        "equivalent_scores": equivalents,
        "source_url": source_url,
        "evidence": [
            {
                "what": "score_rank_table",
                "province": row.province,
                "year": row.year,
                "track": row.track,
                "source_url": source_url,
            }
        ],
        "warnings": [],
    }


def _rank_source_url(session: Session, province: str, year: int, track: str) -> str:
    return repo.get_rank_source_url(session, province, year, track)


def ensure_rank(session: Session, row: db.Student) -> StudentProfile:
    """计算前保证有位次：缺位次但有分数时自动换算（并留来源）。"""
    profile = require_complete(row)
    if profile.rank is None:
        result = resolve_rank(session, row)
        profile = repo.row_to_student(row)
        profile.rank = result["rank"]
    return profile


__all__ = [
    "ProfileIncomplete",
    "RankUnavailable",
    "compute_missing_fields",
    "create",
    "ensure_rank",
    "require_complete",
    "resolve_rank",
    "update",
]

# 供上层做等价分展示（保持导入面稳定）
_ = equivalent_score
