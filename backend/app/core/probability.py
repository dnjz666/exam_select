"""录取概率模型（AGENTS.md §6.2）—— 全系统的心脏。

实现严格对应 §6.2 的 Step 0 ~ Step 8.5，参数全部来自 :class:`ModelParams`
（唯一权威来源 ``docs/DOMAIN_RULES.md`` §3），**本模块不得出现业务魔数**。

三条不可动摇的纪律
------------------
1. **防数据泄漏**：只使用 ``year < target.year`` 的历史行。今年（或未来）的结果
   绝不能进入预测——否则回测会虚高、线上会自我实现。
2. **宁可不答**：有效历史为 0 年且类比池不足 3 个 → ``probability = None`` + ``NO_DATA``，
   绝不猜测。
3. **证据链完整**：``evidence`` 每条都带 ``source_url``，``reasons`` 里的数字必须能被复算。

纯函数：无 IO、无 DB、无 LLM（ADR-003）。调用方（L4）负责取数与组装。
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from scipy.stats import norm

from app.core.models import (
    Adjustment,
    AdmissionRecord,
    AdmissionUnit,
    Confidence,
    DataQuality,
    HistoryEvidence,
    ModelParams,
    ProbabilityResult,
    StudentProfile,
    Tier,
    unit_key_of,
)
from app.core.rank import normalize_rank

# ---- 参与计算的 data_quality（DOMAIN_RULES.md §2.2）----
USABLE_QUALITIES: frozenset[DataQuality] = frozenset(
    {DataQuality.OK, DataQuality.DERIVED, DataQuality.COLLECTED}
)

# ---- 风险 / 警告码（供 risk.py、UI 与 narrator 引用）----
W_NO_HISTORY = "NO_HISTORY"
W_SINGLE_YEAR_DATA = "SINGLE_YEAR_DATA"
W_SMALL_PLAN = "PLAN_TOO_SMALL"
W_COLLECTED_ONLY = "COLLECTED_ONLY"
W_VOLATILE_HISTORY = "VOLATILE_HISTORY"
W_DERIVED_DATA = "DERIVED_DATA_DOWNWEIGHTED"
W_SUSPECT_IGNORED = "SUSPECT_DATA_IGNORED"
W_MISSING_RANK_IGNORED = "MISSING_RANK_IGNORED"
W_NO_NORMALIZATION_BASIS = "NO_NORMALIZATION_BASIS"
W_ANALOG_POOL = "ANALOG_POOL_FALLBACK"
W_UNKNOWN_BATCH = "UNKNOWN_BATCH"
W_SAFETY_MARGIN_NOT_MET = "SAFETY_MARGIN_NOT_MET"  # 概率够高但留不出 15% 余量 → 不可称保底


@dataclass(frozen=True)
class AnalogUnit:
    """Step 0 类比池的一个成员：同地区 + 同院校层次 + 同专业类的其他单位。"""

    unit: AdmissionUnit
    records: Sequence[AdmissionRecord] = field(default_factory=tuple)
    level_tags: tuple[str, ...] = ()
    discipline: str | None = None
    college_province: str | None = None


def usable_records(
    history: Iterable[AdmissionRecord], *, unit_key: str, target_year: int
) -> tuple[list[AdmissionRecord], list[str]]:
    """筛出可用于预测的历史行（同单位 + 年份早于目标年 + 质量可用 + 有位次）。

    公共工具：``probability`` / ``risk`` / ``backtest`` 共用同一套筛选口径，
    避免"概率模型过滤了 MISSSING_RANK，风险扫描却用了"这类不一致。

    返回 ``(可用记录, 警告)``，记录按年份**从新到旧**排序。
    """
    usable: list[AdmissionRecord] = []
    warnings: list[str] = []
    ignored_quality: set[str] = set()
    for record in history:
        if record.unit_key != unit_key:
            continue
        if record.year >= target_year:  # ★ 防数据泄漏
            continue
        if record.min_rank is None:
            ignored_quality.add(DataQuality.MISSING_RANK.value)
            continue
        if record.data_quality not in USABLE_QUALITIES:
            ignored_quality.add(record.data_quality.value)
            continue
        usable.append(record)
    usable.sort(key=lambda r: -r.year)
    if DataQuality.SUSPECT.value in ignored_quality:
        warnings.append(W_SUSPECT_IGNORED)
    if DataQuality.MISSING_RANK.value in ignored_quality:
        warnings.append(W_MISSING_RANK_IGNORED)
    return usable, warnings


def _usable_records(
    history: Iterable[AdmissionRecord], target: AdmissionUnit
) -> tuple[list[AdmissionRecord], list[str]]:
    """单位级包装：由 ``target`` 推出 ``unit_key`` 与 ``target_year``。"""
    return usable_records(
        history, unit_key=unit_key_of(target.unit_id), target_year=target.year
    )


def _normalized_ranks(
    records: Sequence[AdmissionRecord],
    *,
    current_total: int | None,
    warnings: list[str],
) -> list[float]:
    """Step 1：历史位次统一归一化到今年（``R × N_今年 / N_当年``）。"""
    if not records:
        return []
    if current_total is None:
        # 缺今年的考生总数 → 无法归一化。此时按"人数不变"处理并**显式告警**，
        # 由置信度上限约束其可信度（不得静默当作已归一化）。
        warnings.append(W_NO_NORMALIZATION_BASIS)
        return [float(r.min_rank) for r in records if r.min_rank is not None]

    normalized: list[float] = []
    for record in records:
        if record.total_candidates is None or record.total_candidates <= 0:
            warnings.append(W_NO_NORMALIZATION_BASIS)
            normalized.append(float(record.min_rank or 0))
            continue
        normalized.append(normalize_rank(int(record.min_rank), record.total_candidates, current_total))
    return normalized


def _tier_of(probability: float, params: ModelParams) -> Tier:
    """按 ``tier_bounds`` 判定分层（区间左闭右开，最后一档右闭）。"""
    bounds = params.tier_bounds
    ordered = sorted(bounds.items(), key=lambda kv: kv[1][0])
    for index, (name, (low, high)) in enumerate(ordered):
        is_last = index == len(ordered) - 1
        if (low <= probability < high) or (is_last and low <= probability <= high):
            return Tier(name)
    return Tier.NO_DATA  # pragma: no cover - bounds 覆盖 [0,1]


def _sigma(values: Sequence[float]) -> float:
    """Step 5 的 σ_raw：样本少时用 MAD 兜底（§6.2 Step 5）。"""
    if len(values) < 2:
        return 0.0
    spread = statistics.pstdev(values)
    if len(values) < 3:
        median = statistics.median(values)
        mad = statistics.median([abs(v - median) for v in values])
        return max(spread, 1.4826 * mad)
    return spread


def analog_key(
    college_province: str | None, level_tags: Sequence[str] | None, discipline: str | None
) -> tuple[str | None, tuple[str, ...], str | None]:
    """Step 0 类比池的分桶键：**同地区 + 同院校层次 + 同专业类**。"""
    return (college_province, tuple(sorted(level_tags or ())), discipline)


def build_analog_index(
    units: Iterable[AnalogUnit],
) -> dict[tuple[str | None, tuple[str, ...], str | None], list[AnalogUnit]]:
    """把类比单位按 :func:`analog_key` 分桶，供 ``estimate_probability`` 直接取用整桶。

    这样调用方不需要为每个目标单位传入全量类比池（否则 Step 0 会退化成 O(N) 扫描）。
    """
    index: dict[tuple[str | None, tuple[str, ...], str | None], list[AnalogUnit]] = {}
    for analog in units:
        index.setdefault(
            analog_key(analog.college_province, analog.level_tags, analog.discipline), []
        ).append(analog)
    return index


def estimate_probability(
    student: StudentProfile,
    target: AdmissionUnit,
    history: Sequence[AdmissionRecord],
    rule: object,
    params: ModelParams,
    *,
    current_total_candidates: int | None = None,
    analog_pool: Sequence[AnalogUnit] | None = None,
) -> ProbabilityResult:
    """估算考生被 ``target`` 录取的概率（§6.2 八步）。

    :param rule: ``ProvinceRule``（用于取批次上下文与来源状态）；本函数只读其 ``get_batch``。
    :param current_total_candidates: 今年该省该科类考生总数（位次归一化的分母，
        ``province_year_stats`` 提供；缺失时降级并告警）。
    :param analog_pool: Step 0 的类比池（同地区 + 同层次 + 同专业类）。
    """
    warnings: list[str] = []
    reasons: list[str] = []
    adjustments: list[Adjustment] = []

    batch = None
    get_batch = getattr(rule, "get_batch", None)
    if callable(get_batch):
        try:
            batch = get_batch(target.batch)
        except Exception:  # noqa: BLE001 - 未知批次不影响概率计算，但要告警
            warnings.append(W_UNKNOWN_BATCH)

    # ================= Step 1：取历史位次并归一化 =================
    records, quality_warnings = _usable_records(history, target)
    warnings.extend(quality_warnings)
    window = params.history_years
    used = records[:window]
    values = _normalized_ranks(used, current_total=current_total_candidates, warnings=warnings)
    if W_NO_NORMALIZATION_BASIS in warnings:
        reasons.append(
            "缺少今年考生总数（province_year_stats），历史位次未做人数归一化，"
            "该结果的可信度已下调——请补齐年度考生人数后再采信。"
        )

    if not values:
        # ================= Step 0：无历史数据回退 =================
        return _step0_no_history(
            student, target, params, analog_pool or (), current_total_candidates, warnings, batch
        )

    if len(used) == 1:
        warnings.append(W_SINGLE_YEAR_DATA)
    # ================= Step 2：加权预测今年最低位次 =================
    weights = list(params.year_weights[: len(values)])
    weight_sum = sum(weights)
    if weight_sum <= 0:  # pragma: no cover - ModelParams 保证为正
        weights = [1.0] * len(values)
        weight_sum = float(len(values))
    weights = [w / weight_sum for w in weights]
    predicted = sum(w * v for w, v in zip(weights, values))

    # ================= Step 3：趋势修正 =================
    if len(values) >= 2:
        slope = (values[0] - values[-1]) / (len(values) - 1)  # 近 - 远；位次变小 = 越来越热
        clip = params.trend_clip_ratio * predicted
        slope = max(-clip, min(clip, slope))
        before = predicted
        predicted = predicted + params.trend_lambda * slope
        if before > 0 and abs(predicted - before) > 1e-9:
            adjustments.append(
                Adjustment(
                    name="trend",
                    delta=(predicted - before) / before,
                    reason=(
                        f"近三年位次趋势 slope={slope:+.0f}（负值=越来越热），"
                        f"按 λ={params.trend_lambda} 修正，预测位次 {before:,.0f} → {predicted:,.0f}"
                    ),
                )
            )

    # ================= Step 4：计划数修正（强信号）=================
    plan_current = target.plan_count
    plan_previous = used[0].plan_count if used and used[0].plan_count else None
    if plan_previous:
        delta_plan = (plan_current - plan_previous) / plan_previous
        clipped = max(-params.plan_delta_clip, min(params.plan_delta_clip, delta_plan))
        before = predicted
        predicted = predicted * (1 + params.plan_beta * clipped)
        adjustments.append(
            Adjustment(
                name="plan_count",
                delta=(predicted - before) / before if before else 0.0,
                reason=(
                    f"计划数 {plan_previous} → {plan_current}"
                    f"（{delta_plan:+.0%}{'，已限幅' if clipped != delta_plan else ''}），"
                    f"按 β={params.plan_beta} 修正，预测位次 {before:,.0f} → {predicted:,.0f}"
                ),
            )
        )
    else:
        reasons.append("上一年的招生计划数缺失，未做计划数修正。")

    # ================= Step 5：波动性度量 =================
    sigma_raw = _sigma(values)
    sigma = max(sigma_raw, params.min_sigma_rel * predicted, params.min_sigma_abs)

    # ================= Step 6：z 分数与概率 =================
    if student.rank is None:
        return ProbabilityResult(
            probability=None,
            tier=Tier.NO_DATA,
            confidence=Confidence.NO_DATA,
            predicted_min_rank=predicted,
            sigma=sigma,
            evidence=_evidence(used),
            adjustments=adjustments,
            reasons=["考生位次缺失，无法计算录取概率。请先由一分一段表换算位次或直接填写位次。"],
            warnings=sorted(set(warnings)),
        )
    z = (predicted - student.rank) / sigma if sigma > 0 else 0.0
    probability = float(norm.cdf(z))
    probability = max(params.prob_clip_low, min(params.prob_clip_high, probability))

    # ================= Step 7：波动收缩 =================
    # ★ 实现勘误（ADR-009）：§6.2 原文的加法形式 `P = 0.5 + (P-0.5)(1-κ)` 会把**任何**概率
    #   压进 [0.5κ, 1-0.5κ]（κ≤0.35 时即 [0.175, 0.825]）——波动大的单位将**永远无法**被判为
    #   TOO_RISKY（<0.10）或 DIAN（≥0.93），而毫无希望的考生也会被报成 12%~40%，
    #   实测把冲档命中率从 ~19% 砸到 ~1.5%（回测证据见 DECISIONS ADR-009）。
    #   收缩的语义是"降低自信"，因此改为**放大 σ**（等价于把 z 按 (1-κ) 缩放）：
    #   概率同样向 0.5 靠拢，但排序性、单调性与两端可达性都不被破坏。
    mean_value = statistics.fmean(values)
    cv = sigma_raw / mean_value if mean_value else 0.0
    if cv > params.cv_threshold:
        kappa = min(params.shrinkage_max, (cv - params.cv_threshold) * params.shrinkage_slope)
        sigma_before = sigma
        sigma = sigma / (1.0 - kappa)
        probability = float(norm.cdf((predicted - student.rank) / sigma))
        probability = max(params.prob_clip_low, min(params.prob_clip_high, probability))
        adjustments.append(
            Adjustment(
                name="volatility_shrinkage",
                delta=(sigma - sigma_before) / sigma_before if sigma_before else 0.0,
                reason=(
                    f"历史波动 cv={cv:.3f} > {params.cv_threshold}（大小年明显）→ "
                    f"σ 由 {sigma_before:,.0f} 放大到 {sigma:,.0f}（等价 z×{1 - kappa:.3f}），"
                    f"降低自信但不把概率压进分层中段"
                ),
            )
        )
        warnings.append(W_VOLATILE_HISTORY)

    # ================= Step 8：置信度分级 =================
    qualities = {r.data_quality for r in used}
    has_derived = DataQuality.DERIVED in qualities
    has_collected = DataQuality.COLLECTED in qualities
    if has_derived:
        warnings.append(W_DERIVED_DATA)
    if all(r.data_quality is DataQuality.COLLECTED for r in used):
        warnings.append(W_COLLECTED_ONLY)
    if plan_current < params.small_plan_warn:
        warnings.append(W_SMALL_PLAN)

    confidence = _confidence(
        years=len(used),
        qualities=qualities,
        plan_count=plan_current,
        cv=cv,
        params=params,
        normalization_missing=W_NO_NORMALIZATION_BASIS in warnings,
    )

    # ================= Step 8.5：输出（含完整证据链）=================
    reasons.extend(_narrative(student, target, used, values, predicted, sigma, probability, _tier_of(probability, params), confidence))
    if batch is not None and getattr(batch, "is_parallel", True) is False:
        reasons.append(
            "注意：该志愿属于**顺序志愿**批次，第一志愿命中率决定一切，"
            "第 2 志愿起近乎无效——保底职责不能交给这个批次。"
        )

    # ================= Step 8.6：安全闸门（★ 名师铁律 4「保底要真保底」）=================
    # 保/垫是**安全承诺**，不能只由概率区间给出：还要求考生位次比该单位近三年**最差年份**
    # （位次数值最大者）的切线仍靠前 ≥ safety_margin（默认 15%）。
    # 不满足则降级为 WEN 并显式告警——宁可不叫"保底"，也不给假保底。
    tier, gate_warning = _safety_gated_tier(probability, values, student.rank, params)
    if gate_warning:
        warnings.append(gate_warning)
        reasons.append(
            f"原始概率 {probability:.1%}（区间上属 {_tier_of(probability, params).value}），"
            f"但该单位近三年最差年份位次 {max(values):,.0f} 未给考生留出 "
            f"{params.safety_margin:.0%} 余量（需 ≥ {student.rank * (1 + params.safety_margin):,.0f}），"
            f"因此降级为 {tier.value}：**不满足「真保底」，不能当垫底用**。"
        )

    return ProbabilityResult(
        probability=probability,
        tier=tier,
        confidence=confidence,
        predicted_min_rank=predicted,
        sigma=sigma,
        evidence=_evidence(used),
        adjustments=adjustments,
        reasons=reasons,
        warnings=sorted(set(warnings)),
    )


def _safety_gated_tier(
    probability: float,
    values: Sequence[float],
    student_rank: int | None,
    params: ModelParams,
) -> tuple[Tier, str | None]:
    """按名师铁律 4 给 BAO/DIAN 加"真保底"闸门。

    判定（DOMAIN_RULES R-007 的本意，注意方向）：
    ``min(近三年归一化最低位次) ≥ 考生位次 × (1 + safety_margin)``
    —— 即**考生位次比该单位最差年份的切线还靠前 15% 以上**，才允许称"保底/垫底"。
    """
    band_tier = _tier_of(probability, params)
    if band_tier not in (Tier.BAO, Tier.DIAN) or student_rank is None or not values:
        return band_tier, None
    hardest_year_rank = min(values)  # 位次数值最小 = 该单位最难的一年
    required = student_rank * (1.0 + params.safety_margin)
    if hardest_year_rank >= required:
        return band_tier, None
    return Tier.WEN, W_SAFETY_MARGIN_NOT_MET


# ---------------------------------------------------------------------------
# Step 0：无历史数据回退
# ---------------------------------------------------------------------------
def _step0_no_history(
    student: StudentProfile,
    target: AdmissionUnit,
    params: ModelParams,
    analog_pool: Sequence[AnalogUnit],
    current_total: int | None,
    warnings: list[str],
    batch: object | None,
) -> ProbabilityResult:
    """新增专业/新增院校：用**同地区 + 同层次 + 同专业类**的 ≥3 个单位做类比。"""
    warnings = list(warnings)
    warnings.append(W_NO_HISTORY)
    reasons = ["该单位没有任何可用历史数据（新增专业/新增院校），禁止直接猜测概率。"]

    target_province = target.province
    candidates: list[float] = []
    analog_evidence: list[HistoryEvidence] = []
    for analog in analog_pool:
        # 同地区：类比单位与目标单位位于同一省（按院校所在省判断）
        if analog.college_province and analog.college_province != target.college_id.split("-", 1)[0]:
            continue
        analog_records, _ = _usable_records(analog.records, analog.unit)
        if not analog_records:
            continue
        latest = analog_records[0]
        if latest.min_rank is None:
            continue
        if current_total is not None and latest.total_candidates:
            candidates.append(normalize_rank(int(latest.min_rank), latest.total_candidates, current_total))
        else:
            candidates.append(float(latest.min_rank))
        # ★ 类比证据：显式标注"这不是本单位历史"，避免被误当成真实历史
        #   （§7 契约铁律 1 要求 recommend 每项 evidence 非空）
        analog_evidence.append(
            HistoryEvidence(
                year=latest.year,
                min_rank=latest.min_rank,
                min_score=latest.min_score,
                plan_count=latest.plan_count,
                data_quality=latest.data_quality,
                is_collected=latest.is_collected,
                source_url=latest.source_url,
                note=f"类比单位 {analog.unit.unit_id}",
            )
        )
    # 同一招生省份（所有候选单位来自同一省，target_province 仅用于可读性）
    _ = target_province

    if len(candidates) < 3:
        reasons.append(
            f"类比池不足（同地区+同层次+同专业类的可用单位仅 {len(candidates)} 个，需 ≥3 个），"
            "因此返回 NO_DATA：宁可不答，不可编造。"
        )
        return ProbabilityResult(
            probability=None,
            tier=Tier.NO_DATA,
            confidence=Confidence.NO_DATA,
            predicted_min_rank=0.0,
            sigma=0.0,
            evidence=[],
            adjustments=[],
            reasons=reasons,
            warnings=sorted(set(warnings)),
        )

    warnings.append(W_ANALOG_POOL)
    predicted = statistics.median(candidates)
    sigma_raw = statistics.pstdev(candidates) if len(candidates) >= 2 else 0.0
    sigma = max(sigma_raw, params.min_sigma_rel * predicted, params.min_sigma_abs)
    if student.rank is None:
        reasons.append("考生位次缺失，无法计算录取概率。")
        return ProbabilityResult(
            probability=None,
            tier=Tier.NO_DATA,
            confidence=Confidence.NO_DATA,
            predicted_min_rank=predicted,
            sigma=sigma,
            reasons=reasons,
            warnings=sorted(set(warnings)),
        )
    z = (predicted - student.rank) / sigma if sigma > 0 else 0.0
    probability = float(norm.cdf(z))
    probability = max(params.prob_clip_low, min(params.prob_clip_high, probability))
    reasons.append(
        f"采用类比池（{len(candidates)} 个单位）的位次中位数 {predicted:,.0f} 作为预测位次，"
        f"σ 取类比池标准差 {sigma_raw:,.0f}（不低于 {params.min_sigma_abs:,.0f}），"
        f"得到概率 {probability:.1%}。**置信度强制为 LOW**。"
    )
    if batch is not None and getattr(batch, "is_parallel", True) is False:
        reasons.append("注意：该志愿属于顺序志愿批次，第 2 志愿起近乎无效。")
    # 无本单位历史 → 无法验证"真保底"余量 → 不允许称保底/垫底（名师铁律 4）
    analog_tier = _tier_of(probability, params)
    if analog_tier in (Tier.BAO, Tier.DIAN):
        warnings.append(W_SAFETY_MARGIN_NOT_MET)
        reasons.append(
            f"该单位为新增（无本单位历史），无法验证「真保底」余量，"
            f"因此把 {analog_tier.value} 降级为 WEN——**无历史的数据不能当垫底**。"
        )
        analog_tier = Tier.WEN
    return ProbabilityResult(
        probability=probability,
        tier=analog_tier,
        confidence=Confidence.LOW,
        predicted_min_rank=predicted,
        sigma=sigma,
        evidence=analog_evidence,
        adjustments=[
            Adjustment(
                name="analog_pool",
                delta=0.0,
                reason=f"无历史，使用 {len(candidates)} 个同层次同类单位的位次中位数",
            )
        ],
        reasons=reasons,
        warnings=sorted(set(warnings)),
    )


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _confidence(
    *,
    years: int,
    qualities: set[DataQuality],
    plan_count: int,
    cv: float,
    params: ModelParams,
    normalization_missing: bool,
) -> Confidence:
    """Step 8 置信度分级（§6.2）。``normalization_missing`` 时最高只能到 MEDIUM。"""
    if years == 0:
        return Confidence.NO_DATA
    low_reasons = years == 1 or plan_count < params.min_plan_for_medium or DataQuality.MISSING_RANK in qualities
    if low_reasons:
        return Confidence.LOW
    if (
        years >= 3
        and qualities <= {DataQuality.OK}
        and plan_count >= params.min_plan_for_high
        and cv <= params.cv_for_high
        and not normalization_missing
    ):
        return Confidence.HIGH
    if years in (2, 3) and plan_count >= params.min_plan_for_medium:
        if normalization_missing:
            return Confidence.MEDIUM
        return Confidence.MEDIUM
    return Confidence.LOW


def _evidence(records: Sequence[AdmissionRecord]) -> list[HistoryEvidence]:
    return [
        HistoryEvidence(
            year=r.year,
            min_rank=r.min_rank,
            min_score=r.min_score,
            plan_count=r.plan_count,
            data_quality=r.data_quality,
            is_collected=r.is_collected,
            source_url=r.source_url,
        )
        for r in records
    ]


def _narrative(
    student: StudentProfile,
    target: AdmissionUnit,
    used: Sequence[AdmissionRecord],
    values: Sequence[float],
    predicted: float,
    sigma: float,
    probability: float,
    tier: Tier,
    confidence: Confidence,
) -> list[str]:
    """人话解释：数字必须与证据链一一对应（供 LLM 原样转述）。"""
    years_text = "、".join(
        f"{r.year}年 {r.min_rank:,}" for r in used if r.min_rank is not None
    )
    lines = [
        f"你今年位次 {student.rank:,}，目标单位 {target.major_name}（{target.college_id}）"
        f"近 {len(used)} 年最低位次：{years_text}（来源见证据链）。",
        f"按位次法加权预测今年最低位次约 {predicted:,.0f}（σ={sigma:,.0f}），"
        f"估算录取概率 {probability:.1%}，属于「{tier.value}」，置信度 {confidence.value}。",
    ]
    if values:
        lines.append(
            f"归一化后各年位次：{'、'.join(f'{v:,.0f}' for v in values)}"
            f"（已按考生人数变化折算到今年）。"
        )
    return lines


def probability_interval(
    result: ProbabilityResult, params: ModelParams
) -> tuple[float, float] | None:
    """把单点概率转成 **±1σ 区间**（UI 必须显示区间，AGENTS.md §8 强制要求）。

    推导：``P = Φ((R_pred − R_s)/σ)``，对 ``R_pred`` 的不确定性取 ±1σ，
    得到区间 ``[Φ(z−1), Φ(z+1)]``；仍受 ``prob_clip_*`` 约束。
    """
    if result.probability is None or result.sigma <= 0:
        return None
    z = norm.ppf(max(min(result.probability, 0.999999), 0.000001))
    low = float(norm.cdf(z - 1.0))
    high = float(norm.cdf(z + 1.0))
    low = max(params.prob_clip_low, min(params.prob_clip_high, low))
    high = max(params.prob_clip_low, min(params.prob_clip_high, high))
    return (min(low, high), max(low, high))


__all__ = [
    "AnalogUnit",
    "USABLE_QUALITIES",
    "W_ANALOG_POOL",
    "W_COLLECTED_ONLY",
    "W_DERIVED_DATA",
    "W_MISSING_RANK_IGNORED",
    "W_NO_HISTORY",
    "W_NO_NORMALIZATION_BASIS",
    "W_SINGLE_YEAR_DATA",
    "W_SMALL_PLAN",
    "W_SUSPECT_IGNORED",
    "W_UNKNOWN_BATCH",
    "W_VOLATILE_HISTORY",
    "analog_key",
    "build_analog_index",
    "estimate_probability",
    "probability_interval",
    "usable_records",
]
