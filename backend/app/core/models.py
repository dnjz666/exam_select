"""核心领域模型（L3 纯算法层的数据语言）。

铁律（AGENTS.md §3.2 / DECISIONS.md ADR-003）：
- 本模块属于 ``app.core``，**禁止** import 数据库、网络库、LLM SDK；
- 所有参数默认值唯一权威来源是 ``docs/DOMAIN_RULES.md`` §3，代码中不得另行硬编码魔数；
- 位次口径：**数值越小越靠前 = 越难考**（DOMAIN_RULES.md §2.1），全系统统一，防止方向写反。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# ====================================================================
# 枚举
# ====================================================================


class UnitType(str, Enum):
    """投档单位类型（AGENTS.md §2.1）。"""

    MAJOR_COLLEGE = "MAJOR_COLLEGE"  # 专业(类)+院校：浙江 / 山东，无调剂概念
    MAJOR_GROUP = "MAJOR_GROUP"  # 院校专业组：上海 / 北京 / 天津 / 海南，有调剂


def unit_key_from_parts(
    province: str, college_code: str, group_code: str | None, major_code: str
) -> str:
    """拼装不含年份的单位标识：``{province}-{college_code}-{group_code}-{major_code}``。

    ``group_code`` 为 None（专业+院校模式）时使用占位符 ``NA``（DATA_DICTIONARY §2.3）。
    """
    return f"{province}-{college_code}-{group_code or 'NA'}-{major_code}"


def unit_key_of(unit_id: str) -> str:
    """由 ``unit_id`` 反推 ``unit_key``（去掉年份段）。

    ``unit_id = {province}-{year}-{college_code}-{group_code}-{major_code}``
    """
    parts = str(unit_id).split("-")
    if len(parts) < 5:
        return str(unit_id)
    return "-".join([parts[0], *parts[2:]])


class Tier(str, Enum):
    """冲稳保分层（AGENTS.md §6.3）。

    概率区间由 ``ModelParams.tier_bounds`` 定义；``NO_DATA`` 表示无可用历史，
    ``probability`` 必须为 ``None``，且**不参与志愿表生成**。
    """

    CHONG = "CHONG"  # 冲 [0.10, 0.40)
    WEN = "WEN"  # 稳 [0.40, 0.75)
    BAO = "BAO"  # 保 [0.75, 0.93)
    DIAN = "DIAN"  # 垫 [0.93, 1.00]
    TOO_RISKY = "TOO_RISKY"  # [0, 0.10) 基本无望，默认不推荐
    NO_DATA = "NO_DATA"  # 无任何可用历史数据


class Confidence(str, Enum):
    """置信度分级（AGENTS.md §6.2 Step 8）。"""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NO_DATA = "NO_DATA"


class DataQuality(str, Enum):
    """历史数据质量（DOMAIN_RULES.md §2.2）。

    仅 ``OK`` / ``DERIVED`` / ``COLLECTED`` 参与概率计算；
    ``MISSING_RANK`` / ``SUSPECT`` 不参与。
    """

    OK = "OK"
    DERIVED = "DERIVED"  # 由最低分 + 一分一段表反查，权重 ×0.9
    MISSING_RANK = "MISSING_RANK"
    COLLECTED = "COLLECTED"  # 征集志愿，参与但打 COLLECTED_ONLY 风险
    SUSPECT = "SUSPECT"  # 校验不通过，触发 SUSPECT_DATA 高风险


class VerifiedStatus(str, Enum):
    """规则核实等级（DOMAIN_RULES.md §1.2 / DECISIONS.md ADR-005）。"""

    PRIMARY = "PRIMARY"  # 考试院官方文件原文
    PRIMARY_GOV = "PRIMARY_GOV"  # 政府门户转述官方文件
    SECONDARY = "SECONDARY"  # 转载源，必须回原文复核
    UNVERIFIED = "UNVERIFIED"  # 无来源，数字不得进入代码


class RiskLevel(str, Enum):
    """风险等级（AGENTS.md §6.8）；HIGH 级在 UI 必须阻断式提示。"""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SubjectReqMode(str, Enum):
    """选考科目要求编码（DOMAIN_RULES.md §2.4）。"""

    ALL_OF = "all_of"  # set(要求) ⊆ set(考生选考)
    ANY_OF = "any_of"  # set(要求) ∩ set(考生选考) ≠ ∅
    NONE = "none"  # 不限，恒通过


# ====================================================================
# 基础值对象
# ====================================================================


class SubjectRequirement(BaseModel):
    """选考科目要求（DOMAIN_RULES.md §2.4）。

    3+3 模式下考生恰好 3 门选考，判定为集合关系；
    解析失败的原始文本必须标记 ``PARSE_FAILED`` 并拒绝入库（AGENTS.md §5.2）。
    """

    mode: SubjectReqMode = SubjectReqMode.NONE
    subjects: list[str] = Field(default_factory=list)


class PhysicalExam(BaseModel):
    """体检结论（硬约束输入，AGENTS.md §5.3 / §6.4 第 4 条）。"""

    color_blindness: bool = False  # 色盲
    color_weakness: bool = False  # 色弱
    height_cm: int | None = None
    other_restrictions: list[str] = Field(default_factory=list)  # 其他受限结论原文


class Preferences(BaseModel):
    """偏好（软约束输入，AGENTS.md §6.5）。

    权重默认等权（各 1/6，归一化到 1.0，§6.5 "默认等权"），由考生在 UI 调整。
    """

    intended_regions: list[str] = Field(default_factory=list)  # 意向省份
    intended_major_categories: list[str] = Field(default_factory=list)  # 意向专业类/门类
    excluded_majors: list[str] = Field(default_factory=list)  # 明确排斥的专业（GROUP_UNACCEPTABLE 依据）
    budget_comfortable: int | None = None  # 学费舒适上限（元/年）
    budget_max: int | None = None  # 学费硬上限（元/年，视为 filters 硬约束）

    weight_region: float = 1 / 6
    weight_college_level: float = 1 / 6
    weight_major: float = 1 / 6
    weight_tuition: float = 1 / 6
    weight_city: float = 1 / 6
    weight_misc: float = 1 / 6

    model_config = ConfigDict(frozen=False)


# ====================================================================
# 考生档案（AGENTS.md §5.3）
# ====================================================================


class StudentProfile(BaseModel):
    """考生档案。``missing_fields`` 非空时前端必须阻止进入推荐（AGENTS.md §8.1）。"""

    id: str
    province: str  # zhejiang | shanghai | beijing | shandong | tianjin | hainan
    year: int
    track: str = "综合"  # 3+3 不分文理，用 "综合"；预留
    subjects: list[str] = Field(default_factory=list)  # 选考的 3 门
    total_score: int  # 高考总分（必填）
    rank: int | None = None  # 位次；缺省时由 score_rank_table 换算，绝不估算

    physical_exam: PhysicalExam = Field(default_factory=PhysicalExam)
    foreign_language: str = "英语"
    single_subject_scores: dict[str, int] = Field(default_factory=dict)

    # ---- 硬约束所需属性（AGENTS.md §6.4 第 3/7 条）
    gender: str | None = None  # "男" | "女"；None = 未采集（不得据此推断可报男生专业）
    is_fresh_graduate: bool = True  # 应届 / 往届
    political_status: str = "群众"  # 政治面貌（提前批部分院校要求党员/团员）

    bonus_points: int = 0
    bonus_type: str | None = None

    preferences: Preferences = Field(default_factory=Preferences)

    missing_fields: list[str] = Field(default_factory=list)  # 供 agent 追问


# ====================================================================
# 数据实体（与 db 表对应的只读视图，AGENTS.md §5.1 / §5.2）
# ====================================================================


class College(BaseModel):
    """院校（colleges 表）。"""

    id: str  # f"{province}-{college_code}"
    code: str
    name: str
    province: str | None = None
    city: str | None = None
    level_tags: list[str] = Field(default_factory=list)  # ["985","211","双一流"]
    college_type: str | None = None
    affiliation: str | None = None
    is_public: bool = True
    postgrad_rate: float | None = None  # 保研率
    master_points: int | None = None
    doctor_points: int | None = None
    source_url: str | None = None


class Major(BaseModel):
    """专业（majors 表）。"""

    id: str
    code: str
    name: str
    category: str | None = None  # 门类
    discipline: str | None = None  # 专业类
    degree: str | None = None
    duration: int | None = None
    subject_eval_grade: str | None = None  # 学科评估 A+/A/B+...
    source_url: str | None = None


class AdmissionUnit(BaseModel):
    """统一"投档单位"抽象（AGENTS.md §5.1）。

    浙江/山东（专业+院校）与上海/北京/天津/海南（院校专业组）的差异
    全部由 ``ProvinceRule``/``BatchRule`` 吸收，业务代码不得 if-else 区分。
    """

    unit_id: str  # f"{province}-{year}-{college_code}-{group_code}-{major_code}"
    unit_type: UnitType
    province: str
    year: int
    batch: str
    college_id: str
    group_code: str | None = None  # 专业+院校模式为 None
    group_name: str | None = None
    major_id: str | None = None
    major_name: str = ""
    subject_requirement: SubjectRequirement = Field(default_factory=SubjectRequirement)
    plan_count: int = Field(gt=0)  # 招生计划数，必须 > 0
    tuition: int  # 学费（元/年）；推荐卡片必须明示（名师铁律 10）
    duration: int = 4
    campus: str | None = None
    remarks: str | None = None
    #: 该单位招生计划数据的来源（§5.2 要求每张表都有 source_url）。
    #: 放到领域模型上而不是让调用方另找：§9.1 要求**工具的每个数字都带来源**，
    #: 而"计划数"就是单位自身的属性——来源必须随数据一起流动。
    source_url: str = ""

    # ---- 硬约束声明（AGENTS.md §6.4；默认 None/False = 无限制，绝不臆造限制）
    gender_limit: str | None = None  # "男" | "女"；None = 不限
    foreign_language_requirement: str | None = None  # 限报语种，如 "英语"；None = 不限
    single_subject_min: dict[str, int] = Field(default_factory=dict)  # 单科要求 {"英语": 120}
    fresh_graduate_only: bool = False  # 仅应届
    political_requirement: str | None = None  # 如 "中共党员"；None = 不限
    physical_requirements: list[str] = Field(default_factory=list)  # 体检受限原文关键词，如 ["色盲不宜"]
    is_withdrawn: bool = False  # 已撤销 / 停招（§6.4 第 9 条）


class AdmissionRecord(BaseModel):
    """往年投档/录取历史（admission_history 表），位次算法的输入。

    ``min_rank`` 数值越小越靠前；``total_candidates`` 必须来自
    ``province_year_stats``，不得估算（DOMAIN_RULES.md §2.3）。
    """

    unit_key: str  # 不含年份：f"{province}-{college_code}-{group_code}-{major_code}"
    province: str
    year: int
    batch: str
    unit_type: UnitType
    college_id: str
    group_code: str | None = None
    major_id: str | None = None
    min_score: int | None = None
    min_rank: int | None = None  # ★ 核心字段
    avg_score: int | None = None
    avg_rank: int | None = None
    plan_count: int | None = None
    admitted_count: int | None = None
    is_collected: bool = False  # 征集志愿（征集线通常更低，须标记）
    data_quality: DataQuality = DataQuality.OK
    total_candidates: int | None = None
    source_url: str = ""


# ====================================================================
# 概率模型输出（AGENTS.md §6.2 Step 8.5）
# ====================================================================


class HistoryEvidence(BaseModel):
    """历史证据链的一条。前端"为什么"展开与 LLM 引用的唯一数据来源。"""

    year: int
    min_rank: int | None = None
    min_score: int | None = None
    plan_count: int | None = None
    data_quality: DataQuality = DataQuality.OK
    is_collected: bool = False
    source_url: str = ""  # 无来源的证据不得出现在响应中
    #: 证据性质标注：None = 本单位历史；"类比单位 xxx" = Step 0 类比池证据（新增专业无历史）
    note: str | None = None


class Adjustment(BaseModel):
    """概率修正项（趋势 / 计划数等），每条必须可解释。"""

    name: str
    delta: float  # 对 R_pred 的相对影响（带符号）
    reason: str


class ProbabilityResult(BaseModel):
    """录取概率结果。

    契约铁律（AGENTS.md §7）：
    - ``probability`` 为 ``None`` 时 ``confidence`` 必须为 ``NO_DATA``，且 ``reasons`` 说明原因；
    - 概率永远以区间呈现（UI），本字段是算法单值，区间由前端按 sigma 派生。
    """

    probability: float | None = None  # None = 禁止编造（NO_DATA）
    tier: Tier = Tier.NO_DATA
    confidence: Confidence = Confidence.NO_DATA
    predicted_min_rank: float = 0.0
    sigma: float = 0.0
    evidence: list[HistoryEvidence] = Field(default_factory=list)
    adjustments: list[Adjustment] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)  # NO_HISTORY / COLLECTED_ONLY / 小计划 等


# ====================================================================
# 打分与志愿表（AGENTS.md §6.5 / §6.7 / §6.8）
# ====================================================================


class ScoreBreakdown(BaseModel):
    """软偏好各项得分，每项 [0,1]，可追溯（DOMAIN_RULES.md §5）。"""

    region_score: float = 0.0
    college_level_score: float = 0.0
    major_match_score: float = 0.0
    tuition_score: float = 0.0
    city_score: float = 0.0
    misc_score: float = 0.0


class ScoredUnit(BaseModel):
    """已过滤 + 已算概率 + 已打分的候选（planner 的输入）。"""

    unit: AdmissionUnit
    probability: float | None = None
    tier: Tier = Tier.NO_DATA
    confidence: Confidence = Confidence.NO_DATA
    utility: float = 0.0
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    probability_result: ProbabilityResult | None = None


class PlanItem(BaseModel):
    """志愿表中的一项（有序）。"""

    position: int  # 1-based 填报顺序；平行志愿检索严格按此顺序
    unit: AdmissionUnit
    tier: Tier = Tier.NO_DATA
    probability: float | None = None
    #: ±1σ 概率区间。志愿表页同样**只能显示区间**（AGENTS.md §8），故随志愿项一起下发，
    #: 而不是让前端拿单点概率自己编一个区间。
    probability_interval: list[float] | None = None
    utility: float = 0.0
    obey_adjustment: bool | None = None  # 院校专业组模式必填；专业+院校恒为 None
    notes: list[str] = Field(default_factory=list)


class RuleViolation(BaseModel):
    """规则校验违规（``BatchRule.validate_plan`` 输出）。"""

    code: str
    message: str
    unit_id: str | None = None
    position: int | None = None


class ProvinceRuleInfo(BaseModel):
    """志愿表落库/展示用的规则快照（批次级，ADR-006）。"""

    province: str
    batch_code: str
    batch_name: str
    unit_type: UnitType
    max_volunteers: int
    majors_per_group: int | None = None
    has_major_adjustment: bool = False
    is_parallel: bool = True
    verified_status: VerifiedStatus = VerifiedStatus.UNVERIFIED
    verified_year: int | None = None
    source_url: str = ""


class VolunteerPlan(BaseModel):
    """完整志愿表（AGENTS.md §6.7 输出）。"""

    id: str
    student_id: str
    province: str
    rule: ProvinceRuleInfo
    items: list[PlanItem]  # 有序！
    tier_distribution: dict[str, int] = Field(default_factory=dict)  # Tier 名 -> 数量
    total_utility: float = 0.0
    violations: list[RuleViolation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Risk(BaseModel):
    """风险项（AGENTS.md §6.8）：每个风险必须给出可执行建议。"""

    code: str  # 如 NO_SAFETY_NET / NO_OBEDIENCE ...
    level: RiskLevel
    unit_id: str | None = None
    message: str
    suggestion: str


# ====================================================================
# 硬约束过滤结果（AGENTS.md §6.4）
# ====================================================================


class RejectionReason(BaseModel):
    """被剔除的一项，**必须可解释**（用于"为什么没推荐 XX"的追问回答）。"""

    unit_id: str
    rule_code: str
    message: str


class FilterCriteria(BaseModel):
    """考生在推荐页设置的硬性筛选条件（软偏好之外的"一票否决"项）。"""

    regions: list[str] = Field(default_factory=list)  # 意向省份；空 = 不限
    levels: list[str] = Field(default_factory=list)  # 层次标签，如 ["985","211"]；空 = 不限
    major_categories: list[str] = Field(default_factory=list)  # 意向门类；空 = 不限
    tuition_max: int | None = None  # 学费硬上限（元/年）
    exclude_unit_ids: list[str] = Field(default_factory=list)  # 手动排除


class FilterResult(BaseModel):
    """过滤输出：``passed`` 进入概率与打分；``rejected`` 每条都带剔除原因。"""

    passed: list[AdmissionUnit] = Field(default_factory=list)
    rejected: list[RejectionReason] = Field(default_factory=list)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


# ====================================================================
# 省份规则包（AGENTS.md §6.6，批次级建模 ADR-006）
# ====================================================================


class BatchRule(BaseModel):
    """一个省的**一个批次**。★ 一个省必然有多个批次，各自规则不同（ADR-006）。

    任何规则数字必须带 ``source_url`` 与 ``verified_year``（还须带 ``source_quote``
    官方原文摘录）。没有来源的数字不许写进代码。
    """

    batch_code: str  # "zhejiang.public.seg1" / "beijing.undergrad.regular"
    batch_name: str  # "普通类第一段专业平行志愿"
    unit_type: UnitType
    max_volunteers: int  # 80 / 96 / 24 / 30 / 50 ...
    majors_per_group: int | None = None  # 4 / 6 / None
    has_major_adjustment: bool  # True=院校专业组, False=专业+院校
    is_parallel: bool  # ★ True=平行志愿, False=顺序志愿
    tiers_quota: dict[str, float] | None = None  # 仅平行志愿有意义；None 时回落 ModelParams.quota
    source_url: str
    source_quote: str  # ★ 官方原文摘录，供审计
    verified_status: VerifiedStatus = VerifiedStatus.UNVERIFIED
    verified_year: int | None = None

    # ---- 扩展字段（可选；仅在有官方原文时填写，未核实的批次一律 None，不得编造）
    admission_ratio: str | None = None  # 投档比例，如 "1:1"（上海已核实）
    tie_break_rules: list[str] | None = None  # 同分排序位序规则（上海已核实 6 级）
    adjustment_scope: str | None = None  # 调剂边界，如 "仅限组内"（上海已核实）
    withdrawal_clause: list[str] | None = None  # 退档情形（上海已核实）

    # ---- 未核实维度的显式声明（★ 宁可不答，不可编造：假设必须可见且可测）
    # 带 assumptions 的批次，verified_status 不得为 PRIMARY（tests/test_rules.py 强制）。
    assumptions: list[str] = Field(default_factory=list)

    # ---- 已知待办 / 时效提醒（不影响来源等级；与 assumptions 的区别见 DATA_DICTIONARY）
    # 例："依据为 2020/2021 年官网问答，未取当年录取工作意见再核"
    caveats: list[str] = Field(default_factory=list)


class SubjectPool(BaseModel):
    """省份 3+3 **选考科目池**（AGENTS.md §8.1 Step 2 的唯一数据来源）。

    这是**规则事实**（"从几门里选 3 门"），因此与 ``BatchRule`` 同受来源纪律约束：
    没有 ``source_url`` + ``source_quote`` 就不许写进代码（宁可不答，不可编造）。

    ⚠️ 科目池是**省级**规则，与批次无关；未核实到官方原文的省份保持 ``None``，
    由 ``services.meta_service`` 以「招生计划反推」方式给出**明确标注非官方**的降级视图，
    绝不把反推结果伪装成规则（见 ``origin`` 字段）。
    """

    province: str
    mode: str  # "7选3" / "6选3"
    choose: int = 3  # 需选门数（3+3 恒为 3，独立成字段以防未来改革）
    subjects: list[str]  # 官方规范科目名（如"思想政治"，不是"政治"）
    source_url: str = ""
    source_quote: str = ""  # 官方原文摘录（逐字，不得改写）
    verified_status: VerifiedStatus = VerifiedStatus.UNVERIFIED
    verified_year: int | None = None
    caveats: list[str] = Field(default_factory=list)


# ====================================================================
# 模型参数（唯一权威来源：docs/DOMAIN_RULES.md §3）
# ====================================================================


class ModelParams(BaseModel):
    """概率与规划模型参数。

    ⚠️ 纪律（DOMAIN_RULES.md §3.1）：任何参数改动必须重跑回测并在
    ``docs/DECISIONS.md`` 附前后指标对比。``quota`` 是全局默认配额——
    ADR-006 后配额已下沉到 ``BatchRule.tiers_quota``，本字段仅在批次未显式
    配置时回落使用，且仅对 ``is_parallel=True`` 的批次有意义。
    """

    # ---- §6.2 Step 1 数据窗口
    history_years: int = 3  # 取近 N 年
    year_weights: list[float] = Field(default_factory=lambda: [0.5, 0.3, 0.2])  # 由近及远
    derived_quality_weight: float = 0.9  # DERIVED 数据降权

    # ---- Step 3 趋势修正
    trend_lambda: float = 0.5
    trend_clip_ratio: float = 0.10  # 趋势修正幅度限幅 ±10%

    # ---- Step 4 计划数修正
    plan_beta: float = 0.4
    plan_delta_clip: float = 0.5  # 计划变动率限幅 ±50%

    # ---- Step 5 波动性
    min_sigma_abs: float = 300.0  # σ 绝对下限（位次）
    min_sigma_rel: float = 0.03  # σ 相对下限（占预测位次比例）

    # ---- Step 6 概率
    prob_clip_low: float = 0.02
    prob_clip_high: float = 0.98

    # ---- Step 7 波动收缩
    cv_threshold: float = 0.15
    shrinkage_max: float = 0.35
    shrinkage_slope: float = 2.0

    # ---- Step 8 置信度
    min_plan_for_high: int = 10
    min_plan_for_medium: int = 5
    cv_for_high: float = 0.10
    small_plan_warn: int = 5

    # ---- 数据校验：分数↔位次自洽容忍度（M6 / ADR-015）
    #: 官方分数段表（is_synthetic=0）的容忍度：分数与位次必须严格自洽，±2 分为舍入容差
    rank_score_gap: int = 2
    #: **标定估计**的一分一段表（无官方分数段表时由当年投档记录导出，
    #: is_synthetic=1）的容忍度：反查分数与该专业实际最低分的偏差是估计残差，
    #: 不是数据错误；超过 ``rank_score_gap`` 即发 WARNING，超过本值才判 ERROR。
    #: 实测（2026-09，浙江 2023/2024/2025）：最大残差 38 分，99.5% 的记录完全自洽。
    modeled_score_gap: int = 50

    # ---- Step 8.6 安全闸门：判为"保/垫"所需的最少历史年数（M6 / ADR-015 缺陷 6）
    #: 只有 1–2 年历史就承诺"这是底线"是不负责任的：真实数据回测里 6 例保底失效**全部**
    #: 是"历史年份太少、把某年的一次性低位当成长期底线"。默认 3 年（= history_years）。
    #: 历史年数不足时降级为 WEN 并打 ``SAFETY_YEARS_NOT_ENOUGH``。
    min_baodian_years: int = 3

    # ---- §6.3 分层边界
    tier_bounds: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "TOO_RISKY": (0.00, 0.10),
            "CHONG": (0.10, 0.40),
            "WEN": (0.40, 0.75),
            "BAO": (0.75, 0.93),
            "DIAN": (0.93, 1.00),
        }
    )
    # 全局默认配额（缺省值，ADR-006 后下沉到批次级 BatchRule）
    quota: dict[str, float] = Field(
        default_factory=lambda: {"CHONG": 0.25, "WEN": 0.40, "BAO": 0.25, "DIAN": 0.10}
    )

    # ---- §6.8 安全垫
    # ★ 回测标定（DOMAIN_RULES §3.1）：0.15 → 0.25 → 0.30 → **0.60**（2026-02 M5 重标定）
    #
    # 为什么要重标：0.30 是在**有偏样本**上标出来的。当时 M1 的候选院校池
    # ``local + strong + sampled`` 按 id 排序后再截断 ``[:110]``，而院校 id 以省名开头，
    # 于是排在后半段的省份**本省院校被整段丢掉**（浙江考生看不到浙江大学，
    # 且外省普通院校的抽样名额也被截断吃掉）。修正该缺陷并重新播种后，0.30 不再达标：
    # 保底失效率 0.07%（≠0）、稳档命中率 83.0%（<85%）。
    #
    # 在修正数据上做的全量扫描（浙江 150 考生）与跨省验证（浙江/山东/北京）：
    #   0.30 → 保底失效 0.07% · 稳档 83.0%
    #   0.40 → 保底失效 0.07% · 稳档 85.5%
    #   0.50 → 保底失效 0.00% · 稳档 86.9%（北京 84.72%，仍差 0.3 点）
    #   0.60 → 保底失效 0.00% · 稳档 浙江 88.1 / 山东 90.5 / 北京 86.1  ← 三省四项全达标
    # 0.60 是**使三省同时达标的最小值**；再往上（0.75）会把保底样本进一步压小，
    # 等于用"更少的保底志愿"换指标，不取。前后对比见 docs/DECISIONS.md ADR-014。
    safety_margin: float = 0.60  # 保底需优于考生位次的余量
    min_dian_abs: int = 3  # 垫底志愿最少数量
    min_dian_ratio: float = 0.05  # 垫底占总量比例下限
    min_dian_when_small_plan: int = 2  # 总志愿数 < 10 时的下限
