"""测试工厂：构造领域对象（避免各测试文件重复拼装）。

放在 tests/ 根目录，pytest 会把它所在目录加入 sys.path，测试文件可直接 import。
"""

from __future__ import annotations

from app.core.models import (
    AdmissionRecord,
    AdmissionUnit,
    DataQuality,
    Preferences,
    StudentProfile,
    SubjectRequirement,
    UnitType,
)

PROVINCE = "zhejiang"
BATCH = "zhejiang.public.seg1"
TOTAL_CANDIDATES = 400_000
CURRENT_YEAR = 2026


def make_student(rank: int | None = 9000, **kwargs: object) -> StudentProfile:
    data: dict[str, object] = {
        "id": "stu-1",
        "province": PROVINCE,
        "year": CURRENT_YEAR,
        "subjects": ["物理", "化学", "生物"],
        "total_score": 640,
        "rank": rank,
    }
    data.update(kwargs)
    return StudentProfile(**data)  # type: ignore[arg-type]


def make_unit(
    *,
    unit_id: str | None = None,
    year: int = CURRENT_YEAR,
    batch: str = BATCH,
    province: str = PROVINCE,
    college: str = "1001",
    group: str | None = None,
    major: str = "100111",
    unit_type: UnitType = UnitType.MAJOR_COLLEGE,
    plan_count: int = 20,
    tuition: int = 6000,
    major_name: str = "计算机科学与技术",
    **kwargs: object,
) -> AdmissionUnit:
    subject_requirement = kwargs.pop("subject_requirement", None) or SubjectRequirement()
    return AdmissionUnit(  # type: ignore[arg-type]
        unit_id=unit_id or f"{province}-{year}-{college}-{group or 'NA'}-{major}",
        unit_type=unit_type,
        province=province,
        year=year,
        batch=batch,
        college_id=f"{province}-{college}",
        group_code=group,
        major_id=f"工学-{major}",
        major_name=major_name,
        subject_requirement=subject_requirement,
        plan_count=plan_count,
        tuition=tuition,
        **kwargs,
    )


def make_record(
    unit_key: str,
    *,
    year: int,
    min_rank: int | None,
    plan_count: int | None = 20,
    data_quality: str = "OK",
    total_candidates: int | None = TOTAL_CANDIDATES,
    is_collected: bool = False,
    province: str = PROVINCE,
    batch: str = BATCH,
    college: str = "1001",
    group: str | None = None,
    major: str = "100111",
    unit_type: UnitType = UnitType.MAJOR_COLLEGE,
    min_score: int | None = None,
    source_url: str = "synthetic://test",
) -> AdmissionRecord:
    return AdmissionRecord(
        unit_key=unit_key,
        province=province,
        year=year,
        batch=batch,
        unit_type=unit_type,
        college_id=f"{province}-{college}",
        group_code=group,
        major_id=f"工学-{major}",
        min_score=min_score,
        min_rank=min_rank,
        plan_count=plan_count,
        is_collected=is_collected,
        data_quality=DataQuality(data_quality),
        total_candidates=total_candidates,
        source_url=source_url,
    )


def make_history(
    unit_key: str,
    ranks: dict[int, int | None],
    *,
    plan_count: int = 20,
    total_candidates: int | None = TOTAL_CANDIDATES,
    **kwargs: object,
) -> list[AdmissionRecord]:
    """``ranks`` = {year: min_rank}（min_rank 为 None 表示缺位次）。"""
    return [
        make_record(
            unit_key,
            year=year,
            min_rank=rank,
            plan_count=plan_count,
            total_candidates=total_candidates,
            **kwargs,  # type: ignore[arg-type]
        )
        for year, rank in ranks.items()
    ]


def make_table_rows(
    *,
    province: str = PROVINCE,
    year: int = CURRENT_YEAR,
    track: str = "综合",
    total: int = TOTAL_CANDIDATES,
) -> list[dict]:
    """构造一个自洽的一分一段表（分数 700→500，累计位次按线性比例，最低分闭合到 total）。"""
    rows: list[dict] = []
    scores = list(range(700, 499, -1))
    previous = 0
    for index, score in enumerate(scores):
        cumulative = int(round(total * (index + 1) / len(scores)))
        cumulative = max(previous, cumulative)
        if index == 0:
            cumulative = max(1, cumulative)
        rows.append(
            {
                "province": province,
                "year": year,
                "track": track,
                "score": score,
                "count_at_score": cumulative - previous,
                "cumulative_rank": cumulative,
                "source_url": "synthetic://test",
            }
        )
        previous = cumulative
    rows[-1]["cumulative_rank"] = total
    rows[-1]["count_at_score"] = total - rows[-2]["cumulative_rank"]
    return rows


def default_preferences(**kwargs: object) -> Preferences:
    return Preferences(**kwargs)  # type: ignore[arg-type]
