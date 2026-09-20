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
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import TypeVar

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
# 静态参考数据缓存（M6 / ADR-016）
#
# 为什么需要：M6 接入浙江真实数据后，一次推荐要读 18,543 个投档单位 + 38,957 条历史，
# 每次请求都把 SQLAlchemy 行重新组装成 Pydantic 模型（实测每次约 2 秒、构造 7.8 万个对象）。
# 但这些数据**在两次播种之间是只读的**，而一次会话里推荐接口会被反复调用
# （推荐页 → 志愿表生成 → 手改重算 → 风险扫描）。
#
# 失效策略（宁可多失效一次，也不要读到旧数据）：
# * 进程内**代数号** ``_generation``：任何写库（建档 / 存志愿表 / 追加对话）都会自增，
#   缓存键带上它，写后自然失效（``bump_generation`` 由 L4 在写事务提交后调用）；
# * 进程重启自然清空；
# * 测试与排错可用 ``disable_cache()`` 整体关掉（见 ``tests/test_loaders_zhejiang.py`` 的用法）。
# ---------------------------------------------------------------------------
_CACHE_ENABLED = True  # 由 disable_cache() 关闭（测试与排错用）
_CACHE_MAX_ENTRIES = 32
_cache: dict[tuple, object] = {}
_generation = 0
T = TypeVar("T")


def bump_generation() -> int:
    """写库后调用：让所有静态参考数据缓存失效。返回新的代数号。"""
    global _generation
    _generation += 1
    _cache.clear()
    return _generation


def disable_cache() -> None:
    """关闭静态数据缓存（测试里需要"每次都真读库"时用）。"""
    global _CACHE_ENABLED
    _CACHE_ENABLED = False
    _cache.clear()


def _cached(key: tuple, build: Callable[[], T]) -> T:
    if not _CACHE_ENABLED:
        return build()
    cache_key = (*key, _generation)
    hit = _cache.get(cache_key)
    if hit is not None:
        return hit  # type: ignore[return-value]
    value = build()
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        _cache.clear()
    _cache[cache_key] = value
    return value


# ---------------------------------------------------------------------------
# 基础数据
# ---------------------------------------------------------------------------
def get_province_stats(session: Session, province: str) -> dict[int, int]:
    """``{year: 归一化分母}``（位次归一化的分母来源，禁止估算）。

    ★ M6 口径（ADR-015）：分母是**该年分数段表覆盖的最低分对应的累计人数**
    （``total_candidates``）——它必须与库中历史位次的口径一致：浙江的历年投档数据
    （合编 PDF）覆盖到二段，最低分 268–274 分，位次上限 27.7 万–29.1 万，因此分母
    必须取"含二段"的总量；若取"一段线上线人数"（18 万左右），二段位次就会被判越界、
    跨年归一化也会失真。

    ``segment1_cumulative``（一段线上线人数）另有用途：它是**一段线口径**的锚点，
    用于标定无官方分数段表年份的曲线（见 ``etl/loaders/zhejiang.py``）。
    """
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


def get_rank_source_url(session: Session, province: str, year: int, track: str = "综合") -> str:
    """一分一段表的来源（位次必须可追溯，AGENTS.md §8.1）。

    统一放在 L2：服务层与 agent 工具层都要用，不能各写一份查询。
    """
    row = session.execute(
        select(db.ScoreRankTable.source_url)
        .where(
            db.ScoreRankTable.province == province,
            db.ScoreRankTable.year == year,
            db.ScoreRankTable.track == track,
        )
        .limit(1)
    ).scalar_one_or_none()
    return row or "unknown://score_rank_table"


def load_colleges(session: Session) -> dict[str, College]:
    def build() -> dict[str, College]:
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

    return _cached(("colleges",), build)


def load_majors(session: Session) -> dict[str, Major]:
    def build() -> dict[str, Major]:
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

    return _cached(("majors",), build)


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
        source_url=row.source_url or "",
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

    ★ M6（ADR-015）：真实数据的 ``admission_units`` **逐年入库**（浙江 2023–2026 都有行），
    因此优先取 ``year`` 那一年的行（名称、选考要求、计划数都是那一年的官方口径）。
    模拟数据只有填报年（``CURRENT_YEAR``）一份，缺该年行时回落到填报年视图，
    并用 ``admission_plans`` 里目标年的计划数重建（与原实现一致）。

    ``plan_year`` 显式传入时，无论如何都用 ``admission_plans`` 里该年的计划数覆盖。

    ★ 结果按 ``(province, year, plan_year)`` 缓存（ADR-016）：单位表在一次会话里只读，
    而推荐/志愿表/风险扫描会反复要它。
    """
    return _cached(
        ("units", province, year, plan_year),
        lambda: _load_units_uncached(session, province, year, plan_year=plan_year),
    )


def _load_units_uncached(
    session: Session, province: str, year: int, *, plan_year: int | None = None
) -> list[AdmissionUnit]:
    plan_counts: dict[str, int] = {}
    if plan_year is not None:
        plan_counts = {
            row.unit_key: row.plan_count
            for row in session.execute(
                select(db.AdmissionPlan).where(db.AdmissionPlan.year == plan_year)
            ).scalars()
        }

    rows = list(
        session.execute(
            select(db.AdmissionUnitRow).where(
                db.AdmissionUnitRow.province == province, db.AdmissionUnitRow.year == year
            )
        ).scalars()
    )
    if not rows:
        rows = list(
            session.execute(
                select(db.AdmissionUnitRow).where(
                    db.AdmissionUnitRow.province == province,
                    db.AdmissionUnitRow.year == CURRENT_YEAR,
                )
            ).scalars()
        )

    units: list[AdmissionUnit] = []
    for row in rows:
        if plan_year is None:
            units.append(to_unit(row, year=year, plan_count=row.plan_count))
            continue
        plan = row.plan_count if row.year == plan_year else plan_counts.get(unit_key_of(row.unit_id))
        if plan:
            units.append(to_unit(row, year=plan_year, plan_count=plan))
    return units


def load_history(session: Session, province: str) -> dict[str, list[AdmissionRecord]]:
    """该省全部历史行，按 ``unit_key`` 分组（组内按年份从新到旧排序）。

    ★ 结果按省缓存（ADR-016）：这是推荐路径上最贵的一次读取（浙江 38,957 行、
    每次都要重新构造 Pydantic 对象，实测 1.3 秒）。**顺带在这里排好序**——
    概率模型要求"从新到旧"，原先由 ``usable_records`` 每次现排，现在只排一次。
    """

    def build() -> dict[str, list[AdmissionRecord]]:
        history: dict[str, list[AdmissionRecord]] = {}
        for row in session.execute(
            select(db.AdmissionHistory).where(db.AdmissionHistory.province == province)
        ).scalars():
            history.setdefault(row.unit_key, []).append(to_record(row))
        for records in history.values():
            records.sort(key=lambda record: -record.year)
        return history

    return _cached(("history", province), build)


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


# ---------------------------------------------------------------------------
# 对话消息（M5）
# ---------------------------------------------------------------------------
def append_chat_message(
    session: Session,
    *,
    message_id: str,
    session_id: str,
    role: str,
    content: str,
    student_id: str | None = None,
    tool_calls: list[dict] | None = None,
    missing_fields: list[str] | None = None,
    mode: str | None = None,
    blocked: bool = False,
    stamp: str | None = None,
) -> db.ChatMessage:
    row = db.ChatMessage(
        id=message_id,
        session_id=session_id,
        student_id=student_id,
        role=role,
        content=content,
        tool_calls=json.dumps(tool_calls or [], ensure_ascii=False),
        missing_fields=json.dumps(missing_fields or [], ensure_ascii=False),
        mode=mode,
        blocked=blocked,
        created_at=stamp or now_iso(),
    )
    session.add(row)
    session.flush()
    return row


def list_chat_messages(session: Session, session_id: str) -> list[db.ChatMessage]:
    return list(
        session.execute(
            select(db.ChatMessage)
            .where(db.ChatMessage.session_id == session_id)
            .order_by(db.ChatMessage.created_at, db.ChatMessage.id)
        ).scalars()
    )


def delete_chat_session(session: Session, session_id: str) -> int:
    """删除整个会话（测试与"清空对话"用）。返回删除条数。"""
    rows = list_chat_messages(session, session_id)
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)


def row_to_chat_message(row: db.ChatMessage) -> dict:
    """落库行 → 响应体口径（与 ``api/schemas.ChatMessage`` 对齐）。"""
    return {
        "id": row.id,
        "session_id": row.session_id,
        "student_id": row.student_id,
        "role": row.role,
        "content": row.content,
        "tool_calls": json.loads(row.tool_calls or "[]"),
        "missing_fields": json.loads(row.missing_fields or "[]"),
        "mode": row.mode,
        "blocked": bool(row.blocked),
        "created_at": row.created_at,
    }


__all__ = [
    "append_chat_message",
    "build_analog_index",
    "create_student",
    "delete_chat_session",
    "get_plan",
    "get_province_stats",
    "get_rank_source_url",
    "get_rank_table",
    "get_student",
    "list_chat_messages",
    "list_plans",
    "list_students",
    "load_actual_min_rank",
    "load_colleges",
    "load_history",
    "load_majors",
    "load_units",
    "now_iso",
    "row_to_chat_message",
    "row_to_student",
    "save_plan",
    "to_record",
    "to_unit",
    "update_plan",
    "update_student",
]
