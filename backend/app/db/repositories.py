"""数据访问层（L2，AGENTS.md §4.2：``repositories.py`` 供 L4 调用）。

纪律
----
- **只有本模块与 ``services/`` 允许碰 DB**；``core/`` 是纯函数（ADR-003）。
- 所有从库里读出来的数字都带 ``source_url``（契约铁律 §7："响应中禁止出现无来源的数字字段"）。
- 单位视图支持"按年份重建"：库中单位是**填报年**（``CURRENT_YEAR``）的视图，
  预测/回测目标年 Y 时用 Y 年计划数重建（``unit_key`` 不含年份，天然可对齐）。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (
    AdmissionRecord,
    AdmissionUnit,
    College,
    DataQuality,
    Major,
    PhysicalExam,
    Preferences,
    StudentProfile,
    SubjectRequirement,
    UnitType,
    unit_key_of,
)
from app.core.probability import AnalogUnit, analog_key
from app.core.rank import RankTable, build_rank_table
from app.db import models as db
from app.etl.synthetic import CURRENT_YEAR


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# 基础数据
# ---------------------------------------------------------------------------
def get_province_stats(session: Session, province: str) -> dict[int, int]:
    """``{year: total_candidates}``（位次归一化的分母来源，禁止估算）。"""
    rows = session.execute(
        select(db.ProvinceYearStats).where(db.ProvinceYearStats.province == province)
    ).scalars()
    return {row.year: row.total_candidates for row in rows}


def get_rank_table(session: Session, province: str, year: int, track: str = "综合") -> RankTable:
    """构建一分一段表；缺数据时抛 :class:`InsufficientRankData`（禁止估算位次）。"""
    rows = [
        {
            "province": row.province,
            "year": row.year,
            "track": row.track,
            "score": row.score,
            "cumulative_rank": row.cumulative_rank,
        }
        for row in session.execute(
            select(db.ScoreRankTable).where(
                db.ScoreRankTable.province == province,
                db.ScoreRankTable.year == year,
                db.ScoreRankTable.track == track,
            )
        ).scalars()
    ]
    total = get_province_stats(session, province).get(year)
    return build_rank_table(rows, total_candidates=total)


def load_colleges(session: Session) -> dict[str, College]:
    return {
        row.id: College(
            id=row.id,
            code=row.code,
            name=row.name,
            province=row.province,
            city=row.city,
            level_tags=json.loads(row.level_tags or "[]"),
            college_type=row.college_type,
            affiliation=row.affiliation,
            is_public=bool(row.is_public),
            postgrad_rate=row.postgrad_rate,
            master_points=row.master_points,
            doctor_points=row.doctor_points,
            source_url=row.source_url,
        )
        for row in session.execute(select(db.College)).scalars()
    }


def load_majors(session: Session) -> dict[str, Major]:
    return {
        row.id: Major(
            id=row.id,
            code=row.code,
            name=row.name,
            category=row.category,
            discipline=row.discipline,
            degree=row.degree,
            duration=row.duration,
            subject_eval_grade=row.subject_eval_grade,
            source_url=row.source_url,
        )
        for row in session.execute(select(db.Major)).scalars()
    }


def to_unit(row: db.AdmissionUnitRow, *, year: int, plan_count: int) -> AdmissionUnit:
    return AdmissionUnit(
        unit_id=row.unit_id,
        unit_type=UnitType(row.unit_type),
        province=row.province,
        year=year,
        batch=row.batch,
        college_id=row.college_id,
        group_code=row.group_code,
        group_name=row.group_name,
        major_id=row.major_id,
        major_name=row.major_name,
        subject_requirement=SubjectRequirement(**json.loads(row.subject_requirement)),
        plan_count=plan_count,
        tuition=row.tuition or 0,
        duration=row.duration or 4,
        campus=row.campus,
        remarks=row.remarks,
    )


def to_record(row: db.AdmissionHistory) -> AdmissionRecord:
    return AdmissionRecord(
        unit_key=row.unit_key,
        province=row.province,
        year=row.year,
        batch=row.batch,
        unit_type=UnitType(row.unit_type),
        college_id=row.college_id,
        group_code=row.group_code,
        major_id=row.major_id,
        min_score=row.min_score,
        min_rank=row.min_rank,
        avg_score=row.avg_score,
        avg_rank=row.avg_rank,
        plan_count=row.plan_count,
        admitted_count=row.admitted_count,
        is_collected=bool(row.is_collected),
        data_quality=DataQuality(row.data_quality),
        total_candidates=row.total_candidates,
        source_url=row.source_url,
    )


def load_units(
    session: Session, province: str, year: int, *, plan_year: int | None = None
) -> list[AdmissionUnit]:
    """该省该年的投档单位。

    ``plan_year`` 为 None 时直接用库中单位的 ``plan_count``（填报年视图）；
    指定年份时用 ``admission_plans`` 里该年的计划数重建视图（历史/回测视图）。
    """
    plan_counts: dict[str, int] = {}
    if plan_year is not None:
        plan_counts = {
            row.unit_key: row.plan_count
            for row in session.execute(
                select(db.AdmissionPlan).where(db.AdmissionPlan.year == plan_year)
            ).scalars()
        }

    units: list[AdmissionUnit] = []
    for row in session.execute(
        select(db.AdmissionUnitRow).where(
            db.AdmissionUnitRow.province == province, db.AdmissionUnitRow.year == CURRENT_YEAR
        )
    ).scalars():
        if plan_year is None:
            units.append(to_unit(row, year=row.year, plan_count=row.plan_count))
            continue
        plan = plan_counts.get(unit_key_of(row.unit_id))
        if plan:
            units.append(to_unit(row, year=plan_year, plan_count=plan))
    return units


def load_history(session: Session, province: str) -> dict[str, list[AdmissionRecord]]:
    history: dict[str, list[AdmissionRecord]] = {}
    for row in session.execute(
        select(db.AdmissionHistory).where(db.AdmissionHistory.province == province)
    ).scalars():
        history.setdefault(row.unit_key, []).append(to_record(row))
    return history


def load_actual_min_rank(session: Session, province: str, year: int) -> dict[str, int]:
    """目标年**实际**最低位次（地面真值；优先非征集行）。"""
    actual: dict[str, int] = {}
    for row in session.execute(
        select(db.AdmissionHistory).where(
            db.AdmissionHistory.province == province, db.AdmissionHistory.year == year
        )
    ).scalars():
        if row.min_rank is None:
            continue
        key = row.unit_key
        if key not in actual or not row.is_collected:
            actual[key] = int(row.min_rank)
    return actual


def build_analog_index(
    units: Sequence[AdmissionUnit],
    history: dict[str, list[AdmissionRecord]],
    colleges: dict[str, College],
    majors: dict[str, Major],
) -> dict[tuple[str | None, tuple[str, ...], str | None], list[AnalogUnit]]:
    """Step 0 类比池索引：按「院校所在省 + 层次标签 + 专业类」分桶（``probability.analog_key``）。"""
    index: dict[tuple[str | None, tuple[str, ...], str | None], list[AnalogUnit]] = {}
    for unit in units:
        college = colleges.get(unit.college_id)
        major = majors.get(unit.major_id or "")
        analog = AnalogUnit(
            unit=unit,
            records=tuple(history.get(unit_key_of(unit.unit_id), ())),
            level_tags=tuple(college.level_tags) if college else (),
            discipline=major.discipline if major else None,
            college_province=college.province if college else None,
        )
        index.setdefault(
            analog_key(analog.college_province, analog.level_tags, analog.discipline), []
        ).append(analog)
    return index


# ---------------------------------------------------------------------------
# 考生档案
# ---------------------------------------------------------------------------
def _student_fields(profile: StudentProfile, *, rank_source_url: str | None, stamp: str) -> dict:
    return {
        "id": profile.id,
        "province": profile.province,
        "year": profile.year,
        "track": profile.track,
        "subjects": json.dumps(profile.subjects, ensure_ascii=False),
        "total_score": profile.total_score,
        "rank": profile.rank,
        "gender": profile.gender,
        "is_fresh_graduate": profile.is_fresh_graduate,
        "political_status": profile.political_status,
        "foreign_language": profile.foreign_language,
        "single_subject_scores": json.dumps(profile.single_subject_scores, ensure_ascii=False),
        "physical_exam": profile.physical_exam.model_dump_json(),
        "bonus_points": profile.bonus_points,
        "bonus_type": profile.bonus_type,
        "preferences": profile.preferences.model_dump_json(),
        "missing_fields": json.dumps(profile.missing_fields, ensure_ascii=False),
        "rank_source_url": rank_source_url,
        "updated_at": stamp,
    }


def row_to_student(row: db.Student) -> StudentProfile:
    return StudentProfile(
        id=row.id,
        province=row.province,
        year=row.year,
        track=row.track,
        subjects=json.loads(row.subjects or "[]"),
        total_score=row.total_score,
        rank=row.rank,
        gender=row.gender,
        is_fresh_graduate=bool(row.is_fresh_graduate),
        political_status=row.political_status,
        foreign_language=row.foreign_language,
        single_subject_scores=json.loads(row.single_subject_scores or "{}"),
        physical_exam=PhysicalExam(**json.loads(row.physical_exam or "{}")),
        bonus_points=row.bonus_points,
        bonus_type=row.bonus_type,
        preferences=Preferences(**json.loads(row.preferences or "{}")),
        missing_fields=json.loads(row.missing_fields or "[]"),
    )


def get_student(session: Session, student_id: str) -> db.Student | None:
    return session.get(db.Student, student_id)


def create_student(
    session: Session,
    profile: StudentProfile,
    *,
    rank_source_url: str | None = None,
    stamp: str | None = None,
) -> db.Student:
    stamp = stamp or now_iso()
    row = db.Student(created_at=stamp, **_student_fields(profile, rank_source_url=rank_source_url, stamp=stamp))
    session.add(row)
    session.flush()
    return row


def update_student(
    session: Session,
    row: db.Student,
    profile: StudentProfile,
    *,
    rank_source_url: str | None = None,
    stamp: str | None = None,
) -> db.Student:
    stamp = stamp or now_iso()
    for key, value in _student_fields(profile, rank_source_url=rank_source_url, stamp=stamp).items():
        if key == "id":
            continue
        setattr(row, key, value)
    row.updated_at = stamp
    session.flush()
    return row


def list_students(session: Session) -> list[db.Student]:
    return list(session.execute(select(db.Student).order_by(db.Student.created_at)).scalars())


# ---------------------------------------------------------------------------
# 志愿表
# ---------------------------------------------------------------------------
def save_plan(
    session: Session,
    *,
    plan_id: str,
    student_id: str,
    province: str,
    batch_code: str,
    is_parallel: bool,
    payload: dict,
    risks: list[dict] | None = None,
    stamp: str | None = None,
) -> db.Plan:
    stamp = stamp or now_iso()
    row = db.Plan(
        id=plan_id,
        student_id=student_id,
        province=province,
        batch_code=batch_code,
        is_parallel=is_parallel,
        payload=json.dumps(payload, ensure_ascii=False),
        risks=json.dumps(risks or [], ensure_ascii=False),
        created_at=stamp,
        updated_at=stamp,
    )
    session.add(row)
    session.flush()
    return row


def get_plan(session: Session, plan_id: str) -> db.Plan | None:
    return session.get(db.Plan, plan_id)


def update_plan(
    session: Session,
    row: db.Plan,
    *,
    payload: dict | None = None,
    risks: list[dict] | None = None,
    stamp: str | None = None,
) -> db.Plan:
    if payload is not None:
        row.payload = json.dumps(payload, ensure_ascii=False)
    if risks is not None:
        row.risks = json.dumps(risks, ensure_ascii=False)
    row.updated_at = stamp or now_iso()
    session.flush()
    return row


def list_plans(session: Session, student_id: str | None = None) -> list[db.Plan]:
    stmt = select(db.Plan).order_by(db.Plan.created_at)
    if student_id:
        stmt = stmt.where(db.Plan.student_id == student_id)
    return list(session.execute(stmt).scalars())


__all__ = [
    "build_analog_index",
    "create_student",
    "get_plan",
    "get_province_stats",
    "get_rank_table",
    "get_student",
    "list_plans",
    "list_students",
    "load_actual_min_rank",
    "load_colleges",
    "load_history",
    "load_majors",
    "load_units",
    "now_iso",
    "row_to_student",
    "save_plan",
    "to_record",
    "to_unit",
    "update_plan",
    "update_student",
]
