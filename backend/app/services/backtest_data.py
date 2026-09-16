"""编排服务：为回测/标定装配数据（L4 层，AGENTS.md §3.1「services 负责查库 → 组装 → 调 core」）。

core 保持纯函数（ADR-003），凡是"查库、拼对象、造考生队列"都放在这里。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select

from app.core.models import (
    AdmissionRecord,
    AdmissionUnit,
    College,
    DataQuality,
    Major,
    StudentProfile,
    SubjectRequirement,
    UnitType,
    unit_key_of,
)
from app.core.probability import AnalogUnit
from app.core.rank import RankTable, build_rank_table, rank_to_score
from app.core.rules import get_rule
from app.db import models as db
from app.db import repositories as repo
from app.db.session import SessionLocal
from app.etl.synthetic import CURRENT_YEAR


@dataclass
class BacktestContext:
    """一次回测所需的全部输入（已组装好，core 可直接消费）。"""

    province: str
    year: int
    rule: object
    batch: object
    total_candidates: int
    units: list[AdmissionUnit] = field(default_factory=list)
    history_by_key: dict[str, list[AdmissionRecord]] = field(default_factory=dict)
    actual_min_rank: dict[str, int] = field(default_factory=dict)
    analog_units: list[AnalogUnit] = field(default_factory=list)
    level_tags_by_college: dict[str, tuple[str, ...]] = field(default_factory=dict)
    rank_table: RankTable | None = None

    def make_students(self, count: int = 150) -> list[StudentProfile]:
        """确定性考生队列：位次覆盖竞争区间（越靠前越密集），分数由位次反查（自洽）。"""
        assert self.rank_table is not None
        students: list[StudentProfile] = []
        count = max(2, count)
        for index in range(count):
            ratio = 0.004 + 0.796 * (index / (count - 1)) ** 1.6
            rank = max(1, min(self.total_candidates, int(round(self.total_candidates * ratio))))
            students.append(
                StudentProfile(
                    id=f"bt-{self.province}-{self.year}-{index:04d}",
                    province=self.province,
                    year=self.year,
                    subjects=["物理", "化学", "生物"],
                    total_score=rank_to_score(self.rank_table, rank),
                    rank=rank,
                    single_subject_scores={"英语": 120},
                )
            )
        return students


def _to_unit(row: db.AdmissionUnitRow, *, year: int, plan_count: int) -> AdmissionUnit:
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


def _to_record(row: db.AdmissionHistory) -> AdmissionRecord:
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


def load_backtest_context(province: str, year: int) -> BacktestContext:
    """装载回测所需的单位（目标年视图）、历史、地面真值、类比池与一分一段表。

    库中单位是**填报年**（``CURRENT_YEAR``）视图；预测 ``year`` 时用该年的计划数重建视图
    （``unit_key`` 不含年份，天然可对齐）。
    """
    rule = get_rule(province)
    batch = rule.main_batch()

    with SessionLocal() as session:
        stats = repo.get_province_stats(session, province)
        if year not in stats:
            raise KeyError(f"缺少 {province}/{year} 的 province_year_stats")

        plans: dict[str, dict[int, int]] = {}
        for row in session.execute(
            select(db.AdmissionPlan).where(db.AdmissionPlan.year.in_((year, CURRENT_YEAR)))
        ).scalars():
            plans.setdefault(row.unit_key, {})[row.year] = row.plan_count

        # ★ M6（ADR-015）：真实数据的单位**逐年入库**，回测目标年 Y 优先用 Y 年自己的行
        #   （名称/选考要求/计划数都是那一年的官方口径）；模拟数据只有填报年的行，回落。
        unit_rows = list(
            session.execute(
                select(db.AdmissionUnitRow).where(
                    db.AdmissionUnitRow.province == province,
                    db.AdmissionUnitRow.year == year,
                )
            ).scalars()
        )
        if not unit_rows:
            unit_rows = list(
                session.execute(
                    select(db.AdmissionUnitRow).where(
                        db.AdmissionUnitRow.province == province,
                        db.AdmissionUnitRow.year == CURRENT_YEAR,
                    )
                ).scalars()
            )

        units: list[AdmissionUnit] = []
        for row in unit_rows:
            if row.year == year:
                units.append(_to_unit(row, year=year, plan_count=row.plan_count))
                continue
            plan = plans.get(unit_key_of(row.unit_id), {}).get(year)
            if plan:
                units.append(_to_unit(row, year=year, plan_count=plan))

        history_by_key: dict[str, list[AdmissionRecord]] = {}
        for row in session.execute(
            select(db.AdmissionHistory).where(db.AdmissionHistory.province == province)
        ).scalars():
            history_by_key.setdefault(row.unit_key, []).append(_to_record(row))

        colleges = {
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
        majors = {
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
        score_rows = [
            {
                "province": row.province,
                "year": row.year,
                "track": row.track,
                "score": row.score,
                "cumulative_rank": row.cumulative_rank,
            }
            for row in session.execute(
                select(db.ScoreRankTable).where(
                    db.ScoreRankTable.province == province, db.ScoreRankTable.year == year
                )
            ).scalars()
        ]

    rank_table = build_rank_table(score_rows, total_candidates=stats[year])

    # 地面真值（目标年实际最低位次）：优先取非征集行
    actual: dict[str, int] = {}
    for key, rows in history_by_key.items():
        candidates = [r for r in rows if r.year == year and r.min_rank is not None]
        if not candidates:
            continue
        normal = [r for r in candidates if not r.is_collected]
        actual[key] = int((normal or candidates)[0].min_rank or 0)

    analog_units = [
        AnalogUnit(
            unit=unit,
            records=history_by_key.get(unit_key_of(unit.unit_id), ()),
            level_tags=tuple(colleges[unit.college_id].level_tags) if unit.college_id in colleges else (),
            discipline=majors[unit.major_id].discipline if unit.major_id in majors else None,
            college_province=colleges[unit.college_id].province if unit.college_id in colleges else None,
        )
        for unit in units
    ]

    return BacktestContext(
        province=province,
        year=year,
        rule=rule,
        batch=batch,
        total_candidates=stats[year],
        units=units,
        history_by_key=history_by_key,
        actual_min_rank=actual,
        analog_units=analog_units,
        level_tags_by_college={cid: tuple(c.level_tags) for cid, c in colleges.items()},
        rank_table=rank_table,
    )


_ = (Mapping, Sequence)
