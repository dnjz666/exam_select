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

from app.core.models import (
    AdmissionUnit,
    Adjustment,
    Confidence,
    FilterCriteria,
    HistoryEvidence,
    PhysicalExam,
    Preferences,
    Risk,
    RuleViolation,
    ScoreBreakdown,
    Tier,
    VerifiedStatus,
    VolunteerPlan,
)
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
    filters: RecommendFilters | None = Field(
        default=None,
        description=(
            "生成该志愿表时使用的筛选条件。手改只允许在**同口径重新评估出的候选池**内增删，"
            "带上它才能保证「池」与你当初看到的推荐列表完全一致（不带则视为无筛选）。"
        ),
    )


class RiskScanRequest(BaseModel):
    student_id: str
    unit_ids: list[str] = Field(min_length=1)
    obey_adjustment: bool | None = None
    obey_adjustment_map: dict[str, bool] | None = None


# ---------------------------------------------------------------------------
# 响应载荷（★ 契约唯一来源）
# ---------------------------------------------------------------------------
# 为什么这些模型必须显式存在（AGENTS.md §4.3 硬性规则 2）：
#   前端类型**只能**由 ``/openapi.json`` 生成，禁止手写第二份。若响应体是裸 ``dict``，
#   生成的类型就是 ``{[key: string]: unknown}``，"类型从契约生成"形同虚设。
#   因此下列模型把 service 层实际返回的字段**逐字段**声明出来——
#   它们同时充当契约校验器：字段改名/漏字段会在测试中直接报 ResponseValidationError。
class CollegeBlock(BaseModel):
    """推荐项里的院校摘要（``recommend_service._college_block``）。"""

    id: str
    name: str
    province: str | None = None
    city: str | None = None
    level_tags: list[str] = Field(default_factory=list)
    is_public: bool = True
    college_type: str | None = None
    affiliation: str | None = None
    source_url: str | None = None


class MajorBlock(BaseModel):
    """推荐项里的专业摘要（``recommend_service._major_block``）。"""

    id: str
    name: str
    category: str | None = None
    discipline: str | None = None
    duration: int | None = None
    source_url: str | None = None


class RuleBlock(BaseModel):
    """推荐/志愿表所依据的批次规则快照（含核实状态，供 UI 横幅）。"""

    province: str
    batch_code: str
    batch_name: str
    unit_type: str
    max_volunteers: int
    has_major_adjustment: bool
    is_parallel: bool
    majors_per_group: int | None = None
    verified_status: VerifiedStatus
    verified_year: int | None = None
    source_url: str
    requires_banner: bool


class RecommendItem(BaseModel):
    """单个推荐项（AGENTS.md §7 + §8）。

    ``probability`` 为 ``None`` 时 ``confidence`` 必须为 ``NO_DATA`` 且 ``reasons`` 说明原因
    （契约铁律 2）；``evidence`` **必须非空**且每条带 ``source_url``（契约铁律 1）。
    """

    unit: AdmissionUnit
    college: CollegeBlock | None = None
    major: MajorBlock | None = None
    probability: float | None = None
    #: ±1σ 概率区间（UI 只显示区间，禁止单点数字，§8）
    probability_interval: list[float] | None = None
    tier: Tier = Tier.NO_DATA
    confidence: Confidence = Confidence.NO_DATA
    utility: float = 0.0
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    predicted_min_rank: float = 0.0
    sigma: float = 0.0
    evidence: list[HistoryEvidence] = Field(default_factory=list)
    adjustments: list[Adjustment] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RecommendStats(BaseModel):
    """推荐统计（tier 分布、过滤统计、数据覆盖率、所用批次规则）。"""

    units_considered: int = 0
    hard_filtered_out: int = 0
    filtered_out_reasons: dict[str, int] = Field(default_factory=dict)
    evaluated_count: int = 0
    no_data_count: int = 0
    no_evidence_count: int = 0
    data_coverage: float = 0.0
    tier_distribution: dict[str, int] = Field(default_factory=dict)
    tier_distribution_all: dict[str, int] = Field(default_factory=dict)
    returned: int = 0
    limit: int = DEFAULT_LIMIT
    include_too_risky: bool = False
    rule: RuleBlock | None = None


class RecommendPayload(BaseModel):
    items: list[RecommendItem] = Field(default_factory=list)
    stats: RecommendStats = Field(default_factory=RecommendStats)


class PlanStats(BaseModel):
    """志愿表统计：``generate`` 给全量，``load``/``validate`` 只给后两项。"""

    tier_distribution: dict[str, int] = Field(default_factory=dict)
    violations: list[RuleViolation] = Field(default_factory=list)
    candidates_evaluated: int | None = None
    excluded_too_risky: int | None = None
    no_data_count: int | None = None
    data_coverage: float | None = None


class PlanPayload(BaseModel):
    """``/plans/*`` 的统一响应体：志愿表 + 风险扫描 + 统计 + 院校索引。

    ``colleges`` 是 ``college_id -> 院校摘要`` 的索引：``PlanItem`` 只带 ``college_id``，
    志愿表页面没有院校名就无法阅读（AGENTS.md §8.2）。索引来自数据库、每条带 ``source_url``，
    不是前端拼的展示数据。
    """

    plan: VolunteerPlan
    risks: list[Risk] = Field(default_factory=list)
    stats: PlanStats = Field(default_factory=PlanStats)
    colleges: dict[str, CollegeBlock] = Field(default_factory=dict)


class StudentPayload(BaseModel):
    """考生档案（含 ``missing_fields``，前端据此阻止进入推荐，§8.1）。"""

    id: str
    province: str
    year: int
    track: str = "综合"
    subjects: list[str] = Field(default_factory=list)
    total_score: int = 0
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
    missing_fields: list[str] = Field(default_factory=list)
    rank_source_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ResolveRankPayload(BaseModel):
    """分数 → 位次换算结果（§8.1 Step 3：必须能显示完整溯源）。"""

    student_id: str
    total_score: int
    rank: int
    total_candidates: int
    percentile: float
    score_range: dict[str, int] = Field(default_factory=dict)
    equivalent_scores: list[dict] = Field(default_factory=list)
    source_url: str


class BatchMeta(BaseModel):
    """批次级规则（含官方原文摘录与核实状态）。"""

    batch_code: str
    batch_name: str
    unit_type: str
    max_volunteers: int
    majors_per_group: int | None = None
    has_major_adjustment: bool = False
    is_parallel: bool = True
    tiers_quota: dict[str, float] | None = None
    verified_status: VerifiedStatus = VerifiedStatus.UNVERIFIED
    verified_year: int | None = None
    source_url: str = ""
    source_quote: str = ""
    assumptions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    admission_ratio: str | None = None
    tie_break_rules: list[str] | None = None
    adjustment_scope: str | None = None
    withdrawal_clause: list[str] | None = None
    #: UI 直接用它决定是否显示「规则待核实」横幅（红线，禁止前端自行判断）
    requires_banner: bool = False


class SubjectPoolMeta(BaseModel):
    """省份选考科目池（AGENTS.md §8.1 Step 2）。

    ``origin="RULE"`` = 官方来源的规则事实；``origin="DATA_DERIVED"`` = 未核实到原文时
    由招生计划反推的降级视图（``requires_caution=True``，前端必须提示，不得当成官方科目池）。
    """

    province: str
    mode: str | None = None
    choose: int = 3
    subjects: list[str] = Field(default_factory=list)
    source_url: str = ""
    source_quote: str = ""
    verified_status: VerifiedStatus = VerifiedStatus.UNVERIFIED
    verified_year: int | None = None
    caveats: list[str] = Field(default_factory=list)
    origin: str = "RULE"
    requires_caution: bool = False


class ProvinceMeta(BaseModel):
    """``GET /meta/provinces`` 的单省条目。"""

    province: str
    main_batch_code: str
    current_year: int = CURRENT_YEAR
    subject_pool: SubjectPoolMeta | None = None
    batches: list[BatchMeta] = Field(default_factory=list)
    requires_banner: bool = False
    has_caution: bool = False
    source_problems: list[str] = Field(default_factory=list)


class UnmatchedUnit(BaseModel):
    """覆盖率统计里"因选考不匹配被排除"的示例单位。"""

    unit_id: str
    college_id: str
    major_name: str
    requirement_mode: str
    requirement_subjects: list[str] = Field(default_factory=list)


class SubjectCoveragePayload(BaseModel):
    """选考组合的可报专业覆盖率（真实统计，非估算）。"""

    province: str
    year: int
    batch_code: str
    subjects: list[str] = Field(default_factory=list)
    total_units: int = 0
    matched_units: int = 0
    coverage: float | None = None
    subject_pool: SubjectPoolMeta | None = None
    by_subject: dict[str, int] = Field(default_factory=dict)
    unmatched_examples: list[UnmatchedUnit] = Field(default_factory=list)
    source_url: str = ""
    warnings: list[str] = Field(default_factory=list)


class TierMeta(BaseModel):
    tier: str
    low: float
    high: float
    meaning: str = ""


class SafetyGateMeta(BaseModel):
    rule: str
    affects: list[str] = Field(default_factory=list)
    downgrade_to: str = ""
    warning_code: str = ""
    note: str = ""


class TiersPayload(BaseModel):
    """分层区间、默认配额、安全闸门（前端色带与文案的唯一来源）。"""

    tiers: list[TierMeta] = Field(default_factory=list)
    quota: dict[str, float] = Field(default_factory=dict)
    safety_margin: float = 0.0
    safety_gate: SafetyGateMeta | None = None
    probability_interval: str = ""
    disclaimer: str = ""


class UnitHistoryRecord(BaseModel):
    year: int
    min_score: int | None = None
    min_rank: int | None = None
    avg_score: int | None = None
    avg_rank: int | None = None
    plan_count: int | None = None
    admitted_count: int | None = None
    is_collected: bool = False
    data_quality: str = "OK"
    total_candidates: int | None = None
    source_url: str = ""


class UnitHistoryPayload(BaseModel):
    unit_id: str
    unit_key: str
    unit: AdmissionUnit | None = None
    records: list[UnitHistoryRecord] = Field(default_factory=list)


class CollegeSearchItem(BaseModel):
    id: str
    name: str
    province: str | None = None
    city: str | None = None
    level_tags: list[str] = Field(default_factory=list)
    college_type: str | None = None
    affiliation: str | None = None
    is_public: bool = True
    source_url: str | None = None


class MajorSearchItem(BaseModel):
    id: str
    name: str
    category: str | None = None
    discipline: str | None = None
    degree: str | None = None
    duration: int | None = None
    source_url: str | None = None


class RiskScanPayload(BaseModel):
    risks: list[Risk] = Field(default_factory=list)
    scanned: int = 0
    by_level: dict[str, int] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    """一条会话消息（M3 存内存；``missing_fields`` / ``note`` 仅 assistant 侧出现）。"""

    id: str
    session_id: str
    role: str
    content: str
    created_at: str | None = None
    student_id: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    note: str | None = None


class ChatHistoryPayload(BaseModel):
    session_id: str
    messages: list[ChatMessage] = Field(default_factory=list)
    count: int = 0


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
    "BatchMeta",
    "ChatHistoryPayload",
    "ChatMessage",
    "ChatRequest",
    "CollegeBlock",
    "CollegeSearchItem",
    "Envelope",
    "ErrorBody",
    "ErrorResponse",
    "MajorBlock",
    "MajorSearchItem",
    "PlanGenerateRequest",
    "PlanItemPatch",
    "PlanPatchRequest",
    "PlanPayload",
    "PlanStats",
    "ProvinceMeta",
    "RecommendFilters",
    "RecommendItem",
    "RecommendPayload",
    "RecommendRequest",
    "RecommendStats",
    "ResolveRankPayload",
    "RiskScanPayload",
    "RiskScanRequest",
    "RuleBlock",
    "SafetyGateMeta",
    "StudentCreateRequest",
    "StudentPatchRequest",
    "StudentPayload",
    "SubjectCoveragePayload",
    "SubjectPoolMeta",
    "TierMeta",
    "TiersPayload",
    "UnmatchedUnit",
    "UnitHistoryPayload",
    "UnitHistoryRecord",
]

