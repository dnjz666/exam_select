"""LLM 工具定义（AGENTS.md §9.1）—— **只读**，绝不写库。

为什么工具层是防幻觉的地基
-------------------------
LLM 只能"转述工具返回值"。因此**每一个数字都必须从工具里出来、并且带着出处**——
只要有一个数字没有来源，模型就有机会在它旁边编出第二个。本模块的硬约束：

1. 每个工具返回 ``ToolResult``，含 ``data``（给模型看的数字）与 ``evidence``
   （每条带 ``source_url``）；数字与出处**同时**返回，不允许"先给数字、出处回头再说"。
2. **绝不写库**：``generate_plan`` 走 ``persist=False`` 的只读预览（§9.1「只读或需确认」），
   需要落库的动作一律由考生在前端显式点击完成。
3. 预期内的失败（查不到单位、一分一段表缺失）**不抛异常**，而是返回带错误码的结果——
   好让模型诚实地说"数据缺失"，而不是在异常里瞎猜一个数字填上。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import FilterCriteria, ModelParams, StudentProfile, unit_key_of
from app.core.probability import analog_key, estimate_probability, probability_interval
from app.core.rank import InsufficientRankData, rank_percentile, rank_to_score, score_to_rank
from app.core.rules import get_rule
from app.db import models as db
from app.db import repositories as repo
from app.services import meta_service, plan_service, recommend_service, risk_service, student_service

# ---------------------------------------------------------------------------
# 结果与错误
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """**预期内**的工具失败（未知 id、缺一分一段表…）→ 转成给模型看的错误结果。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ToolResult:
    """一次工具调用的结果：数字 + 出处 + 警告（或明确的失败原因）。"""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: dict[str, str] | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_payload(self) -> dict[str, Any]:
        """交给 LLM 的内容。

        失败时回传 ``error``（而不是空对象）：模型看到"数据缺失/查不到"才有机会
        说"我没有这个数据"，这正是我们要的行为。
        """
        payload: dict[str, Any] = {"tool": self.name}
        if self.error is not None:
            payload["error"] = self.error
            return payload
        payload["data"] = self.data
        if self.evidence:
            payload["evidence"] = self.evidence
        if self.warnings:
            payload["warnings"] = self.warnings
        return payload


@dataclass
class ToolContext:
    """工具执行上下文：数据库会话 + 当前考生（可选）。"""

    session: Session
    student_id: str | None = None
    params: ModelParams = field(default_factory=ModelParams)

    def require_student(self) -> db.Student:
        if not self.student_id:
            raise ToolError("STUDENT_REQUIRED", "这个工具需要先有考生档案（student_id 缺失）。")
        row = repo.get_student(self.session, self.student_id)
        if row is None:
            raise ToolError("STUDENT_NOT_FOUND", f"档案不存在：{self.student_id}")
        return row


# ---------------------------------------------------------------------------
# 内部小工具
# ---------------------------------------------------------------------------
def _college_block(session: Session, college_id: str) -> dict[str, Any] | None:
    college = repo.load_colleges(session).get(college_id)
    if college is None:
        return None
    return {
        "id": college.id,
        "name": college.name,
        "province": college.province,
        "city": college.city,
        "level_tags": list(college.level_tags),
        "is_public": college.is_public,
        "source_url": college.source_url,
    }


def _unit_block(unit, college_name: str | None = None) -> dict[str, Any]:
    """单位摘要（含计划数、学费——名师铁律 6/10 要求它们必须可见）。"""
    return {
        "unit_id": unit.unit_id,
        "college_id": unit.college_id,
        "college_name": college_name,
        "major_name": unit.major_name,
        "group_name": unit.group_name,
        "batch": unit.batch,
        "unit_type": unit.unit_type.value,
        "plan_count": unit.plan_count,
        "tuition": unit.tuition,
        "duration": unit.duration,
        "subject_requirement": unit.subject_requirement.model_dump(mode="json"),
        "source_url": unit.source_url,
    }


def _load_student_profile(ctx: ToolContext) -> StudentProfile:
    row = ctx.require_student()
    return student_service.ensure_rank(ctx.session, row)


def _profile_unit(ctx: ToolContext, unit_id: str):
    profile = _load_student_profile(ctx)
    units = repo.load_units(ctx.session, profile.province, profile.year)
    for unit in units:
        if unit.unit_id == unit_id:
            return profile, unit
    raise ToolError("UNIT_NOT_FOUND", f"查不到这个投档单位：{unit_id}")


def _criteria(filters: Mapping[str, Any] | None) -> FilterCriteria:
    filters = filters or {}
    return FilterCriteria(
        regions=list(filters.get("regions") or []),
        levels=list(filters.get("levels") or []),
        major_categories=list(filters.get("majors") or []),
        tuition_max=filters.get("tuition_max"),
        exclude_unit_ids=[],
    )


def _probability_block(result, params: ModelParams) -> dict[str, Any]:
    interval = probability_interval(result, params)
    return {
        "probability": result.probability,
        "probability_interval": list(interval) if interval else None,
        "tier": result.tier.value,
        "confidence": result.confidence.value,
        "predicted_min_rank": result.predicted_min_rank,
        "sigma": result.sigma,
        "evidence": [entry.model_dump(mode="json") for entry in result.evidence],
        "adjustments": [adj.model_dump(mode="json") for adj in result.adjustments],
        "reasons": list(result.reasons),
        "warnings": list(result.warnings),
    }


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------
def _get_rank_by_score(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    province = str(args["province"])
    year = int(args["year"])
    track = str(args.get("track") or "综合")
    score = int(args["score"])
    try:
        table = repo.get_rank_table(ctx.session, province, year, track)
    except (InsufficientRankData, ValueError) as exc:
        raise ToolError(
            "RANK_UNAVAILABLE",
            f"{province}/{year}/{track} 的一分一段表不可用（{exc}）：位次换算不可用，"
            "不能用估算值代替。",
        ) from None
    rank = score_to_rank(table, score)
    source_url = repo.get_rank_source_url(ctx.session, province, year, track)
    return ToolResult(
        name="get_rank_by_score",
        arguments=args,
        data={
            "province": province,
            "year": year,
            "track": track,
            "score": score,
            "rank": rank,
            "percentile": rank_percentile(rank, table.total_candidates),
            "total_candidates": table.total_candidates,
            "score_range": {"min": table.min_score, "max": table.max_score},
        },
        evidence=[
            {
                "what": "score_rank_table",
                "province": province,
                "year": year,
                "track": track,
                "source_url": source_url,
            }
        ],
    )


def _get_score_by_rank(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    province = str(args["province"])
    year = int(args["year"])
    track = str(args.get("track") or "综合")
    rank = int(args["rank"])
    try:
        table = repo.get_rank_table(ctx.session, province, year, track)
    except (InsufficientRankData, ValueError) as exc:
        raise ToolError("RANK_UNAVAILABLE", f"一分一段表不可用（{exc}）：不能用估算值代替。") from None
    score = rank_to_score(table, rank)
    source_url = repo.get_rank_source_url(ctx.session, province, year, track)
    return ToolResult(
        name="get_score_by_rank",
        arguments=args,
        data={
            "province": province,
            "year": year,
            "track": track,
            "rank": rank,
            "score": score,
            "total_candidates": table.total_candidates,
        },
        evidence=[{"what": "score_rank_table", "source_url": source_url}],
    )


def _search_units(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    province = str(args["province"])
    year = int(args["year"])
    keyword = (args.get("keyword") or "").strip()
    limit = int(args.get("limit") or 20)
    colleges = repo.load_colleges(ctx.session)
    units = repo.load_units(ctx.session, province, year)

    matched: list[tuple[Any, Any]] = []
    for unit in units:
        college = colleges.get(unit.college_id)
        name = college.name if college else ""
        if keyword and keyword not in name and keyword not in unit.major_name:
            continue
        matched.append((unit, college))
        if len(matched) >= limit:
            break

    if not matched:
        return ToolResult(
            name="search_units",
            arguments=args,
            data={"province": province, "year": year, "keyword": keyword, "units": [], "count": 0},
            warnings=[
                f"A 表（当前数据）里没有匹配「{keyword or '（无关键词）'}」的投档单位；"
                "这属于**数据缺失**，不能凭印象补一个。"
            ],
        )

    evidence: list[dict[str, Any]] = []
    for unit, college in matched:
        evidence.append(
            {
                "what": "admission_unit",
                "unit_id": unit.unit_id,
                "source_url": unit.source_url
                or (college.source_url if college else "")
                or "unknown://admission_units",
            }
        )
    return ToolResult(
        name="search_units",
        arguments=args,
        data={
            "province": province,
            "year": year,
            "keyword": keyword,
            "count": len(matched),
            "units": [
                _unit_block(unit, college.name if college else None)
                for unit, college in matched
            ],
        },
        evidence=evidence,
    )


def _get_unit_history(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    unit_id = str(args["unit_id"])
    years = int(args.get("years") or 3)
    province = unit_id.split("-", 1)[0]
    key = unit_key_of(unit_id)
    records = repo.load_history(ctx.session, province).get(key, [])
    if not records:
        raise ToolError(
            "NO_HISTORY",
            f"{unit_id} 没有任何历史记录（可能是新增专业）：无历史不得当保底，"
            "只能用同层次单位类比并标注低置信度。",
        )
    ordered = sorted(records, key=lambda record: -record.year)[:years]
    return ToolResult(
        name="get_unit_history",
        arguments=args,
        data={
            "unit_id": unit_id,
            "unit_key": key,
            "records": [
                {
                    "year": record.year,
                    "min_score": record.min_score,
                    "min_rank": record.min_rank,
                    "avg_rank": record.avg_rank,
                    "plan_count": record.plan_count,
                    "is_collected": record.is_collected,
                    "data_quality": record.data_quality.value,
                    "source_url": record.source_url,
                }
                for record in ordered
            ],
        },
        evidence=[
            {
                "what": "unit_history",
                "unit_id": unit_id,
                "year": record.year,
                "source_url": record.source_url,
            }
            for record in ordered
        ],
        warnings=(
            ["仅有 %d 年历史（请求 %d 年）：单年数据参考价值有限。" % (len(ordered), years)]
            if len(ordered) < years
            else []
        ),
    )


def _estimate_probability(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    unit_id = str(args["unit_id"])
    profile, unit = _profile_unit(ctx, unit_id)
    rule = get_rule(profile.province)
    colleges = repo.load_colleges(ctx.session)
    majors = repo.load_majors(ctx.session)
    history = repo.load_history(ctx.session, profile.province)
    units = repo.load_units(ctx.session, profile.province, profile.year)
    analog_index = repo.build_analog_index(units, history, colleges, majors)
    total_current = repo.get_province_stats(ctx.session, profile.province).get(profile.year)

    college = colleges.get(unit.college_id)
    major = majors.get(unit.major_id or "")
    bucket = analog_index.get(
        analog_key(
            college.province if college else None,
            tuple(college.level_tags) if college else (),
            major.discipline if major else None,
        ),
        [],
    )
    result = estimate_probability(
        profile,
        unit,
        history.get(unit_key_of(unit.unit_id), ()),
        rule,
        ctx.params,
        current_total_candidates=total_current,
        analog_pool=bucket,
    )
    if result.probability is None:
        return ToolResult(
            name="estimate_probability",
            arguments=args,
            data={"unit_id": unit_id, "probability": None, "tier": result.tier.value},
            warnings=[
                "无可用历史数据，也不足以构造类比池 → 概率**不计算**（宁可不答，不可编造）。",
                *result.warnings,
            ],
        )
    return ToolResult(
        name="estimate_probability",
        arguments=args,
        data={
            "unit_id": unit_id,
            "unit": _unit_block(unit, college.name if college else None),
            "student_rank": profile.rank,
            **_probability_block(result, ctx.params),
        },
        evidence=[
            {
                "what": "unit_history",
                "unit_id": unit_id,
                "year": entry.year,
                "source_url": entry.source_url,
            }
            for entry in result.evidence
        ],
    )


def _recommend_units(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    row = ctx.require_student()
    limit = int(args.get("limit") or 20)
    outcome = recommend_service.recommend(
        ctx.session,
        row,
        criteria=_criteria(args.get("filters")),  # type: ignore[arg-type]
        limit=limit,
        include_too_risky=bool(args.get("include_too_risky") or False),
        params=ctx.params,
    )
    return ToolResult(
        name="recommend_units",
        arguments=args,
        data={"items": outcome.items, "stats": outcome.stats},
        evidence=list(outcome.evidence),
        warnings=list(outcome.warnings),
    )


def _generate_plan(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """**只读预览**：算出来给考生看，但不落库（§9.1「绝不写库」）。"""
    row = ctx.require_student()
    bundle = plan_service.generate(
        ctx.session,
        row,
        criteria=_criteria(args.get("filters")),  # type: ignore[arg-type]
        preference_order=list(args.get("preference_order") or []) or None,
        obey_adjustment=args.get("obey_adjustment"),
        params=ctx.params,
        persist=False,
    )
    plan = bundle.plan
    return ToolResult(
        name="generate_plan",
        arguments=args,
        data={
            "preview": True,
            "persisted": False,
            "batch_code": plan.rule.batch_code,
            "batch_name": plan.rule.batch_name,
            "max_volunteers": plan.rule.max_volunteers,
            "has_major_adjustment": plan.rule.has_major_adjustment,
            "total_utility": plan.total_utility,
            "tier_distribution": plan.tier_distribution,
            "item_count": len(plan.items),
            "items": [
                {
                    "position": item.position,
                    "unit_id": item.unit.unit_id,
                    "college_id": item.unit.college_id,
                    "major_name": item.unit.major_name,
                    "tier": item.tier.value,
                    "probability": item.probability,
                    "probability_interval": item.probability_interval,
                    "plan_count": item.unit.plan_count,
                    "tuition": item.unit.tuition,
                    "obey_adjustment": item.obey_adjustment,
                }
                for item in plan.items
            ],
            "violations": [violation.model_dump(mode="json") for violation in plan.violations],
        },
        evidence=list(bundle.evidence),
        warnings=[
            "这是**预览**，没有保存；确认无误后请到「志愿表」页由考生本人点击生成。",
            *bundle.warnings,
        ],
    )


def _scan_risks(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    row = ctx.require_student()
    unit_ids = [str(item) for item in (args.get("unit_ids") or [])]
    plan_id = args.get("plan_id")
    if not unit_ids and plan_id:
        bundle = plan_service.load(ctx.session, str(plan_id))
        unit_ids = [item.unit.unit_id for item in bundle.plan.items]
    if not unit_ids:
        raise ToolError("NOTHING_TO_SCAN", "需要给出 plan_id 或 unit_ids 之一，否则没有可扫描的志愿。")

    outcome = risk_service.scan(
        ctx.session,
        row,
        unit_ids,
        obey_adjustment=args.get("obey_adjustment"),
        params=ctx.params,
    )
    return ToolResult(
        name="scan_risks",
        arguments=args,
        data={
            "scanned": outcome.scanned,
            "risks": [risk.model_dump(mode="json") for risk in outcome.risks],
            "by_level": _count_by_level(outcome.risks),
        },
        evidence=list(outcome.evidence),
        warnings=list(outcome.warnings),
    )


def _count_by_level(risks: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for risk in risks:
        counts[risk.level.value] = counts.get(risk.level.value, 0) + 1
    return dict(sorted(counts.items()))


def _get_college_profile(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    college_id = str(args["college_id"])
    college = repo.load_colleges(ctx.session).get(college_id)
    if college is None:
        raise ToolError("COLLEGE_NOT_FOUND", f"院校库里没有这个 id：{college_id}（不得凭印象描述它）")
    return ToolResult(
        name="get_college_profile",
        arguments=args,
        data={
            "id": college.id,
            "name": college.name,
            "province": college.province,
            "city": college.city,
            "level_tags": list(college.level_tags),
            "college_type": college.college_type,
            "affiliation": college.affiliation,
            "is_public": college.is_public,
        },
        evidence=[{"what": "colleges", "college_id": college.id, "source_url": college.source_url}],
    )


def _get_major_profile(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    major_id = str(args["major_id"])
    major = repo.load_majors(ctx.session).get(major_id)
    if major is None:
        raise ToolError("MAJOR_NOT_FOUND", f"专业库里没有这个 id：{major_id}（不得凭印象描述它）")
    return ToolResult(
        name="get_major_profile",
        arguments=args,
        data={
            "id": major.id,
            "name": major.name,
            "category": major.category,
            "discipline": major.discipline,
            "degree": major.degree,
            "duration": major.duration,
        },
        evidence=[{"what": "majors", "major_id": major.id, "source_url": major.source_url}],
    )


def _list_missing_fields(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    if not ctx.student_id:
        return ToolResult(
            name="list_missing_fields",
            arguments=args,
            data={"student_id": None, "missing_fields": ["province", "subjects", "total_score"]},
            warnings=["还没有档案：建档向导的第 1–3 步是硬门槛（AGENTS.md §8.1）。"],
        )
    row = repo.get_student(ctx.session, ctx.student_id)
    if row is None:
        raise ToolError("STUDENT_NOT_FOUND", f"档案不存在：{ctx.student_id}")
    profile = repo.row_to_student(row)
    return ToolResult(
        name="list_missing_fields",
        arguments=args,
        data={
            "student_id": profile.id,
            "missing_fields": list(profile.missing_fields),
            "complete": not profile.missing_fields,
        },
        evidence=[{"what": "student_profile", "source_url": row.source_url}],
        warnings=(
            []
            if not profile.missing_fields
            else ["档案未完成前不得进入推荐（AGENTS.md §8.1）。"]
        ),
    )


def _get_province_rule(ctx: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """省份投档规则（**只读**，含官方原文摘录与核实状态）。

    §9.1 的清单里没有这一条，但它是必要的：考生最常问的恰恰是"我这省能填几个志愿、
    有没有调剂"。没有这个工具，模型就只能凭常识答——那正是本项目最不能接受的行为。
    """
    province = str(args["province"])
    meta = meta_service.province_rule_meta(province, ctx.session)  # 未知省份 → KeyError
    main_batch = next(
        (batch for batch in meta["batches"] if batch["batch_code"] == meta["main_batch_code"]),
        None,
    )
    return ToolResult(
        name="get_province_rule",
        arguments=args,
        data={
            "province": province,
            "current_year": meta["current_year"],
            "main_batch": main_batch,
            "subject_pool": meta["subject_pool"],
            "requires_banner": meta["requires_banner"],
        },
        evidence=[
            {
                "what": "province_rule",
                "batch_code": batch["batch_code"],
                "source_url": batch["source_url"],
            }
            for batch in meta["batches"]
        ],
        warnings=(
            ["该省全部批次均未达 PRIMARY：其推荐结果不得用于真实填报。"]
            if meta["requires_banner"]
            else []
        ),
    )


# ---------------------------------------------------------------------------
# 注册表 + JSON Schema（严格：additionalProperties=false，必填项显式声明）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, Mapping[str, Any]], ToolResult]

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _obj(properties: dict[str, Any], required: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


_TOOL_LIST: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_rank_by_score",
        description="按分数查位次（含百分位与总考生数）。位次是跨年比较的唯一可靠口径。数字来自当年一分一段表。",
        parameters=_obj(
            {
                "province": {"type": "string", "description": "省份代码，如 zhejiang"},
                "year": {"type": "integer", "description": "高考年份，如 2026"},
                "track": {"type": "string", "description": "科类，3+3 固定为 综合"},
                "score": {"type": "integer", "description": "高考总分"},
            },
            ["province", "year", "score"],
        ),
        handler=_get_rank_by_score,
    ),
    ToolSpec(
        name="get_score_by_rank",
        description="按位次反查分数（等效分）。数字来自当年一分一段表。",
        parameters=_obj(
            {
                "province": {"type": "string"},
                "year": {"type": "integer"},
                "track": {"type": "string"},
                "rank": {"type": "integer"},
            },
            ["province", "year", "rank"],
        ),
        handler=_get_score_by_rank,
    ),
    ToolSpec(
        name="search_units",
        description="按关键词（院校名或专业名）检索投档单位，返回计划数、学费与选考要求。查不到就是数据缺失，不要补。",
        parameters=_obj(
            {
                "province": {"type": "string"},
                "year": {"type": "integer"},
                "keyword": {"type": "string", "description": "院校名或专业名关键词"},
                "limit": {"type": "integer", "description": "返回条数上限，默认 20"},
            },
            ["province", "year"],
        ),
        handler=_search_units,
    ),
    ToolSpec(
        name="get_unit_history",
        description="查某个投档单位的逐年投档历史（最低分、最低位次、计划数、数据质量），每条带来源。",
        parameters=_obj(
            {
                "unit_id": {"type": "string"},
                "years": {"type": "integer", "description": "取近 N 年，默认 3"},
            },
            ["unit_id"],
        ),
        handler=_get_unit_history,
    ),
    ToolSpec(
        name="estimate_probability",
        description=(
            "对某个投档单位估算录取概率（位次法，最多近三年数据）。返回概率**区间**与完整证据链；"
            "概率为 null 表示无可用历史，此时不得给出任何数字。"
        ),
        parameters=_obj(
            {"student_id": {"type": "string"}, "unit_id": {"type": "string"}},
            ["unit_id"],
        ),
        handler=_estimate_probability,
    ),
    ToolSpec(
        name="recommend_units",
        description="按考生档案生成推荐列表（已过硬约束过滤 + 概率分层 + 软偏好打分）。每项带证据链。",
        parameters=_obj(
            {
                "student_id": {"type": "string"},
                "filters": _obj(
                    {
                        "regions": {"type": "array", "items": {"type": "string"}},
                        "levels": {"type": "array", "items": {"type": "string"}},
                        "majors": {"type": "array", "items": {"type": "string"}},
                        "tuition_max": {"type": "integer"},
                    }
                ),
                "limit": {"type": "integer"},
                "include_too_risky": {"type": "boolean"},
            },
        ),
        handler=_recommend_units,
    ),
    ToolSpec(
        name="generate_plan",
        description=(
            "按考生档案生成志愿表**预览**（不保存、不写库）。返回有序志愿、分层分布与违规项；"
            "真正落库需要考生在「志愿表」页自行确认。"
        ),
        parameters=_obj(
            {
                "student_id": {"type": "string"},
                "preference_order": {"type": "array", "items": {"type": "string"}},
                "obey_adjustment": {"type": "boolean"},
                "filters": _obj(
                    {
                        "regions": {"type": "array", "items": {"type": "string"}},
                        "levels": {"type": "array", "items": {"type": "string"}},
                        "majors": {"type": "array", "items": {"type": "string"}},
                        "tuition_max": {"type": "integer"},
                    }
                ),
            },
        ),
        handler=_generate_plan,
    ),
    ToolSpec(
        name="scan_risks",
        description="对一组志愿做风险扫描（退档风险、保底不足、梯度倒挂等），每条风险带可执行建议。",
        parameters=_obj(
            {
                "student_id": {"type": "string"},
                "plan_id": {"type": "string"},
                "unit_ids": {"type": "array", "items": {"type": "string"}},
                "obey_adjustment": {"type": "boolean"},
            },
        ),
        handler=_scan_risks,
    ),
    ToolSpec(
        name="get_college_profile",
        description="查院校档案（层次标签、城市、办学性质、来源）。查不到就说没有，不要凭印象描述。",
        parameters=_obj({"college_id": {"type": "string"}}, ["college_id"]),
        handler=_get_college_profile,
    ),
    ToolSpec(
        name="get_major_profile",
        description="查专业档案（门类、专业类、学位、学制）。查不到就说没有。",
        parameters=_obj({"major_id": {"type": "string"}}, ["major_id"]),
        handler=_get_major_profile,
    ),
    ToolSpec(
        name="list_missing_fields",
        description="查考生档案还缺哪些必填字段。缺字段时应先追问，不要替考生假设。",
        parameters=_obj({"student_id": {"type": "string"}}),
        handler=_list_missing_fields,
    ),
    ToolSpec(
        name="get_province_rule",
        description=(
            "查某省当年投档规则（投档单位类型、志愿数量、组内专业数、是否有专业调剂、"
            "选考科目池）与官方原文摘录、核实状态。"
        ),
        parameters=_obj({"province": {"type": "string"}}, ["province"]),
        handler=_get_province_rule,
    ),
)

TOOL_SPECS: tuple[ToolSpec, ...] = _TOOL_LIST
TOOL_REGISTRY: dict[str, ToolSpec] = {spec.name: spec for spec in _TOOL_LIST}
TOOL_SCHEMAS: list[dict[str, Any]] = [spec.openai_schema() for spec in _TOOL_LIST]


def call_tool(ctx: ToolContext, name: str, arguments: Mapping[str, Any] | None = None) -> ToolResult:
    """执行工具。**任何失败都变成结果**，不向上抛——否则 agent 循环会因一次查询失败而崩掉。"""
    args = dict(arguments or {})
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return ToolResult(
            name=name,
            arguments=args,
            error={"code": "UNKNOWN_TOOL", "message": f"没有这个工具：{name}"},
        )
    # 惰性注入 student_id：模型不必每次重复传
    if ctx.student_id and not args.get("student_id") and "student_id" in spec.parameters.get("properties", {}):
        args["student_id"] = ctx.student_id
    try:
        return spec.handler(ctx, args)
    except ToolError as exc:
        return ToolResult(
            name=name, arguments=args, error={"code": exc.code, "message": exc.message}
        )
    except KeyError as exc:
        return ToolResult(
            name=name,
            arguments=args,
            error={"code": "NOT_FOUND", "message": f"找不到对应的数据：{exc}"},
        )
    except Exception as exc:  # pragma: no cover - 兜底，避免 agent 循环被单点异常打断
        return ToolResult(
            name=name,
            arguments=args,
            error={"code": "INTERNAL_ERROR", "message": f"工具执行失败：{type(exc).__name__}: {exc}"},
        )


__all__ = [
    "TOOL_REGISTRY",
    "TOOL_SCHEMAS",
    "TOOL_SPECS",
    "ToolContext",
    "ToolError",
    "ToolResult",
    "ToolSpec",
    "call_tool",
]
