"""API Schema（AGENTS.md §7）。

契约要点
--------
- **所有响应含 ``data`` / ``evidence`` / ``warnings`` 三段**（§7 开头）；
- 领域模型（``AdmissionUnit`` / ``ProbabilityResult`` / ``VolunteerPlan`` / ``Risk``）直接复用
  ``app.core.models``，**不手写第二份类型**（ADR-004：OpenAPI 是契约唯一来源）；
- 请求模型只做"入参校验"，业务约束（如选考 3 门、位次可换算）在 service/core 层判定。
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.core.models import FilterCriteria, PhysicalExam, Preferences
from app.etl.synthetic import CURRENT_YEAR

T = TypeVar("T")

DEFAULT_LIMIT = 60
MAX_LIMIT = 500


class Envelope(BaseModel, Generic[T]):
    """统一响应信封：data + evidence + warnings（§7）。"""

    data: T
    evidence: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ErrorBody(BaseModel):
    """统一错误体（异常处理器输出）。"""

    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------------------------------------------------------------------------
# 考生档案
# ---------------------------------------------------------------------------
class StudentCreateRequest(BaseModel):
    """建档（允许草稿态：缺的字段会在响应 ``missing_fields`` 里给出）。"""

    province: str
    year: int = CURRENT_YEAR
    track: str = "综合"
    subjects: list[str] = Field(default_factory=list)
    total_score: int | None = None
    rank: int | None = None
    gender: str | None = None
    is_fresh_graduate: bool = True
    political_status: str = "群众"
    foreign_language: str = "英语"
    single_subject_scores: dict[str, int] = Field(default_factory=dict)
    physical_exam: PhysicalExam = Field(default_factory=PhysicalExam)
    bonus_points: int = 0
    bonus_type: str | None = None
    preferences: Preferences = Field(default_factory=Preferences)


class StudentPatchRequest(BaseModel):
    """增量补全（只提交要改的字段；未提交字段保持原值）。"""

    province: str | None = None
    year: int | None = None
    track: str | None = None
    subjects: list[str] | None = None
    total_score: int | None = None
    rank: int | None = None
    gender: str | None = None
    is_fresh_graduate: bool | None = None
    political_status: str | None = None
    foreign_language: str | None = None
    single_subject_scores: dict[str, int] | None = None
    physical_exam: PhysicalExam | None = None
    bonus_points: int | None = None
    bonus_type: str | None = None
    preferences: Preferences | None = None


# ---------------------------------------------------------------------------
# 推荐 / 志愿表
# ---------------------------------------------------------------------------
class RecommendFilters(BaseModel):
    """与 §7 的 ``filters:{regions,majors,levels,tuition_max}`` 对应。"""

    regions: list[str] = Field(default_factory=list)
    majors: list[str] = Field(default_factory=list)
    levels: list[str] = Field(default_factory=list)
    tuition_max: int | None = None
    exclude_unit_ids: list[str] = Field(default_factory=list)
    intent_as_hard: bool = Field(
        default=False,
        description="是否把意向省份/层次/门类当硬约束（默认 False：意向属软偏好 §6.5）",
    )

    def to_criteria(self) -> FilterCriteria:
        return FilterCriteria(
            regions=list(self.regions),
            levels=list(self.levels),
            major_categories=list(self.majors),
            tuition_max=self.tuition_max,
            exclude_unit_ids=list(self.exclude_unit_ids),
        )


class RecommendRequest(BaseModel):
    student_id: str
    filters: RecommendFilters = Field(default_factory=RecommendFilters)
    weights: dict[str, float] | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    include_too_risky: bool = False


class PlanGenerateRequest(BaseModel):
    student_id: str
    filters: RecommendFilters = Field(default_factory=RecommendFilters)
    weights: dict[str, float] | None = None
    plan_id: str | None = None
    preference_order: list[str] | None = Field(
        default=None, description="考生意愿序（unit_id 列表）；不填则按冲稳保垫 + 层内效用排序"
    )
    obey_adjustment: bool | None = Field(
        default=None, description="院校专业组模式是否服从调剂；专业+院校模式忽略"
    )


class PlanItemPatch(BaseModel):
    unit_id: str
    obey_adjustment: bool | None = None


class PlanPatchRequest(BaseModel):
    items: list[PlanItemPatch] = Field(default_factory=list, description="完整有序志愿列表（覆盖式）")
    obey_adjustment: bool | None = Field(default=None, description="统一设置服从调剂（覆盖逐项值）")


class RiskScanRequest(BaseModel):
    student_id: str
    unit_ids: list[str] = Field(min_length=1)
    obey_adjustment: bool | None = None
    obey_adjustment_map: dict[str, bool] | None = None


# ---------------------------------------------------------------------------
# 对话
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    student_id: str | None = None


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "ChatRequest",
    "Envelope",
    "ErrorBody",
    "ErrorResponse",
    "PlanGenerateRequest",
    "PlanItemPatch",
    "PlanPatchRequest",
    "RecommendFilters",
    "RecommendRequest",
    "RiskScanRequest",
    "StudentCreateRequest",
    "StudentPatchRequest",
]
