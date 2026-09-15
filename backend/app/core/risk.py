"""风险扫描（AGENTS.md §6.8）—— 全 14 个风险码，每个都必须给出可执行建议。

铁律
----
- 梯度类风险码（``NO_SAFETY_NET`` / ``SAFETY_NOT_SAFE`` / ``GRADIENT_INVERSION`` /
  ``INSUFFICIENT_COUNT``）**仅适用于平行志愿批次**（``is_parallel=True``）；
  顺序志愿批次不做冲稳保梯度校验（ADR-006）。
- 保底判定用**名师铁律 4**：垫底志愿近三年最低位次必须**全部**优于考生位次且留有余量。
- 纯函数，无 IO（ADR-003）。
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence

from app.core.models import (
    AdmissionRecord,
    BatchRule,
    ModelParams,
    Risk,
    RiskLevel,
    StudentProfile,
    Tier,
    VolunteerPlan,
    unit_key_of,
)
from app.core.probability import usable_records
from app.core.rank import normalize_rank

# ---- 风险码常量（与 §6.8 表格一一对应）----
NO_SAFETY_NET = "NO_SAFETY_NET"
SAFETY_NOT_SAFE = "SAFETY_NOT_SAFE"
GRADIENT_INVERSION = "GRADIENT_INVERSION"
INSUFFICIENT_COUNT = "INSUFFICIENT_COUNT"
PLAN_TOO_SMALL = "PLAN_TOO_SMALL"
VOLATILE_HISTORY = "VOLATILE_HISTORY"
NO_HISTORY = "NO_HISTORY"
SINGLE_YEAR_DATA = "SINGLE_YEAR_DATA"
NO_OBEDIENCE = "NO_OBEDIENCE"
GROUP_UNACCEPTABLE = "GROUP_UNACCEPTABLE"
PHYSICAL_LIMIT = "PHYSICAL_LIMIT"
TUITION_HIGH = "TUITION_HIGH"
SUSPECT_DATA = "SUSPECT_DATA"
COLLECTED_ONLY = "COLLECTED_ONLY"

ALL_RISK_CODES: tuple[str, ...] = (
    NO_SAFETY_NET,
    SAFETY_NOT_SAFE,
    GRADIENT_INVERSION,
    INSUFFICIENT_COUNT,
    PLAN_TOO_SMALL,
    VOLATILE_HISTORY,
    NO_HISTORY,
    SINGLE_YEAR_DATA,
    NO_OBEDIENCE,
    GROUP_UNACCEPTABLE,
    PHYSICAL_LIMIT,
    TUITION_HIGH,
    SUSPECT_DATA,
    COLLECTED_ONLY,
)

_LEVEL_RANK: dict[str, int] = {"985": 5, "211": 4, "双一流": 3}


def level_rank(level_tags: Sequence[str] | None) -> int:
    """院校层次的可比较序数（985 > 211 > 双一流 > 其他）。"""
    tags = set(level_tags or ())
    for tag, rank in _LEVEL_RANK.items():
        if tag in tags:
            return rank
    return 2


def _usable(
    histories: Mapping[str, Sequence[AdmissionRecord]], unit_id: str, year: int
) -> tuple[list[AdmissionRecord], list[str]]:
    key = unit_key_of(unit_id)
    return usable_records(histories.get(key, ()), unit_key=key, target_year=year)


def _normalized_values(
    records: Sequence[AdmissionRecord], current_total: int | None
) -> list[float]:
    values: list[float] = []
    for record in records:
        if record.min_rank is None:
            continue
        if current_total and record.total_candidates:
            values.append(normalize_rank(int(record.min_rank), record.total_candidates, current_total))
        else:
            values.append(float(record.min_rank))
    return values


def scan_risks(
    plan: VolunteerPlan,
    *,
    student: StudentProfile,
    histories: Mapping[str, Sequence[AdmissionRecord]],
    params: ModelParams,
    batch: BatchRule,
    current_total_candidates: int | None = None,
    group_majors: Mapping[tuple[str, str], Sequence[str]] | None = None,
    college_level_tags: Mapping[str, Sequence[str]] | None = None,
) -> list[Risk]:
    """扫描志愿表风险，返回风险清单（HIGH 优先）。

    :param histories: ``unit_key -> 历史记录``（可由 L4 批量查库后传入）。
    :param group_majors: ``(college_id, group_code) -> 组内专业名``，
        用于 ``GROUP_UNACCEPTABLE``（冲进去被调剂到排斥专业是真实事故）。
    :param college_level_tags: ``college_id -> 层次标签``，用于 ``GRADIENT_INVERSION``。
    """
    risks: list[Risk] = []
    group_majors = group_majors or {}
    college_level_tags = college_level_tags or {}
    items = plan.items
    is_parallel = batch.is_parallel

    # ---------------- 梯度类（仅平行志愿批次，ADR-006）----------------
    if is_parallel:
        dian_required = max(
            params.min_dian_when_small_plan if batch.max_volunteers < 10 else params.min_dian_abs,
            int(params.min_dian_ratio * batch.max_volunteers + 0.9999),
        )
        dian_items = [item for item in items if item.tier is Tier.DIAN]
        if len(dian_items) < dian_required:
            risks.append(
                Risk(
                    code=NO_SAFETY_NET,
                    level=RiskLevel.HIGH,
                    message=(
                        f"垫底（DIAN）志愿只有 {len(dian_items)} 个，少于要求的 {dian_required} 个"
                    ),
                    suggestion="增加绝对保底志愿：选择近三年位次都明显低于你位次、且计划数充足的单位。",
                )
            )

        # 名师铁律 4：垫底志愿"真保底"检验（方向勘误，ADR-009）
        # 正确语义：**考生位次必须比该单位近三年最难年份的切线还靠前 ≥ safety_margin**，
        # 即 min(近三年归一化最低位次) ≥ 考生位次 × (1 + safety_margin)。
        # （文档 R-007 字面写作"单位位次优于考生位次"，那等于单位更难=不安全，与"保底"自相矛盾。）
        if student.rank is not None and dian_items:
            required = student.rank * (1 + params.safety_margin)
            for item in dian_items:
                records, _ = _usable(histories, item.unit.unit_id, item.unit.year)
                window = records[:3]
                normalized = _normalized_values(window, current_total_candidates)
                hardest = min(normalized) if normalized else None
                if hardest is None or hardest < required or len(window) < 2:
                    detail = (
                        f"近三年最难年份位次 {hardest:,.0f}，未达到所需余量 "
                        f"{required:,.0f}（考生位次 {student.rank:,} 的 "
                        f"{1 + params.safety_margin:.0%}）"
                        if hardest is not None
                        else "没有可用历史"
                    )
                    risks.append(
                        Risk(
                            code=SAFETY_NOT_SAFE,
                            level=RiskLevel.HIGH,
                            unit_id=item.unit.unit_id,
                            message=f"垫底志愿 {item.unit.major_name} 不够安全：{detail}",
                            suggestion=(
                                f"更换更稳的保底：要求该单位近三年**每一年**的切线都比你位次靠后 "
                                f"≥{params.safety_margin:.0%}（即最差年份也 ≥ {required:,.0f}）。"
                            ),
                        )
                    )

        if len(items) < int(batch.max_volunteers * 0.8):
            risks.append(
                Risk(
                    code=INSUFFICIENT_COUNT,
                    level=RiskLevel.MEDIUM,
                    message=(
                        f"仅填报 {len(items)} 个志愿，不足上限 {batch.max_volunteers} 的 80%"
                    ),
                    suggestion="建议填满：平行志愿下多填一个就是多一次机会，空着等于浪费。",
                )
            )

        # 顺序倒挂：后序志愿层次更高且更稳
        for i in range(len(items) - 1):
            current, following = items[i], items[i + 1]
            cur_level = level_rank(college_level_tags.get(current.unit.college_id))
            next_level = level_rank(college_level_tags.get(following.unit.college_id))
            cur_p = current.probability or 0.0
            next_p = following.probability or 0.0
            if next_level > cur_level and next_p > cur_p + 0.05:
                risks.append(
                    Risk(
                        code=GRADIENT_INVERSION,
                        level=RiskLevel.MEDIUM,
                        unit_id=following.unit.unit_id,
                        message=(
                            f"第 {following.position} 志愿（层次更高、概率更高）排在第 "
                            f"{current.position} 志愿之后"
                        ),
                        suggestion=(
                            "平行志愿按填报顺序检索，最想去的必须放最前：建议把更想去、"
                            "更稳的志愿往前调。"
                        ),
                    )
                )
                break

    # ---------------- 单位级风险 ----------------
    for item in items:
        unit = item.unit
        records, warnings = _usable(histories, unit.unit_id, unit.year)
        window = records[:3]
        values = _normalized_values(window, current_total_candidates)

        if unit.plan_count < params.small_plan_warn:
            risks.append(
                Risk(
                    code=PLAN_TOO_SMALL,
                    level=RiskLevel.MEDIUM,
                    unit_id=unit.unit_id,
                    message=f"计划数仅 {unit.plan_count} 人（< {params.small_plan_warn}）",
                    suggestion="招生人数少，位次波动大、历史参考价值低：建议增加同层次替代志愿。",
                )
            )

        if not records:
            risks.append(
                Risk(
                    code=NO_HISTORY,
                    level=RiskLevel.MEDIUM,
                    unit_id=unit.unit_id,
                    message="新增专业/新增院校：无任何可用历史数据",
                    suggestion=(
                        "系统已用同层次、同地区、同类单位做类比（置信度 LOW）："
                        "填报前务必核对招生章程与计划数。"
                    ),
                )
            )
        elif len(records) == 1:
            risks.append(
                Risk(
                    code=SINGLE_YEAR_DATA,
                    level=RiskLevel.MEDIUM,
                    unit_id=unit.unit_id,
                    message="仅有 1 年有效历史数据",
                    suggestion="单年数据参考价值有限，无法识别大小年：建议降定位、留足余量。",
                )
            )

        if "SUSPECT" in warnings or any(
            r.data_quality.value == "SUSPECT" for r in histories.get(unit_key_of(unit.unit_id), ())
        ):
            risks.append(
                Risk(
                    code=SUSPECT_DATA,
                    level=RiskLevel.HIGH,
                    unit_id=unit.unit_id,
                    message="历史数据存在自相矛盾（quality=SUSPECT）",
                    suggestion="该单位数据需人工核实（位次与分数不匹配），核实前不要作为保底。",
                )
            )

        if records and all(r.data_quality.value == "COLLECTED" for r in window):
            risks.append(
                Risk(
                    code=COLLECTED_ONLY,
                    level=RiskLevel.MEDIUM,
                    unit_id=unit.unit_id,
                    message="历史仅来自征集志愿（征集线通常更低）",
                    suggestion="征集志愿线偏低会高估概率：请按正常批次的位次重新定位。",
                )
            )

        if len(values) >= 2:
            mean = statistics.fmean(values)
            cv = statistics.pstdev(values) / mean if mean else 0.0
            if cv > params.cv_threshold:
                risks.append(
                    Risk(
                        code=VOLATILE_HISTORY,
                        level=RiskLevel.MEDIUM,
                        unit_id=unit.unit_id,
                        message=f"近三年位次波动剧烈（cv={cv:.2f} > {params.cv_threshold}）",
                        suggestion="该单位大小年明显：不要按最好那年定位，按最差那年留余量。",
                    )
                )

        # 服从调剂（院校专业组模式的生死线）
        if batch.has_major_adjustment and item.obey_adjustment is not True:
            risks.append(
                Risk(
                    code=NO_OBEDIENCE,
                    level=RiskLevel.HIGH,
                    unit_id=unit.unit_id,
                    message="院校专业组模式下未勾选服从专业调剂",
                    suggestion=(
                        "★ 退档风险：不服从调剂时，所填专业未录即被退档；"
                        "除组内专业全部不可接受外，强烈建议勾选服从调剂。"
                    ),
                )
            )

        # 组内含考生明确排斥的专业
        excluded = set(student.preferences.excluded_majors)
        if excluded:
            majors_in_group = group_majors.get((unit.college_id, unit.group_code or ""), ())
            hit = sorted(excluded & set(majors_in_group))
            if hit:
                risks.append(
                    Risk(
                        code=GROUP_UNACCEPTABLE,
                        level=RiskLevel.MEDIUM,
                        unit_id=unit.unit_id,
                        message=f"该组含考生明确排斥的专业：{'、'.join(hit)}",
                        suggestion=(
                            "冲进去也可能被调剂到这些专业：要么换组，要么确认可以接受后再填。"
                        ),
                    )
                )

        # 体检受限
        exam = student.physical_exam
        for requirement in unit.physical_requirements:
            conflict = (
                (exam.color_blindness and "色盲" in requirement)
                or (exam.color_weakness and "色弱" in requirement)
                or any(r and (r in requirement or requirement in r) for r in exam.other_restrictions)
            )
            if conflict:
                risks.append(
                    Risk(
                        code=PHYSICAL_LIMIT,
                        level=RiskLevel.HIGH,
                        unit_id=unit.unit_id,
                        message=f"体检受限：该单位要求「{requirement}」",
                        suggestion="必须移除该志愿，或核实招生章程后确认是否可报。",
                    )
                )
                break

        # 学费超预算
        comfortable = student.preferences.budget_comfortable
        if comfortable is not None and unit.tuition > comfortable:
            risks.append(
                Risk(
                    code=TUITION_HIGH,
                    level=RiskLevel.LOW,
                    unit_id=unit.unit_id,
                    message=f"学费 {unit.tuition:,} 元/年 超过预算舒适线 {comfortable:,} 元/年",
                    suggestion="确认家庭可承受四年总投入后再填；中外合作/民办尤需注意。",
                )
            )

    risks.sort(key=lambda r: (0 if r.level is RiskLevel.HIGH else 1 if r.level is RiskLevel.MEDIUM else 2, r.code))
    return risks


def risk_summary(risks: Sequence[Risk]) -> dict[str, int]:
    """按风险码计数（供 UI 面板与回测报告）。"""
    summary: dict[str, int] = {}
    for risk in risks:
        summary[risk.code] = summary.get(risk.code, 0) + 1
    return dict(sorted(summary.items()))


__all__ = [
    "ALL_RISK_CODES",
    "COLLECTED_ONLY",
    "GRADIENT_INVERSION",
    "GROUP_UNACCEPTABLE",
    "INSUFFICIENT_COUNT",
    "NO_HISTORY",
    "NO_OBEDIENCE",
    "NO_SAFETY_NET",
    "PHYSICAL_LIMIT",
    "PLAN_TOO_SMALL",
    "SAFETY_NOT_SAFE",
    "SINGLE_YEAR_DATA",
    "SUSPECT_DATA",
    "TUITION_HIGH",
    "VOLATILE_HISTORY",
    "level_rank",
    "risk_summary",
    "scan_risks",
]
