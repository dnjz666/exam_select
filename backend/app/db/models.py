"""SQLAlchemy 表定义（L2 数据层，AGENTS.md §5.2）。

强制要求（AGENTS.md §5.2）：
1. 所有数据表必须有 ``source_url`` 与 ``is_synthetic``（§5.2 DDL 草图中未画出
   ``is_synthetic`` 的表按此强制要求补齐）；没有来源的数字不许入库。
2. ``data_quality`` 取值与语义见 ``docs/DOMAIN_RULES.md`` §2.2。
3. ``total_candidates`` 必须来自 ``province_year_stats``，不得估算（§2.3）。

位次口径：``min_rank`` 数值越小越靠前（DOMAIN_RULES.md §2.1）。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ScoreRankTable(Base):
    """一分一段表（位次法的地基）。"""

    __tablename__ = "score_rank_table"
    __table_args__ = (UniqueConstraint("province", "year", "track", "score"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province: Mapped[str] = mapped_column(String(16), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    track: Mapped[str] = mapped_column(String(16), nullable=False)  # 3+3 用 "综合"；预留
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    count_at_score: Mapped[int] = mapped_column(Integer, nullable=False)
    cumulative_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class College(Base):
    """院校。"""

    __tablename__ = "colleges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # f"{province}-{college_code}"
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    province: Mapped[str | None] = mapped_column(String(16))
    city: Mapped[str | None] = mapped_column(String(32))
    level_tags: Mapped[str | None] = mapped_column(String(128))  # JSON: ["985","211","双一流"]
    college_type: Mapped[str | None] = mapped_column(String(32))  # 综合/理工/师范/医药...
    affiliation: Mapped[str | None] = mapped_column(String(64))  # 教育部/省属/...
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    postgrad_rate: Mapped[float | None] = mapped_column(Float)  # 保研率
    master_points: Mapped[int | None] = mapped_column(Integer)
    doctor_points: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(String(512))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Major(Base):
    """专业。"""

    __tablename__ = "majors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32))  # 门类
    discipline: Mapped[str | None] = mapped_column(String(64))  # 专业类
    degree: Mapped[str | None] = mapped_column(String(32))
    duration: Mapped[int | None] = mapped_column(Integer)
    subject_eval_grade: Mapped[str | None] = mapped_column(String(8))  # A+/A/B+...
    source_url: Mapped[str | None] = mapped_column(String(512))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AdmissionUnitRow(Base):
    """投档单位（当年）—— core.models.AdmissionUnit 的落库形态。"""

    __tablename__ = "admission_units"
    __table_args__ = (
        UniqueConstraint("province", "year", "college_id", "group_code", "major_id"),
    )

    unit_id: Mapped[str] = mapped_column(
        String(96), primary_key=True
    )  # f"{province}-{year}-{college_code}-{group_code}-{major_code}"
    unit_type: Mapped[str] = mapped_column(String(16), nullable=False)  # MAJOR_COLLEGE | MAJOR_GROUP
    province: Mapped[str] = mapped_column(String(16), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    batch: Mapped[str] = mapped_column(String(64), nullable=False)
    college_id: Mapped[str] = mapped_column(String(64), nullable=False)
    group_code: Mapped[str | None] = mapped_column(String(16))  # 专业+院校模式为 NULL
    group_name: Mapped[str | None] = mapped_column(String(128))
    major_id: Mapped[str | None] = mapped_column(String(64))
    major_name: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_requirement: Mapped[str] = mapped_column(String(256), nullable=False)  # JSON
    subject_req_status: Mapped[str] = mapped_column(String(16), nullable=False)  # PARSED | PARSE_FAILED
    plan_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tuition: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[int | None] = mapped_column(Integer)
    campus: Mapped[str | None] = mapped_column(String(128))
    remarks: Mapped[str | None] = mapped_column(String(512))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # ★ 1=模拟数据
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)


class AdmissionPlan(Base):
    """招生计划历史快照（用于跨年计划数对比）。"""

    __tablename__ = "admission_plans"
    __table_args__ = (UniqueConstraint("unit_key", "year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_key: Mapped[str] = mapped_column(String(80), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)


class AdmissionHistory(Base):
    """投档/录取历史（往年）—— 位次算法的输入。"""

    __tablename__ = "admission_history"
    __table_args__ = (UniqueConstraint("unit_key", "year", "is_collected"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_key: Mapped[str] = mapped_column(String(80), nullable=False)
    province: Mapped[str] = mapped_column(String(16), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    batch: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(16), nullable=False)
    college_id: Mapped[str] = mapped_column(String(64), nullable=False)
    group_code: Mapped[str | None] = mapped_column(String(16))
    major_id: Mapped[str | None] = mapped_column(String(64))
    min_score: Mapped[int | None] = mapped_column(Integer)
    min_rank: Mapped[int | None] = mapped_column(Integer)  # ★ 核心字段；数值越小越靠前
    avg_score: Mapped[int | None] = mapped_column(Integer)
    avg_rank: Mapped[int | None] = mapped_column(Integer)
    plan_count: Mapped[int | None] = mapped_column(Integer)
    admitted_count: Mapped[int | None] = mapped_column(Integer)
    is_collected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 征集志愿
    data_quality: Mapped[str] = mapped_column(String(16), nullable=False)  # OK|DERIVED|MISSING_RANK|COLLECTED|SUSPECT
    total_candidates: Mapped[int | None] = mapped_column(Integer)  # 位次归一化分母，禁止估算
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ProvinceYearStats(Base):
    """省级年度元数据（位次归一化的分母来源）。

    ★ M6 新增两列（ADR-015）：真实数据接入后发现"总量"与"一段线口径"必须分开记——
    各年分数段表覆盖的最低分不同，累计人数自然不同（浙江 2026 官方表最低 266 分 → 292,753；
    而一段线上的累计人数只有 184,816）。两者混用会让跨年位次失真：

    * ``total_candidates``：该年分数段表**覆盖的最低分**对应的累计人数（官方原文口径）。
      ★ 它**就是位次归一化的分母** —— 因为库中历史位次同样覆盖到二段（浙江 27.7–29.1 万），
      两者必须同口径；
    * ``segment1_cumulative``：**一段线上的累计人数**（历年同口径）。用途是**标定**：
      无官方分数段表年份的"分数—累计人数"曲线要在官方一段线处精确闭合到它；
    * ``segment1_line``：该年普通类一段线分数。

    ``segment1_*`` 为 NULL 时表示模拟数据（没有"一段线"这个概念）。
    """

    __tablename__ = "province_year_stats"

    province: Mapped[str] = mapped_column(String(16), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    track: Mapped[str] = mapped_column(String(16), primary_key=True)
    total_candidates: Mapped[int] = mapped_column(Integer, nullable=False)
    segment1_cumulative: Mapped[int | None] = mapped_column(Integer)
    segment1_line: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ====================================================================
# M3 新增：考生档案 与 志愿表（ADR-010）
# 说明：这两张表存的是**用户产生的数据**（档案草稿与志愿表），不是外部数据源，
# 因此 source_url 记录其来源口径（考生自述 / 系统生成），is_synthetic 沿用模拟数据标记。
# ====================================================================


class Student(Base):
    """考生档案（§5.3 StudentProfile 的落库形态）。

    嵌套结构（选考科目、体检、偏好、单科成绩）以 JSON 文本列存储，
    口径见 ``docs/DATA_DICTIONARY.md`` §7。
    """

    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    province: Mapped[str] = mapped_column(String(16), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    track: Mapped[str] = mapped_column(String(16), nullable=False, default="综合")
    subjects: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list[str]
    total_score: Mapped[int | None] = mapped_column(Integer)  # 草稿态可为空，以 missing_fields 为准
    rank: Mapped[int | None] = mapped_column(Integer)  # 位次；缺省由一分一段表换算，绝不估算
    gender: Mapped[str | None] = mapped_column(String(4))
    is_fresh_graduate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    political_status: Mapped[str] = mapped_column(String(16), nullable=False, default="群众")
    foreign_language: Mapped[str] = mapped_column(String(16), nullable=False, default="英语")
    single_subject_scores: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON dict
    physical_exam: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON dict
    bonus_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bonus_type: Mapped[str | None] = mapped_column(String(32))
    preferences: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON dict
    missing_fields: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list[str]
    rank_source_url: Mapped[str | None] = mapped_column(String(512))  # 位次换算的来源（可追溯）
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False, default="draft://student-profile")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Plan(Base):
    """志愿表（§6.7 VolunteerPlan 的落库形态）。

    ``payload`` 存整份 ``VolunteerPlan`` 的 JSON（含逐项证据链）；
    批次规则快照、分层分布、违规与风险都随 payload 走，保证"导出即可复现"。
    """

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    student_id: Mapped[str] = mapped_column(String(64), nullable=False)
    province: Mapped[str] = mapped_column(String(16), nullable=False)
    batch_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_parallel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON: VolunteerPlan
    risks: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list[Risk]
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False, default="generated://planner")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ====================================================================
# M5 新增：对话消息（ADR-013）
# 与 students/plans 同理：这是**用户产生的数据**，source_url 记录来源口径
# （agent://chat = 由 agent 层产生），is_synthetic 沿用模拟数据标记。
# ====================================================================


class ChatMessage(Base):
    """一条会话消息。

    为什么要**落库**而不是留在进程内存（M3 的做法）：会话历史是考生回看"我当时问了什么、
    系统依据什么这么答"的唯一凭据；进程重启就清空，等于把证据链丢了。
    ``tool_calls`` 特别重要——它是"这句话里的数字是从哪查出来的"的直接证据。
    """

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    student_id: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: 本轮调用的工具名 + 参数 + 返回值（JSON）——护栏的判据，也是给考生看的"查了什么"
    tool_calls: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    missing_fields: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    #: deterministic | llm | deterministic-fallback
    mode: Mapped[str | None] = mapped_column(String(32))
    #: 是否被护栏拦截过（拦截说明模型试图编造，值得留痕以便复盘）
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False, default="agent://chat")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AppMeta(Base):
    """键值元数据（ADR-019）。

    目前只存 ``data_version`` —— **持久化的数据代次令牌**，用于让"结果缓存"在
    **跨进程重启**后依然能被正确失效。

    ★ 为什么必须有它：进程内代数号（ADR-016 的 ``_generation``）重启就归零，
    若把它写进持久缓存键，重启后旧结果会被当成新结果命中。
    ★ 为什么不能靠"行数变化"判断：实测回填 ``majors.category`` 时**行数没变**，
    但归类全变了 —— 只有写入方显式 bump 才可靠。
    """

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)


class ResultCache(Base):
    """计算结果持久缓存（ADR-019）——"相似问题下次直接调用"。

    ★ 缓存什么：``recommend`` 的完整响应体。它**只依赖**
    ``(数据代次, 省, 年, 位次, 筛选, 权重, 参数, limit, 批次, 是否含过险)``，
    与考生身份无关（``item_payload`` 不含 student_id；概率只依赖位次，见 probability 文档）。
    因此同位次 + 同筛选的**另一位考生**也能安全复用。
    ★ 失效：``data_version`` 变化（重新播种 / 回填）即整体失效；
    参数或筛选变化会生成不同的 ``cache_key``，天然不命中。
    """

    __tablename__ = "result_cache"

    #: 内容指纹（sha256），见 services.cache_service.fingerprint_recommend
    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: 写入时的数据代次；读取时必须相等，否则视为未命中
    data_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: 缓存类别（目前只有 recommend；为后续 plan/probability 预留）
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 人类可读的键摘要，便于排错与运维查看（不参与匹配）
    label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_hit_at: Mapped[str | None] = mapped_column(String(32))
