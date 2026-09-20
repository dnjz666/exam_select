"""硬约束过滤（AGENTS.md §6.4）。

按顺序执行，**任一不满足直接剔除**，并记录可解释原因
（用于回答"为什么没推荐 XX"）。纯函数，无 IO（ADR-003）。

顺序（§6.4）
------------
1. province / year / batch / track 匹配
2. 选考科目（``all_of`` / ``any_of`` / ``none``；新高考最易出错处）
3. 性别限制
4. 体检结论（色盲/色弱/身高/视力等）
5. 外语语种
6. 单科成绩要求
7. 应届/往届、政治面貌
8. 学费上限（用户设定即视为硬约束）
9. 已撤销 / 停招

另外支持：手动排除、以及可选的"意向范围当硬约束"（``intent_as_hard=True``；
默认关闭，因为省份/层次/门类的意向属于**软偏好**，见 §6.5）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from app.core.models import (
    AdmissionUnit,
    FilterCriteria,
    FilterResult,
    Major,
    RejectionReason,
    StudentProfile,
    SubjectReqMode,
    SubjectRequirement,
)

# ---------------------------------------------------------------------------
# 规则码（RejectionReason.rule_code，稳定字符串，供前端与追问引用）
# ---------------------------------------------------------------------------
PROVINCE_MISMATCH = "PROVINCE_MISMATCH"
YEAR_MISMATCH = "YEAR_MISMATCH"
BATCH_MISMATCH = "BATCH_MISMATCH"
TRACK_MISMATCH = "TRACK_MISMATCH"
SUBJECT_NOT_MATCHED = "SUBJECT_NOT_MATCHED"
SUBJECT_UNPARSED = "SUBJECT_UNPARSED"
GENDER_LIMIT = "GENDER_LIMIT"
GENDER_UNKNOWN = "GENDER_UNKNOWN"
PHYSICAL_LIMIT = "PHYSICAL_LIMIT"
FOREIGN_LANGUAGE_LIMIT = "FOREIGN_LANGUAGE_LIMIT"
SINGLE_SUBJECT_LIMIT = "SINGLE_SUBJECT_LIMIT"
SINGLE_SUBJECT_UNKNOWN = "SINGLE_SUBJECT_UNKNOWN"
FRESH_GRADUATE_LIMIT = "FRESH_GRADUATE_LIMIT"
POLITICAL_LIMIT = "POLITICAL_LIMIT"
TUITION_LIMIT = "TUITION_LIMIT"
UNIT_WITHDRAWN = "UNIT_WITHDRAWN"
MANUALLY_EXCLUDED = "MANUALLY_EXCLUDED"
REGION_NOT_INTENDED = "REGION_NOT_INTENDED"
LEVEL_NOT_INTENDED = "LEVEL_NOT_INTENDED"
MAJOR_CATEGORY_NOT_INTENDED = "MAJOR_CATEGORY_NOT_INTENDED"

_COLOR_BLIND_KEYS = ("色盲",)
_COLOR_WEAK_KEYS = ("色弱",)


def subject_matches(requirement: SubjectRequirement, subjects: Sequence[str]) -> bool:
    """选考科目判定（DOMAIN_RULES.md §2.4）。

    3+3 下考生恰好 3 门选考，判定为集合关系：

    - ``none``  → 恒通过
    - ``all_of`` → ``set(要求) ⊆ set(考生选考)``
    - ``any_of`` → ``set(要求) ∩ set(考生选考) ≠ ∅``
    """
    if requirement.mode is SubjectReqMode.NONE or not requirement.subjects:
        return True
    chosen = set(subjects)
    if requirement.mode is SubjectReqMode.ALL_OF:
        return set(requirement.subjects) <= chosen
    if requirement.mode is SubjectReqMode.ANY_OF:
        return bool(set(requirement.subjects) & chosen)
    return True  # pragma: no cover - 枚举已穷尽


def _physical_conflict(student: StudentProfile, unit: AdmissionUnit) -> str | None:
    """体检受限判定：返回冲突描述（None = 无冲突）。"""
    if not unit.physical_requirements:
        return None
    exam = student.physical_exam
    for requirement in unit.physical_requirements:
        if exam.color_blindness and any(k in requirement for k in _COLOR_BLIND_KEYS):
            return f"考生色盲，该单位要求：{requirement}"
        if exam.color_weakness and any(k in requirement for k in _COLOR_WEAK_KEYS):
            return f"考生色弱，该单位要求：{requirement}"
        for restriction in exam.other_restrictions:
            if restriction and (restriction in requirement or requirement in restriction):
                return f"考生体检结论「{restriction}」与该单位要求「{requirement}」冲突"
    return None


def check_unit(
    unit: AdmissionUnit,
    student: StudentProfile,
    *,
    criteria: FilterCriteria | None = None,
    major: Major | None = None,
    level_tags: Sequence[str] | None = None,
    college_province: str | None = None,
    allowed_batches: Sequence[str] | None = None,
    intent_as_hard: bool = False,
) -> RejectionReason | None:
    """逐条硬约束检查；返回第一条不满足的原因（None = 通过）。

    ``level_tags``：院校层次标签（来自 ``College.level_tags``）。仅当
    ``intent_as_hard=True`` 时用于层次过滤——单位本身不携带层次信息。

    ``college_province``：**院校所在地**（来自 ``College.province``）。
    同样只在 ``intent_as_hard=True`` 时用于地区过滤。

    ★ M6 实测缺陷（ADR-017）：这里原先写的是
    ``unit.college_id.split("-", 1)[0]`` —— 那取到的是 **unit_id 的第一段**，
    而 unit_id 是 ``{招生省}-{年份}-…``，所以它永远是**招生省**（浙江考生 = "zhejiang"）。
    后果：只要勾选"把意向地区当硬约束"，**任何地区**（哪怕就是"浙江"）都会把全部
    18,543 个单位剔光，前端显示"没有符合条件的推荐"。地区必须取院校自己的所在地。
    """
    criteria = criteria or FilterCriteria()

    # 1) 省份 / 年份 / 批次 / 科类
    if unit.province != student.province:
        return RejectionReason(
            unit_id=unit.unit_id,
            rule_code=PROVINCE_MISMATCH,
            message=f"招生省份 {unit.province} 与考生省份 {student.province} 不符",
        )
    if unit.year != student.year:
        return RejectionReason(
            unit_id=unit.unit_id,
            rule_code=YEAR_MISMATCH,
            message=f"招生年份 {unit.year} 与考生年份 {student.year} 不符",
        )
    if allowed_batches is not None and unit.batch not in allowed_batches:
        return RejectionReason(
            unit_id=unit.unit_id,
            rule_code=BATCH_MISMATCH,
            message=f"批次 {unit.batch} 不在本次推荐范围内",
        )
    if student.track != "综合":
        return RejectionReason(
            unit_id=unit.unit_id,
            rule_code=TRACK_MISMATCH,
            message=f"本系统面向 3+3 综合改革省份，考生科类 {student.track} 暂不支持",
        )

    # 2) 选考科目
    if not subject_matches(unit.subject_requirement, student.subjects):
        req = "、".join(unit.subject_requirement.subjects)
        mode = "均须选考" if unit.subject_requirement.mode is SubjectReqMode.ALL_OF else "选考其一"
        return RejectionReason(
            unit_id=unit.unit_id,
            rule_code=SUBJECT_NOT_MATCHED,
            message=f"选考科目不匹配：要求{mode} {req}，考生选考 {'、'.join(student.subjects)}",
        )

    # 3) 性别
    if unit.gender_limit:
        if student.gender is None:
            return RejectionReason(
                unit_id=unit.unit_id,
                rule_code=GENDER_UNKNOWN,
                message=f"该单位限{unit.gender_limit}生，但考生性别未采集，无法判定",
            )
        if student.gender != unit.gender_limit:
            return RejectionReason(
                unit_id=unit.unit_id,
                rule_code=GENDER_LIMIT,
                message=f"该单位限{unit.gender_limit}生，考生性别为{student.gender}",
            )

    # 4) 体检
    conflict = _physical_conflict(student, unit)
    if conflict:
        return RejectionReason(unit_id=unit.unit_id, rule_code=PHYSICAL_LIMIT, message=conflict)

    # 5) 外语语种
    if unit.foreign_language_requirement and student.foreign_language != unit.foreign_language_requirement:
        return RejectionReason(
            unit_id=unit.unit_id,
            rule_code=FOREIGN_LANGUAGE_LIMIT,
            message=(
                f"该单位限{unit.foreign_language_requirement}语种考生，"
                f"考生外语为{student.foreign_language}"
            ),
        )

    # 6) 单科成绩
    for subject, minimum in sorted(unit.single_subject_min.items()):
        actual = student.single_subject_scores.get(subject)
        if actual is None:
            return RejectionReason(
                unit_id=unit.unit_id,
                rule_code=SINGLE_SUBJECT_UNKNOWN,
                message=f"该单位要求{subject} ≥ {minimum}，但考生{subject}单科成绩未采集",
            )
        if actual < minimum:
            return RejectionReason(
                unit_id=unit.unit_id,
                rule_code=SINGLE_SUBJECT_LIMIT,
                message=f"该单位要求{subject} ≥ {minimum}，考生{subject}为 {actual}",
            )

    # 7) 应届/往届、政治面貌
    if unit.fresh_graduate_only and not student.is_fresh_graduate:
        return RejectionReason(
            unit_id=unit.unit_id, rule_code=FRESH_GRADUATE_LIMIT, message="该单位仅招应届毕业生"
        )
    if unit.political_requirement and student.political_status != unit.political_requirement:
        return RejectionReason(
            unit_id=unit.unit_id,
            rule_code=POLITICAL_LIMIT,
            message=(
                f"该单位要求政治面貌为{unit.political_requirement}，"
                f"考生为{student.political_status}"
            ),
        )

    # 8) 学费上限（用户设定即硬约束）
    if criteria.tuition_max is not None and unit.tuition > criteria.tuition_max:
        return RejectionReason(
            unit_id=unit.unit_id,
            rule_code=TUITION_LIMIT,
            message=f"学费 {unit.tuition} 元/年 超过设定上限 {criteria.tuition_max} 元/年",
        )

    # 9) 已撤销 / 停招
    if unit.is_withdrawn:
        return RejectionReason(
            unit_id=unit.unit_id, rule_code=UNIT_WITHDRAWN, message="该单位已撤销或停招"
        )

    # 附加：手动排除
    if unit.unit_id in set(criteria.exclude_unit_ids):
        return RejectionReason(
            unit_id=unit.unit_id, rule_code=MANUALLY_EXCLUDED, message="考生已手动排除该志愿"
        )

    # 可选：把意向范围当硬约束（默认关闭；意向属软偏好 §6.5）
    if intent_as_hard:
        # ★ 用**院校所在地**（college_province）判定，不能用 unit_id 的第一段（那是招生省）
        if criteria.regions:
            if college_province is None:
                # 院校所在地缺失 → 无法判定是否在意向地区内。
                # 硬约束是"一票否决"，**不知道就不能否决**（否则真实数据里 892 所
                # 无所在地的院校会被无声剔除，考生以为"这些学校不存在"）。
                pass
            elif college_province not in criteria.regions:
                return RejectionReason(
                    unit_id=unit.unit_id,
                    rule_code=REGION_NOT_INTENDED,
                    message=(
                        f"院校所在地 {college_province} 不在意向地区内"
                        f"（意向：{'、'.join(criteria.regions)}）"
                    ),
                )
        if criteria.levels and not set(criteria.levels) & set(level_tags or ()):
            return RejectionReason(
                unit_id=unit.unit_id,
                rule_code=LEVEL_NOT_INTENDED,
                message=f"院校层次不在意向范围内：{'、'.join(criteria.levels)}",
            )
        if criteria.major_categories and major is not None and major.category not in criteria.major_categories:
            return RejectionReason(
                unit_id=unit.unit_id,
                rule_code=MAJOR_CATEGORY_NOT_INTENDED,
                message=f"专业门类 {major.category} 不在意向范围内",
            )
    return None


def filter_units(
    units: Iterable[AdmissionUnit],
    student: StudentProfile,
    *,
    criteria: FilterCriteria | None = None,
    majors: Mapping[str, Major] | None = None,
    level_tags_by_college: Mapping[str, Sequence[str]] | None = None,
    college_province_by_college: Mapping[str, str | None] | None = None,
    allowed_batches: Sequence[str] | None = None,
    intent_as_hard: bool = False,
) -> FilterResult:
    """批量过滤：返回 ``FilterResult{passed, rejected}``，剔除项**必须可解释**。

    ``college_province_by_college``：``college_id -> 院校所在地``（来自 ``College.province``），
    仅 ``intent_as_hard=True`` 时用于地区硬约束（见 :func:`check_unit` 的勘误说明）。
    """
    majors = majors or {}
    tags_map = level_tags_by_college or {}
    province_map = college_province_by_college or {}
    result = FilterResult()
    for unit in units:
        reason = check_unit(
            unit,
            student,
            criteria=criteria,
            major=majors.get(unit.major_id or ""),
            level_tags=tags_map.get(unit.college_id, ()),
            college_province=province_map.get(unit.college_id),
            allowed_batches=allowed_batches,
            intent_as_hard=intent_as_hard,
        )
        if reason is None:
            result.passed.append(unit)
        else:
            result.rejected.append(reason)
    return result


def rejection_summary(result: FilterResult) -> dict[str, int]:
    """按规则码汇总剔除数量（供"为什么没推荐"与调参观察）。"""
    summary: dict[str, int] = {}
    for reason in result.rejected:
        summary[reason.rule_code] = summary.get(reason.rule_code, 0) + 1
    return dict(sorted(summary.items()))


__all__ = [
    "BATCH_MISMATCH",
    "FOREIGN_LANGUAGE_LIMIT",
    "FRESH_GRADUATE_LIMIT",
    "GENDER_LIMIT",
    "GENDER_UNKNOWN",
    "MANUALLY_EXCLUDED",
    "PHYSICAL_LIMIT",
    "POLITICAL_LIMIT",
    "PROVINCE_MISMATCH",
    "SINGLE_SUBJECT_LIMIT",
    "SINGLE_SUBJECT_UNKNOWN",
    "SUBJECT_NOT_MATCHED",
    "TRACK_MISMATCH",
    "TUITION_LIMIT",
    "UNIT_WITHDRAWN",
    "YEAR_MISMATCH",
    "check_unit",
    "filter_units",
    "rejection_summary",
    "subject_matches",
]
