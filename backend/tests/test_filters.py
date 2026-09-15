"""硬约束过滤测试（AGENTS.md §6.4）：九类约束 + 可解释剔除原因。"""

from __future__ import annotations

from app.core.filters import (
    BATCH_MISMATCH,
    FOREIGN_LANGUAGE_LIMIT,
    FRESH_GRADUATE_LIMIT,
    GENDER_LIMIT,
    GENDER_UNKNOWN,
    MANUALLY_EXCLUDED,
    PHYSICAL_LIMIT,
    POLITICAL_LIMIT,
    PROVINCE_MISMATCH,
    SINGLE_SUBJECT_LIMIT,
    SINGLE_SUBJECT_UNKNOWN,
    SUBJECT_NOT_MATCHED,
    TRACK_MISMATCH,
    TUITION_LIMIT,
    UNIT_WITHDRAWN,
    YEAR_MISMATCH,
    check_unit,
    filter_units,
    rejection_summary,
    subject_matches,
)
from app.core.models import FilterCriteria, SubjectReqMode, SubjectRequirement

from factories import make_student, make_unit


# ---------------------------------------------------------------------------
# 选考科目（新高考最易出错处，单独覆盖）
# ---------------------------------------------------------------------------
def test_subject_matches_all_modes() -> None:
    chosen = ["物理", "化学", "生物"]
    assert subject_matches(SubjectRequirement(mode=SubjectReqMode.NONE), chosen)
    assert subject_matches(
        SubjectRequirement(mode=SubjectReqMode.ALL_OF, subjects=["物理", "化学"]), chosen
    )
    assert not subject_matches(
        SubjectRequirement(mode=SubjectReqMode.ALL_OF, subjects=["物理", "历史"]), chosen
    )
    assert subject_matches(
        SubjectRequirement(mode=SubjectReqMode.ANY_OF, subjects=["物理", "历史"]), chosen
    )
    assert subject_matches(
        SubjectRequirement(mode=SubjectReqMode.ANY_OF, subjects=["历史", "地理"]), chosen
    ) is False
    # all_of 的空要求视为不限
    assert subject_matches(SubjectRequirement(mode=SubjectReqMode.ALL_OF, subjects=[]), chosen)


def test_check_unit_passes_clean_unit() -> None:
    assert check_unit(make_unit(), make_student()) is None


# ---------------------------------------------------------------------------
# 逐条约束
# ---------------------------------------------------------------------------
def test_province_year_batch_track_mismatch() -> None:
    student = make_student()
    assert check_unit(make_unit(province="beijing"), student).rule_code == PROVINCE_MISMATCH
    assert check_unit(make_unit(year=2025), student).rule_code == YEAR_MISMATCH
    assert (
        check_unit(make_unit(batch="zhejiang.public.seg2"), student, allowed_batches=["zhejiang.public.seg1"]).rule_code
        == BATCH_MISMATCH
    )
    from app.core.models import StudentProfile

    other_track = StudentProfile(
        id="s", province=student.province, year=student.year, track="物理类", total_score=600, rank=1000
    )
    assert check_unit(make_unit(), other_track).rule_code == TRACK_MISMATCH


def test_subject_requirement_variants() -> None:
    student = make_student(subjects=["物理", "生物", "地理"])
    unit = make_unit(subject_requirement=SubjectRequirement(mode=SubjectReqMode.ALL_OF, subjects=["物理", "化学"]))
    reason = check_unit(unit, student)
    assert reason is not None and reason.rule_code == SUBJECT_NOT_MATCHED
    assert "均须选考" in reason.message

    unit_any = make_unit(subject_requirement=SubjectRequirement(mode=SubjectReqMode.ANY_OF, subjects=["物理", "历史"]))
    assert check_unit(unit_any, student) is None


def test_gender_limit_and_unknown_gender() -> None:
    unit = make_unit(gender_limit="男")
    assert check_unit(unit, make_student(gender=None)).rule_code == GENDER_UNKNOWN
    assert check_unit(unit, make_student(gender="女")).rule_code == GENDER_LIMIT
    assert check_unit(unit, make_student(gender="男")) is None


def test_physical_conflicts() -> None:
    from app.core.models import PhysicalExam

    blind = make_student(physical_exam=PhysicalExam(color_blindness=True))
    assert check_unit(make_unit(physical_requirements=["色盲不宜"]), blind).rule_code == PHYSICAL_LIMIT
    weak = make_student(physical_exam=PhysicalExam(color_weakness=True))
    assert check_unit(make_unit(physical_requirements=["色弱限报"]), weak).rule_code == PHYSICAL_LIMIT
    other = make_student(physical_exam=PhysicalExam(other_restrictions=["身高低于155cm不宜"]))
    assert (
        check_unit(make_unit(physical_requirements=["身高低于155cm不宜报考"]), other).rule_code
        == PHYSICAL_LIMIT
    )
    # 无相关限制时通过
    assert check_unit(make_unit(physical_requirements=["色盲不宜"]), make_student()) is None


def test_foreign_language_and_single_subject() -> None:
    japanese = make_student(foreign_language="日语")
    assert (
        check_unit(make_unit(foreign_language_requirement="英语"), japanese).rule_code
        == FOREIGN_LANGUAGE_LIMIT
    )
    unit = make_unit(single_subject_min={"英语": 120})
    assert check_unit(unit, make_student(single_subject_scores={"英语": 110})).rule_code == SINGLE_SUBJECT_LIMIT
    assert check_unit(unit, make_student(single_subject_scores={})).rule_code == SINGLE_SUBJECT_UNKNOWN
    assert check_unit(unit, make_student(single_subject_scores={"英语": 130})) is None


def test_fresh_graduate_and_political() -> None:
    assert (
        check_unit(make_unit(fresh_graduate_only=True), make_student(is_fresh_graduate=False)).rule_code
        == FRESH_GRADUATE_LIMIT
    )
    assert (
        check_unit(make_unit(political_requirement="中共党员"), make_student(political_status="群众")).rule_code
        == POLITICAL_LIMIT
    )


def test_tuition_withdrawn_and_manual_exclusion() -> None:
    student = make_student()
    assert (
        check_unit(make_unit(tuition=45000), student, criteria=FilterCriteria(tuition_max=20000)).rule_code
        == TUITION_LIMIT
    )
    assert check_unit(make_unit(tuition=45000), student) is None  # 未设上限则不限制
    assert check_unit(make_unit(is_withdrawn=True), student).rule_code == UNIT_WITHDRAWN
    unit = make_unit()
    assert (
        check_unit(unit, student, criteria=FilterCriteria(exclude_unit_ids=[unit.unit_id])).rule_code
        == MANUALLY_EXCLUDED
    )


def test_intent_as_hard_optional() -> None:
    """意向省份/层次/门类默认是**软偏好**；显式开启才当硬约束。"""
    unit = make_unit()  # 浙江单位
    student = make_student()
    criteria = FilterCriteria(regions=["beijing"], levels=["985"], major_categories=["医学"])
    assert check_unit(unit, student, criteria=criteria) is None
    assert check_unit(unit, student, criteria=criteria, intent_as_hard=True) is not None
    # 层次过滤需要调用方提供 level_tags
    assert (
        check_unit(
            unit,
            student,
            criteria=FilterCriteria(levels=["985"]),
            level_tags=["985", "211", "双一流"],
            intent_as_hard=True,
        )
        is None
    )


# ---------------------------------------------------------------------------
# 批量过滤
# ---------------------------------------------------------------------------
def test_filter_units_returns_passed_and_explainable_rejections() -> None:
    student = make_student(subjects=["物理", "生物", "地理"])
    units = [
        make_unit(major="100111"),
        make_unit(major="100112", subject_requirement=SubjectRequirement(mode=SubjectReqMode.ALL_OF, subjects=["物理", "化学"])),
        make_unit(major="100113", province="beijing"),
        make_unit(major="100114", is_withdrawn=True),
    ]
    result = filter_units(units, student)
    assert len(result.passed) == 1
    assert result.rejected_count == 3
    codes = {reason.rule_code for reason in result.rejected}
    assert codes == {SUBJECT_NOT_MATCHED, PROVINCE_MISMATCH, UNIT_WITHDRAWN}
    assert all(reason.message for reason in result.rejected)
    assert all(reason.unit_id for reason in result.rejected)
    assert rejection_summary(result) == {
        PROVINCE_MISMATCH: 1,
        SUBJECT_NOT_MATCHED: 1,
        UNIT_WITHDRAWN: 1,
    }
