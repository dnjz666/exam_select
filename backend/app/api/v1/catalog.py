"""数据查询端点（AGENTS.md §7 数据查询段）。

- ``GET /colleges/search``：院校检索（含层次标签与来源）
- ``GET /majors/search``：专业检索（含门类/专业类）
- ``GET /units/{unit_id}/history``：某投档单位的逐年历史（每条带 source_url）

所有返回的数字都带来源；一行数据都没有时返回空列表 + 警告，**不猜测**。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbDep
from app.api.schemas import Envelope
from app.core.models import unit_key_of
from app.db import repositories as repo

router = APIRouter(tags=["catalog"])


@router.get("/colleges/search", response_model=Envelope[list[dict]], summary="院校检索")
def search_colleges(
    session: DbDep,
    q: str | None = Query(default=None, description="院校名模糊匹配"),
    province: str | None = Query(default=None, description="院校所在省"),
    level: str | None = Query(default=None, description="层次标签，如 985 / 211 / 双一流"),
    limit: int = Query(default=50, ge=1, le=200),
) -> Envelope[list[dict]]:
    colleges = repo.load_colleges(session)
    items = []
    for college in colleges.values():
        if q and q not in college.name:
            continue
        if province and college.province != province:
            continue
        if level and level not in set(college.level_tags):
            continue
        items.append(
            {
                "id": college.id,
                "name": college.name,
                "province": college.province,
                "city": college.city,
                "level_tags": list(college.level_tags),
                "college_type": college.college_type,
                "affiliation": college.affiliation,
                "is_public": college.is_public,
                "source_url": college.source_url,
            }
        )
        if len(items) >= limit:
            break
    warnings = [] if items else ["没有匹配的院校；请放宽条件或核对关键词。"]
    evidence = [{"what": "colleges", "count": len(items), "source_url": items[0]["source_url"]}] if items else []
    return Envelope[list[dict]](data=items, evidence=evidence, warnings=warnings)


@router.get("/majors/search", response_model=Envelope[list[dict]], summary="专业检索")
def search_majors(
    session: DbDep,
    q: str | None = Query(default=None, description="专业名模糊匹配"),
    category: str | None = Query(default=None, description="门类，如 工学"),
    discipline: str | None = Query(default=None, description="专业类，如 计算机类"),
    limit: int = Query(default=50, ge=1, le=300),
) -> Envelope[list[dict]]:
    majors = repo.load_majors(session)
    items = []
    for major in majors.values():
        if q and q not in major.name:
            continue
        if category and major.category != category:
            continue
        if discipline and major.discipline != discipline:
            continue
        items.append(
            {
                "id": major.id,
                "name": major.name,
                "category": major.category,
                "discipline": major.discipline,
                "degree": major.degree,
                "duration": major.duration,
                "source_url": major.source_url,
            }
        )
        if len(items) >= limit:
            break
    warnings = [] if items else ["没有匹配的专业；请放宽条件或核对关键词。"]
    evidence = [{"what": "majors", "count": len(items), "source_url": items[0]["source_url"]}] if items else []
    return Envelope[list[dict]](data=items, evidence=evidence, warnings=warnings)


@router.get("/units/{unit_id}/history", response_model=Envelope[dict], summary="投档单位逐年历史")
def unit_history(
    unit_id: str,
    session: DbDep,
    years: int = Query(default=3, ge=1, le=10),
) -> Envelope[dict]:
    province = unit_id.split("-", 1)[0]
    key = unit_key_of(unit_id)
    history = repo.load_history(session, province).get(key, [])
    if not history:
        raise HTTPException(status_code=404, detail=f"该单位没有历史记录：{unit_id}")

    records = sorted(history, key=lambda r: -r.year)[:years]
    unit = next((u for u in repo.load_units(session, province, records[0].year, plan_year=records[0].year)
                 if unit_key_of(u.unit_id) == key), None)
    data = {
        "unit_id": unit_id,
        "unit_key": key,
        "unit": unit.model_dump(mode="json") if unit else None,
        "records": [
            {
                "year": record.year,
                "min_score": record.min_score,
                "min_rank": record.min_rank,
                "avg_score": record.avg_score,
                "avg_rank": record.avg_rank,
                "plan_count": record.plan_count,
                "admitted_count": record.admitted_count,
                "is_collected": record.is_collected,
                "data_quality": record.data_quality.value,
                "total_candidates": record.total_candidates,
                "source_url": record.source_url,
            }
            for record in records
        ],
    }
    evidence = [
        {"what": "unit_history", "unit_id": unit_id, "year": record.year, "source_url": record.source_url}
        for record in records
    ]
    warnings: list[str] = []
    if any(record.data_quality.value == "COLLECTED" for record in records):
        warnings.append("含征集志愿记录：征集线通常偏低，会高估概率（COLLECTED_ONLY）。")
    if len(records) < years:
        warnings.append(f"仅有 {len(records)} 年历史（请求 {years} 年）：单年数据参考价值有限。")
    return Envelope[dict](data=data, evidence=evidence, warnings=warnings)


__all__ = ["router"]
